"""`Service(Subsystem)` for Cognition (docs/blueprint/subsystems/04-
cognition.md section 5, 9): wires `cognition.think`/`.compact.request`,
provider-status ticks, and pause/stop into the pieces built in this
package. `start()` discovers providers, builds one `RollingWindowBudget`
per provider replayed from the Ledger, and subscribes; `stop()`
unsubscribes. Provider availability is re-broadcast every
`availability_poll_seconds` of `system.tick.second` ticks."""

from __future__ import annotations

import asyncio
import dataclasses
import os

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message, time_left
from simorgh.contracts.protocols import Context, Health, ProviderResponse, NULL_TELEMETRY
from simorgh.contracts.registry import error_reply_payload

from .api import capabilities_of, Budget, BudgetExceeded, ContextTooLarge, NoRealProvider, Paused, Purpose
from .assembler import PromptAssembler
from .budget import RollingWindowBudget
from .compaction import Compactor
from .config import Config
from .parser import OutputParser
from .providers.base import FloorProvider
from .providers.claude_code import ClaudeCodeProvider
from .providers.gemini import GeminiProvider
from .providers.together import DEFAULT_MODEL as together_default_model, TogetherProvider
from .router import Router

VERSION = "0.1.0"

# `CognitionThink.expected` is a flat wire enum (text|tool_calls|edit_blocks|
# verdict -- contracts/messages/cognition.py); `OutputParser.parse` wants a
# `{kind, markers?}` dict (04 section 5's `OutputSpec`). "tool_calls" is the
# one case needing real translation: the request's own `tools` list of names
# doubles as the marker set `_parse_markers` scans for.
def _expected_spec(payload: dict) -> dict:
    expected = payload.get("expected")
    if expected == "tool_calls":
        return {"kind": "markers", "markers": tuple(payload.get("tools") or ())}
    if expected in ("edit_blocks", "verdict"):
        return {"kind": expected}
    return {"kind": "final"}


# Live-caught (the creator, real use: Sim telling them "no MCP servers
# connected... no fetch tool" turn after turn, even after `web_fetch`
# and `propose_mcp_server` were real, registered, and in `session.
# profile.tools`): `_expected_spec` above only ever *parses* a reply for
# markers -- nothing ever told the model the marker convention exists in
# the first place, or which tool names it could write. `orchestration/
# session.py` request-side fix (`expected: "tool_calls"`) makes parsing
# reachable at all; this is the other missing half -- a real instruction
# in the prompt, or a model has no way to discover this protocol from
# first principles. Tool names alone (no per-tool argument semantics)
# rather than reaching into Execution's tool registry for real
# descriptions -- that would cross the subsystem boundary
# `test_module_boundaries.py` enforces; a self-descriptive name like
# `web_fetch` is enough on its own. **Second live-catch, same day**: a
# name alone was NOT enough for `propose_mcp_server` -- its one argument
# has real internal structure, and the model invented a wrong JSON shape
# rather than the real `key: value` lines. `payload["tool_hints"]`
# (`orchestration/tools.py::marker_hint`, threaded through by `session.
# py`) is the fix -- a short, hand-maintained, per-tool addendum for the
# handful of tools that actually need one.
def _argument_shape(schema: dict | None) -> str:
    """One short phrase for a tool's arguments, from its schema: the model
    was shown bare upper-cased names and had to guess (stage 2 item 2)."""
    props = (schema or {}).get("properties") or {}
    if not isinstance(props, dict) or not props:
        return ""
    required = set((schema or {}).get("required") or ())
    if len(props) == 1:
        (name,) = props
        return f"argument: {name}"
    fields = [name if name in required else f"{name}?" for name in props]
    return "arguments: " + ", ".join(fields[:8]) + (", ..." if len(fields) > 8 else "")


def _tool_line(tool: str, spec: dict | None) -> str:
    if not spec:
        return f"- {tool.upper()}"
    description = " ".join(str(spec.get("description") or "").split())
    if len(description) > 90:
        description = description[:87].rsplit(" ", 1)[0] + "..."
    shape = _argument_shape(spec.get("input_schema"))
    return f"- {tool.upper()}: {description}" + (f" ({shape})" if shape else "")


