"""`Service(Subsystem)` for Cognition (docs/blueprint/subsystems/04-
cognition.md section 5, 9): wires `cognition.think`/`.compact.request`,
provider-status ticks, and pause/stop into the pieces built in this
package. `start()` discovers providers, builds one `RollingWindowBudget`
per provider replayed from the Ledger, and subscribes; `stop()` cancels
the availability loop."""

from __future__ import annotations

import asyncio

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.protocols import Context, Health, ProviderResponse
from simorgh.contracts.registry import error_reply_payload

from .api import Budget, BudgetExceeded, ContextTooLarge, NoRealProvider, Paused, Purpose
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
def _tool_instruction_block(payload: dict) -> str | None:
    if payload.get("expected") != "tool_calls":
        return None
    tools = tuple(payload.get("tools") or ())
    if not tools:
        return None
    names = ", ".join(sorted(tool.upper() for tool in tools))
    lines = [
        "Tools available this turn: " + names + ". To use one, write its name "
        "in capitals, a colon, then your argument, as the very first line of "
        "your reply -- nothing before it. For example:\nWEB_FETCH: https://example.com\n"
        "Only do this when you genuinely need that tool right now; otherwise "
        "just answer in plain text as normal, with no marker line.",
    ]
    for tool, hint in (payload.get("tool_hints") or {}).items():
        if tool in tools and hint:
            lines.append(f"{tool.upper()}'s own argument format:\n{hint}")
    return "\n\n".join(lines)


class Service:
    name = "cognition"
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.COGNITION_THINK, topics.COGNITION_COMPACT_REQUEST,
        topics.SYSTEM_STATE_CHANGED, topics.SYSTEM_TICK_SECOND, topics.SYSTEM_STARTED,
    )
    produces: tuple[str, ...] = (
        topics.COGNITION_THINK_REPLY, topics.COGNITION_COMPACT_REPLY,
        topics.COGNITION_COMPACT_PRE, topics.COGNITION_COMPACT_DONE,
        topics.COGNITION_PROVIDER_STATUS, topics.SYSTEM_HEALTH, topics.SYSTEM_METRICS,
    )

    def __init__(self, *, config: Config | None = None, providers: list | None = None) -> None:
        self._config_from_caller = config
        self._config = config or Config()
        self._injected_providers = providers
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
                ))
            real_providers.append(
                ClaudeCodeProvider(timeout_seconds=self._config.providers["claude_code_cli"].timeout_seconds),
            )
            gemini_cfg = self._config.providers.get("gemini")
            if gemini_cfg is not None:
                real_providers.append(GeminiProvider(model=gemini_cfg.model or "gemini-3.8-flash"))
        self._budgets = {
            p.name: RollingWindowBudget(p.name, self._config.providers[p.name], ctx.ledger, clock=ctx.clock)
            for p in real_providers if p.name in self._config.providers
        }
        self._router = Router(
            real_providers, self._budgets, self._floor, order=self._config.provider_order, clock=ctx.clock,
            logger=ctx.logger,
        )
        self._assembler = PromptAssembler(
            ctx.bus, ctx.source, request_timeout=self._config.assembly_request_timeout, logger=ctx.logger,
        )
        self._last_provider: str | None = None
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
        self._real_providers = list(real_providers)
        for provider in real_providers:
            await self._emit_status(provider)

    async def stop(self) -> None:
        for sub in (self._sub_think, self._sub_compact, self._sub_state, self._sub_tick,
                    getattr(self, "_sub_started", None)):
            if sub is not None:
                await sub.unsubscribe()

    async def health(self) -> Health:
        if self._no_real_provider_since is not None:
            elapsed = self._ctx.clock.now() - self._no_real_provider_since
            if elapsed > 300:
                return Health.degraded(f"no real provider available for {elapsed:.0f}s")
        return Health.ok()

    # -- handlers ---------------------------------------------------------------------
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
        )

        if self._paused:
            await self._error_reply(message, "paused", "cognition is paused", retryable=True)
            return

        try:
            assembled = await self._assembler.assemble(
                purpose=purpose.value, messages=payload["messages"],
                task_rules=payload.get("task_rules", ""),
                last_step=payload.get("last_step", False),
                steps_left=payload.get("steps_left"),
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
            tool_instructions = _tool_instruction_block(payload)
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

            response, floor = await self._router.complete(
                purpose, think_messages, tools=None,
                budget=budget, timeout=budget.max_seconds,
            )
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

        self._no_real_provider_since = self._ctx.clock.now() if floor else None
        parsed = self._parser.parse(response.text, _expected_spec(payload))
        await self._append_call_record(purpose, response, floor, compacted)
        await self._notice_if_provider_changed(response.provider)

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
        if self._tick_seconds % 30 != 0:  # 03 section 4.1: refresh every ~30s, not every second tick
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

    async def _notice_if_provider_changed(self, provider: str) -> None:
        """Say on screen when thinking moves to another provider, and
        why. The failover is silent by design at the router; the person
        must not be. 2026-09-11: Together's day of calls ran out at
        20:32 in the middle of a spoken conversation, every turn after
        it went to the Claude Code CLI, and the creator's report was
        "sim became less responsive" -- five seconds a turn instead of
        one, and nothing on screen said so."""
        previous, self._last_provider = self._last_provider, provider
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