def _tool_instruction_block(payload: dict, specs: dict | None = None) -> str | None:
    if payload.get("expected") != "tool_calls":
        return None
    tools = tuple(payload.get("tools") or ())
    if not tools:
        return None
    specs = specs or {}
    # One line per tool: its name, what it does, and its arguments -- from
    # `tool.registered` (stage 2 item 2). Before, only the upper-cased
    # names were shown, so the model knew what a tool was called and had
    # to guess what it did and what it took.
    listing = "\n".join(_tool_line(tool, specs.get(tool)) for tool in sorted(tools))
    lines = [
        "Tools available this turn:\n" + listing + "\n\nTo use one, write its name "
        "in capitals, a colon, then your argument, as the very first line of "
        "your reply -- nothing before it. For example:\nWEB_FETCH: https://example.com\n"
        "Only do this when you genuinely need that tool right now; otherwise "
        "just answer in plain text as normal, with no marker line.",
    ]
    parallel = [tool for tool in (payload.get("parallel_tools") or ()) if tool in tools]
    most = int(payload.get("max_parallel_tools") or 1)
    if len(parallel) > 1 and most > 1:
        lines.append(
            f"Lookups that do not depend on each other can go in one reply, up to {most} at once: "
            + ", ".join(sorted(tool.upper() for tool in parallel))
            + ". Put each marker on its own line; they run together and every result comes back "
            "in the next turn. Any other tool is one per reply, on its own."
        )
    for tool, hint in (payload.get("tool_hints") or {}).items():
        if tool in tools and hint:
            lines.append(f"{tool.upper()}'s own argument format:\n{hint}")
    return "\n\n".join(lines)



def _within_deadline(max_seconds: float, message: Message, now: float) -> float:
    """The think's time cap, shrunk to what the caller will still wait
    (stage 1 item 5), less half a second so the reply beats its timeout --
    but never below what the Router needs to dial one candidate
    (`router._MIN_CANDIDATE_SECONDS`): shrinking under it turns every short
    wait into a floor reply without trying a provider at all."""
    left = time_left(message, now)
    if left is None:
        return max_seconds
    from .router import _MIN_CANDIDATE_SECONDS

    return min(float(max_seconds), max(_MIN_CANDIDATE_SECONDS, left - 0.5))

class Service:
    name = "cognition"
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.COGNITION_THINK, topics.COGNITION_COMPACT_REQUEST,
        topics.SYSTEM_STATE_CHANGED, topics.SYSTEM_TICK_SECOND, topics.SYSTEM_STARTED,
        topics.TOOL_REGISTERED,
    )
    # Requests count as produced: the assembler sends persona.voice,
    # self.summary and world.env.query and waits for their replies.
    produces: tuple[str, ...] = (
        topics.COGNITION_THINK_REPLY, topics.COGNITION_COMPACT_REPLY,
        topics.COGNITION_COMPACT_PRE, topics.COGNITION_COMPACT_DONE,
        topics.COGNITION_PROVIDER_STATUS, topics.SYSTEM_METRICS, topics.UI_NOTICE,
        topics.PERSONA_VOICE, topics.SELF_SUMMARY, topics.WORLD_ENV_QUERY,
    )

    def __init__(self, *, config: Config | None = None, providers: list | None = None) -> None:
        self._config_from_caller = config
        self._config = config or Config()
        self._injected_providers = providers
        self._tool_specs: dict[str, dict] = {}
        self._paused = False
        self._no_real_provider_since: float | None = None
        self._tick_seconds = 0

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        # Live-caught as a class 2026-09-08: every service is handed its
        # own `[section]` from simorgh.toml (`kernel/context.py` builds
        # `ctx.config` for exactly this) and eleven of them never read
        # it. The settings existed, were documented, were parsed into a
        # Config dataclass with a `from_mapping` -- and nothing ever
        # called it, so changing the file changed nothing. The dominant
        # bug shape in this codebase: a designed slot with one side
        # implemented and nobody writing to it.
        #
        # A config passed by the caller still wins, so a test that
        # constructs the service with one is unaffected.
        if self._config_from_caller is None and ctx.config:
            self._config = Config.from_mapping(dict(ctx.config))
        for problem in self._config.problems:
            # A malformed entry used to be skipped in silence, and the Ollama
            # fallback was off for a day with nothing said (2026-09-15).
            ctx.logger.warning("cognition.config_ignored", detail=problem)
        # `SIMORGH_COGNITION_PROVIDER_ORDER=floor` (comma-separated names)
        # chooses who answers without a config file. The test session sets
        # it: every test that booted a real Kernel was making a paid
        # Together call with the operator's own key (2026-09-14). A config
        # or providers handed in by the caller still win.
        order_env = os.environ.get("SIMORGH_COGNITION_PROVIDER_ORDER", "").strip()
        if order_env and self._config_from_caller is None and self._injected_providers is None:
            self._config = dataclasses.replace(
                self._config, provider_order=tuple(p.strip() for p in order_env.split(",") if p.strip()))
        self._floor = FloorProvider()
        if self._injected_providers is not None:
            # test seam: a fake Provider list, so an integration test can
            # boot a real Kernel + real Service without shelling out to an
            # actual CLI or API (04 section 9's own acceptance bar wants a
            # real Service, not a mock of this class).
            real_providers = list(self._injected_providers)
        else:
            real_providers = []
            together_cfg = self._config.providers.get("together")
            if together_cfg is not None:
                # `ctx.secrets` first so an operator can keep the key in
                # the 0600 secrets file (`[cognition] secrets =
                # ["TOGETHER_API_KEY"]`); the provider falls back to the
                # plain environment variable, which is how it is normally
                # set and needs no config at all.
                real_providers.append(TogetherProvider(
                    api_key=ctx.secrets.get("TOGETHER_API_KEY"),
                    model=together_cfg.model or together_default_model,
                    timeout_seconds=together_cfg.timeout_seconds,
                    **({"reasoning_effort": together_cfg.reasoning_effort} if together_cfg.reasoning_effort else {}),
                ))
            # Extra Together instances by name (a stronger model or more
            # effort), for per-purpose routes and escalation.
            from .providers import together as _together

            for extra_name, extra in self._config.providers.items():
                if extra_name == "together" or extra.backend != "together":
                    continue
                real_providers.append(TogetherProvider(
                    api_key=ctx.secrets.get("TOGETHER_API_KEY"), name=extra_name,
                    model=extra.model or together_default_model, timeout_seconds=extra.timeout_seconds,
                    reasoning_effort=extra.reasoning_effort or _together.DEFAULT_REASONING_EFFORT,
                    price_in=extra.price_in or _together.PRICE_IN, price_out=extra.price_out or _together.PRICE_OUT,
                    price_cached_in=extra.price_cached_in or extra.price_in or _together.PRICE_CACHED_IN,
                ))
            real_providers.append(
                ClaudeCodeProvider(timeout_seconds=self._config.providers["claude_code_cli"].timeout_seconds),
            )
            gemini_cfg = self._config.providers.get("gemini")
            if gemini_cfg is not None:
                real_providers.append(GeminiProvider(
                    api_key=ctx.secrets.get("GEMINI_API_KEY") or ctx.secrets.get("GOOGLE_API_KEY"),
                    model=gemini_cfg.model or "gemini-3.8-flash",
                ))
            ollama_cfg = self._config.providers.get("ollama")
            if ollama_cfg is not None and ollama_cfg.model:
                # The local last resort: after every cloud provider, before the floor.
                from .providers.ollama import OllamaProvider

                real_providers.append(OllamaProvider(
                    model=ollama_cfg.model, base_url=ollama_cfg.base_url, keep_alive=ollama_cfg.keep_alive,
                    num_ctx=ollama_cfg.num_ctx, timeout_seconds=ollama_cfg.timeout_seconds,
                    vision_model=ollama_cfg.vision_model,
                ))
                if "ollama" not in self._config.provider_order:
                    order = [n for n in self._config.provider_order if n != "floor"] + ["ollama"]
                    if "floor" in self._config.provider_order:
                        order.append("floor")
                    self._config = dataclasses.replace(self._config, provider_order=tuple(order))
        self._budgets = {
            p.name: RollingWindowBudget(p.name, self._config.providers[p.name], ctx.ledger, clock=ctx.clock)
            for p in real_providers if p.name in self._config.providers
        }
        self._router = Router(
            real_providers, self._budgets, self._floor, order=self._config.provider_order, clock=ctx.clock,
            logger=ctx.logger,
            purpose_filter={name: set(cfg.only_purposes) for name, cfg in self._config.providers.items()
                            if getattr(cfg, "only_purposes", ())},
            native={p.name for p in real_providers
                    if getattr(self._config.providers.get(p.name), "tool_dialect", "markers") == "native"
                    and capabilities_of(p).supports_tools},
        )
        self._assembler = PromptAssembler(
            ctx.bus, ctx.source, request_timeout=self._config.assembly_request_timeout, logger=ctx.logger,
        )
        self._last_provider: str | None = None
        self._last_by_route: dict[str, str] = {}
        self._compactor = Compactor(
            self._config, ctx.ledger, bus=ctx.bus, source=ctx.source, clock=ctx.clock,
            summarize=self._summarize_for_compaction,
        )
        self._parser = OutputParser()

        self._sub_think = await ctx.bus.subscribe(topics.COGNITION_THINK, self._on_think)
        self._sub_compact = await ctx.bus.subscribe(topics.COGNITION_COMPACT_REQUEST, self._on_compact_request)
        self._sub_state = await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed)
        self._sub_tick = await ctx.bus.subscribe(topics.SYSTEM_TICK_SECOND, self._on_tick)
        # Cognition boots in layer 2 and broadcasts its provider there,
        # which is before layers 3-6 exist to hear it: the benchmark
        # subsystem recorded its first real run against model "unknown"
        # (watched, 2026-09-08). `system.started` fires once every layer
        # is up, so repeating the broadcast there reaches all of them.
        self._sub_started = await ctx.bus.subscribe(topics.SYSTEM_STARTED, self._on_system_started)
        # What each tool does and takes, for the prompt (stage 2 item 2) and
        # for the native dialects (item 4). Cognition boots before Execution
        # registers anything, so nothing is missed.
        self._sub_tools = await ctx.bus.subscribe(topics.TOOL_REGISTERED, self._on_tool_registered)
        self._real_providers = list(real_providers)
        for provider in real_providers:
            await self._emit_status(provider)

    async def stop(self) -> None:
        for sub in (self._sub_think, self._sub_compact, self._sub_state, self._sub_tick,
                    getattr(self, "_sub_started", None), getattr(self, "_sub_tools", None)):
            if sub is not None:
                await sub.unsubscribe()

    def _note_reply(self, *, floor: bool) -> None:
        """Start the "no real provider" clock on the FIRST floor reply;
        a real reply stops it. It was reset to now on every floor reply,
        so health() reported degraded only once 300 s had passed since
        the LAST floor -- i.e. only after the system stopped asking
        (2026-09-18 evaluation, C12)."""
        if floor:
            if self._no_real_provider_since is None:
                self._no_real_provider_since = self._ctx.clock.now()
        else:
            self._no_real_provider_since = None

    async def health(self) -> Health:
        if self._no_real_provider_since is not None:
            elapsed = self._ctx.clock.now() - self._no_real_provider_since
            if elapsed > 300:
                return Health.degraded(f"no real provider available for {elapsed:.0f}s")
        return Health.ok()

    # -- handlers ---------------------------------------------------------------------
    def _offered_specs(self, payload: dict) -> list[dict] | None:
        """The offered tools as specs for a native provider; None when the
        caller expects no tool calls. The Router hands them only to a
        provider set to `tool_dialect = "native"`."""
        if payload.get("expected") != "tool_calls":
            return None
        names = [n for n in payload.get("tools") or () if n]
        return [self._tool_specs.get(n) or {"name": n, "description": "", "input_schema": {"type": "object"}}
                for n in names] or None

    async def _on_tool_registered(self, message: Message) -> None:
        p = message.payload
        if p.get("name"):
            self._tool_specs[p["name"]] = {"name": p["name"], "description": p.get("description", ""),
                                           "input_schema": p.get("input_schema") or {"type": "object"}}

    async def _on_think(self, message: Message) -> None:
        payload = message.payload
        try:
            purpose = Purpose(payload["purpose"])
        except ValueError:
            await self._error_reply(message, "invalid_request", f"unknown purpose {payload.get('purpose')!r}")
            return

        budget_cfg = self._config.purposes.get(purpose.value)
        req_budget = payload.get("budget") or {}
        # `max_tokens` is how much the caller wants *back*. It used to set
        # the input ceiling as well, so asking for a 2000-token answer also
        # said "and you may only be given 2000 tokens of context" -- one
        # field standing for two unrelated things.
        #
        # Live-caught 2026-09-07: a research session searched the code,
        # got one real result, and died on its next step with
        # `context_too_large -- context still exceeds budget after all
        # compaction layers`. The protected blocks alone are most of 2000
        # tokens; there was never room for anything the session actually
        # went and found. That error is all over the historical ledger.
        #
        # The input ceiling belongs to the purpose (`[cognition.purposes]`,
        # e.g. research 24k, draft 40k), which is exactly what those
        # numbers were written for. A caller can still set it explicitly
        # with `max_tokens_in`.
        budget = Budget(
            max_tokens_in=req_budget.get(
                "max_tokens_in", budget_cfg.max_tokens_in if budget_cfg else 12_000,
            ),
            max_tokens_out=req_budget.get("max_tokens", budget_cfg.max_tokens_out if budget_cfg else 1_000),
            max_cost_usd=req_budget.get("max_cost_usd", budget_cfg.max_cost_usd if budget_cfg else 0.05),
            require_real=payload.get("require_real_provider", False),
            # The purpose's own time cap. It was left out, so every think ran
            # against the 180 s default and chat's 90 s never applied (found
            # writing cognition's CONTRACT.md, 2026-09-19).
            max_seconds=_within_deadline(
                req_budget.get("max_seconds", budget_cfg.max_seconds if budget_cfg else 180.0),
                message, self._ctx.clock.now() if hasattr(self._ctx.clock, "now") else self._ctx.clock()),
        )

        if self._paused:
            await self._error_reply(message, "paused", "cognition is paused", retryable=True)
            return

        try:
            assembled = await self._assembler.assemble(
                purpose=purpose.value, messages=payload["messages"],
                task_rules=payload.get("task_rules", ""),
                last_step=payload.get("last_step", False),
                steps_left=payload.get("steps_left"), trace_id=message.trace_id,
            )
            protected = [b for b in assembled.blocks if b.protected]
            protected_tokens = sum(b.tokens for b in protected)
            if protected_tokens > budget.max_tokens_in:
                await self._error_reply(message, "context_too_large", "protected blocks alone exceed the budget")
                return

            # The compactor sees the caller's *raw* messages (role, name,
            # load_bearing intact) -- not the assembler's already-flattened
            # "conversation" block -- so layer 1 can still find individual
            # tool results and layers 3-4 have real per-segment structure
            # to work with, per 04 section 5's compaction pipeline.
            elastic_limit = budget.max_tokens_in - protected_tokens
            compacted = await self._compactor.compact(
                payload["messages"], limit_tokens=elastic_limit,
                allow_summarize=payload.get("allow_summarize", False),
                session_id=payload.get("session_id"), purpose=purpose.value,
            )
            if compacted.tokens_after > elastic_limit:
                # Layers 1-5 ran and it's still over budget -- a single
                # oversized protected block is the spec's own example, but
                # the check itself is general: protected means protected
                # (principle 4.6), so we fail loudly rather than truncate.
                raise ContextTooLarge("context still exceeds budget after all compaction layers")

            # Protected blocks (self-summary, persona voice) go as a real
            # `role: "system"` message, not flattened into the same user
            # turn as everything else -- live-caught: a provider that
            # only ever sees one undifferentiated blob of text has no way
            # to tell "binding identity" apart from "conversation," and
            # `ClaudeCodeProvider` in particular is the literal Claude
            # Code CLI, which defaults to its own strong identity unless
            # something with real system-prompt authority overrides it
            # (see that provider's own module docstring).
            protected_text = "\n\n".join(b.text for b in protected)
            tool_instructions = _tool_instruction_block(payload, self._tool_specs)
            think_messages: list[dict] = []
            if protected_text:
                think_messages.append({"role": "system", "content": protected_text})
            if tool_instructions:
                # Not counted in `protected_tokens`'s budget check above --
                # a short fixed-shape string, not worth the extra
                # bookkeeping given the budget check already ran.
                think_messages.append({"role": "system", "content": tool_instructions})
            if compacted.text:
                think_messages.append({"role": "user", "content": compacted.text})
            if not think_messages:
                think_messages.append({"role": "user", "content": ""})  # never call complete() with zero messages

            # A per-purpose route, or the strong route when the caller escalates,
            # tried before the default order (design section 7).
            strong = payload.get("tier") == "strong"
            route = (self._config.routes.get("strong") if strong else None) or self._config.routes.get(purpose.value)
            order = tuple(dict.fromkeys(tuple(route) + tuple(self._config.provider_order))) if route else None
            if strong and route and self._ctx is not None:
                self._ctx.logger.info("cognition.escalated", purpose=purpose.value, route=list(route),
                                      reason=str(payload.get("tier_reason") or ""))
            # Pictures travel beside the words, as paths (the `images` field
            # of `cognition.think`): only a provider that can actually see is
            # dialled for these, so nothing describes a photograph it was
            # never shown.
            images = [str(p) for p in (payload.get("images") or []) if str(p).strip()]
            telemetry = getattr(self._ctx, "telemetry", None) or NULL_TELEMETRY
            async with telemetry.span("cognition.provider_call", trace_id=message.trace_id, parent_id=message.id,
                                      attrs={"purpose": purpose.value}) as span:
                response, floor = await self._router.complete(
                    purpose, think_messages, tools=self._offered_specs(payload),
                    budget=budget, timeout=budget.max_seconds, order=order, images=images or None,
                )
                span.set("provider", response.provider)
                span.set("tokens_in", response.input_tokens)
                span.set("tokens_out", response.output_tokens)
        except NoRealProvider as exc:
            await self._error_reply(message, "no_real_provider", str(exc), retryable=True)
            return
        except BudgetExceeded as exc:
            await self._error_reply(message, "budget_exceeded", str(exc), retryable=False)
            return
        except ContextTooLarge as exc:
            await self._error_reply(message, "context_too_large", str(exc))
            return
        except Paused:
            await self._error_reply(message, "paused", "system paused mid-call", retryable=True)
            return

        self._note_reply(floor=floor)
        parsed = self._parser.parse(response.text, _expected_spec(payload))
        if response.tool_calls and payload.get("expected") == "tool_calls":
            # A native provider answered with typed calls (stage 2 item 9):
            # those are the calls, whatever marker-looking text came with them.
            parsed = dataclasses.replace(parsed, kind="tool_calls", tool_calls=tuple(
                {"tool": c["tool"], "args": c.get("args") or {}, "id": c.get("id", ""),
                 **({"error": c["error"]} if c.get("error") else {})} for c in response.tool_calls))
        await self._append_call_record(purpose, response, floor, compacted)
        # Not for a call that carried pictures: only one provider can see,
        # so a camera event always "changes" the provider and then changes
        # it back on the next chat turn. The creator's screen, 2026-09-16:
        # "thinking moved from together to ollama" twice a minute while
        # thinking had not moved at all.
        if not images:
            await self._notice_if_provider_changed(response.provider, route_key=",".join(order) if order else "")

        await self._ctx.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": parsed.text,
            "tool_calls": list(parsed.tool_calls),
            "provider": response.provider,
            "cost_usd": response.cost_usd or 0.0,
            "tokens": response.input_tokens + response.output_tokens,
            "floor": floor,
            "non_answer": parsed.non_answer,
            "edit_blocks": list(parsed.edit_blocks),
            "compaction": {
                "layers_applied": [str(n) for n in compacted.layers_applied],
                "tokens_before": compacted.tokens_before, "tokens_after": compacted.tokens_after,
                "summary_ref": compacted.summary_ref,
            },
            # Per-call budget accounting (04 section 7): what this one
            # request actually spent against what it stated it could --
            # reported alongside the rolling per-provider window in
            # `cognition.provider.status`, not instead of it.
            "budget": {
                "max_cost_usd": budget.max_cost_usd, "spent_usd": response.cost_usd or 0.0,
                "max_tokens_out": budget.max_tokens_out, "tokens_out": response.output_tokens,
                "within_budget": (response.cost_usd or 0.0) <= budget.max_cost_usd,
            },
        })

    async def _summarize_for_compaction(self, text: str) -> str:
        """Layer 5's model call (04 section 5's "Auto-compact"): purpose
        `consolidate`, routed through the same `Router` as any other
        `think` call so it shares budgets/failover/floor -- if every
        provider is down, the floor's fixed template still returns
        *something*, which is safer than raising out of a compaction
        pass that a caller is relying on to make room."""
        consolidate_budget = self._config.purposes.get("consolidate") or Budget(16_000, 2_000, 0.1)
        response, _floor = await self._router.complete(
            Purpose.CONSOLIDATE, [{"role": "user", "content": text}], tools=None,
            budget=consolidate_budget, timeout=consolidate_budget.max_seconds,
        )
        return response.text

    async def _on_compact_request(self, message: Message) -> None:
        compacted = await self._compactor.compact(
            message.payload.get("messages", []), limit_tokens=message.payload["target_tokens"],
            allow_summarize=message.payload.get("allow_summarize", False),
            session_id=message.payload.get("session_id"),
        )
        await self._ctx.bus.reply(message, type=topics.COGNITION_COMPACT_REPLY, payload={
            "layers_applied": [str(n) for n in compacted.layers_applied],
            "tokens_before": compacted.tokens_before, "tokens_after": compacted.tokens_after,
            "summary_ref": compacted.summary_ref,
        })

    async def _on_state_changed(self, message: Message) -> None:
        self._paused = message.payload.get("state") in ("paused", "stopping")

    def _model_of(self, provider_name: str) -> str:
        """The model this provider is configured to call, for the status
        broadcast. Empty when the provider does not name one."""
        return self._router.model_of(provider_name) if self._router is not None else ""

    async def _on_tick(self, message: Message) -> None:
        self._tick_seconds += 1
        # 03 section 4.1: refresh every ~30s, not every second tick. The
        # period is `availability_poll_seconds` (it was a literal 30 while
        # the config key sat unread, found writing CONTRACT.md 2026-09-19).
        every = max(1, round(float(self._config.availability_poll_seconds)))
        if self._tick_seconds % every != 0:
            return
        statuses = [await b.status() for b in self._budgets.values()]
        selected = self._router.selected_name() if self._router is not None else None
        for status in statuses:
            await self._ctx.bus.publish(Message.new(
                topics.COGNITION_PROVIDER_STATUS, source=self._ctx.source, payload={
                    "provider": status.provider, "available": not status.exhausted,
                    "model": self._model_of(status.provider),
                    "selected": status.provider == selected,
                    "budget": {
                        "window_seconds": status.window_seconds, "calls": status.calls_in_window,
                        "max_calls": status.max_calls, "spend_usd": status.spend_usd,
                        "max_spend_usd": status.max_spend_usd, "exhausted": status.exhausted,
                    },
                },
            ))
        # A dashboard's "LLM usage" view (02-system-architecture.md
        # section 6.2's own creator-flagged item): the same rolling-
        # window status each `cognition.provider.status` event above
        # just carried, also folded into `system.metrics` so it reaches
        # `system.status.request`'s single aggregated snapshot the way
        # every other subsystem's own gauges already do -- no new topic,
        # `gauges` already permits a structured value (milestone 112).
        await self._ctx.bus.publish(Message.new(
            topics.SYSTEM_METRICS, source=self._ctx.source, payload={
                "subsystem": "cognition", "counters": {},
                "gauges": {"providers": [
                    {
                        "name": s.provider, "calls": s.calls_in_window, "max_calls": s.max_calls,
                        "spend_usd": round(s.spend_usd, 4), "max_spend_usd": s.max_spend_usd,
                        "exhausted": s.exhausted,
                    }
                    for s in statuses
                ]},
            },
        ))

    async def _on_system_started(self, _message) -> None:
        for provider in getattr(self, "_real_providers", ()):
            await self._emit_status(provider)

    async def _emit_status(self, provider) -> None:
        exhausted = False
        budget = self._budgets.get(provider.name)
        if budget is not None:
            status = await budget.status()
            exhausted = status.exhausted
        # The startup broadcast carries the model and the selection too.
        # It used to send only the name, so the self model had no
        # "Thinking with:" line until the first 30-second tick -- exactly
        # the window in which a human asks "what model are you?", and Sim
        # confabulated a retired v1 path (watched chat trial, 2026-09-07).
        selected = self._router.selected_name() if self._router is not None else None
        await self._ctx.bus.publish(Message.new(
            topics.COGNITION_PROVIDER_STATUS, source=self._ctx.source,
            payload={
                "provider": provider.name, "available": provider.available() and not exhausted, "budget": {},
                "model": self._model_of(provider.name), "selected": provider.name == selected,
            },
        ))

    async def _notice_if_provider_changed(self, provider: str, route_key: str = "") -> None:
        """Say on screen when thinking moves to another provider, and
        why. The failover is silent by design at the router; the person
        must not be. 2026-09-11: Together's day of calls ran out at
        20:32 in the middle of a spoken conversation, every turn after
        it went to the Claude Code CLI, and the creator's report was
        "sim became less responsive" -- five seconds a turn instead of
        one, and nothing on screen said so."""
        # Per route, not across all calls: with `escalate_from_attempt = 1`
        # a task's drafts are routed to `together_strong` while chat uses
        # `together`, and comparing consecutive calls announced "thinking
        # moved" on nearly every call (the creator's screen, 2026-09-19).
        # A move is a different provider answering the SAME route: failover.
        previous = self._last_by_route.get(route_key)
        self._last_by_route[route_key] = provider
        self._last_provider = provider
        if previous is None or previous == provider or self._ctx is None:
            return
        why = ""
        budget = self._budgets.get(previous)
        if budget is not None:
            try:
                status = await budget.status()
            except Exception:  # noqa: BLE001 -- the notice matters more than its detail
                status = None
            if status is not None and status.exhausted:
                hours = status.window_seconds / 3600
                if status.max_calls is not None and status.calls_in_window >= status.max_calls:
                    why = f"{previous} reached its cap of {status.max_calls} calls per {hours:g} h"
                elif status.max_spend_usd is not None:
                    why = f"{previous} reached its ${status.max_spend_usd:g} per {hours:g} h budget"
        text = f"thinking moved from {previous} to {provider}" + (f": {why}" if why else "")
        if provider == "claude_code_cli":
            text += " -- slower per turn, and it counts against the Claude Code quota"
        self._ctx.logger.warning("cognition.provider_changed", previous=previous, provider=provider, why=why)
        await self._ctx.bus.publish(Message.new(topics.UI_NOTICE, source=self._ctx.source, payload={
            "level": "warning", "text": text, "source": "cognition"}))

    async def _append_call_record(self, purpose: Purpose, response: ProviderResponse, floor: bool, compacted) -> None:
        await self._ctx.ledger.append("cognition:calls", Event(
            stream="cognition:calls", type="think.completed", ts=self._ctx.clock.now(),
            trace_id="", causation_id=None,
            payload={
                "purpose": purpose.value, "provider": response.provider,
                "tokens": response.input_tokens + response.output_tokens,
                "cost_usd": response.cost_usd or 0.0, "floor": floor,
                "compaction": [str(n) for n in compacted.layers_applied],
            },
        ))

    async def _error_reply(self, message: Message, code: str, detail: str, *, retryable: bool = False) -> None:
        await self._ctx.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload=error_reply_payload(code, detail, retryable=retryable))


__all__ = ["Service", "VERSION"]
