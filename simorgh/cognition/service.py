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
        topics.COGNITION_PROVIDER_STATUS, topics.SYSTEM_HEALTH,
    )

    def __init__(self, *, config: Config | None = None, providers: list | None = None) -> None:
        self._config = config or Config()
        self._injected_providers = providers
        self._paused = False
        self._no_real_provider_since: float | None = None
        self._tick_seconds = 0

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._floor = FloorProvider()
        if self._injected_providers is not None:
            # test seam: a fake Provider list, so an integration test can
            # boot a real Kernel + real Service without shelling out to an
            # actual CLI or API (04 section 9's own acceptance bar wants a
            # real Service, not a mock of this class).
            real_providers = list(self._injected_providers)
        else:
            real_providers = [ClaudeCodeProvider(timeout_seconds=self._config.providers["claude_code_cli"].timeout_seconds)]
            gemini_cfg = self._config.providers.get("gemini")
            if gemini_cfg is not None:
                real_providers.append(GeminiProvider(model=gemini_cfg.model or "gemini-3.8-flash"))
        self._budgets = {
            p.name: RollingWindowBudget(p.name, self._config.providers[p.name], ctx.ledger, clock=ctx.clock)
            for p in real_providers if p.name in self._config.providers
        }
        self._router = Router(
            real_providers, self._budgets, self._floor, order=self._config.provider_order, clock=ctx.clock,
        )
        self._assembler = PromptAssembler(
            ctx.bus, ctx.source, request_timeout=self._config.assembly_request_timeout, logger=ctx.logger,
        )
        self._compactor = Compactor(
            self._config, ctx.ledger, bus=ctx.bus, source=ctx.source, clock=ctx.clock,
            summarize=self._summarize_for_compaction,
        )
        self._parser = OutputParser()

        self._sub_think = await ctx.bus.subscribe(topics.COGNITION_THINK, self._on_think)
        self._sub_compact = await ctx.bus.subscribe(topics.COGNITION_COMPACT_REQUEST, self._on_compact_request)
        self._sub_state = await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed)
        self._sub_tick = await ctx.bus.subscribe(topics.SYSTEM_TICK_SECOND, self._on_tick)
        for provider in real_providers:
            await self._emit_status(provider)

    async def stop(self) -> None:
        for sub in (self._sub_think, self._sub_compact, self._sub_state, self._sub_tick):
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
        budget = Budget(
            max_tokens_in=req_budget.get("max_tokens", budget_cfg.max_tokens_in if budget_cfg else 12_000),
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
                last_step=payload.get("last_step", False),
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

            protected_text = "\n\n".join(b.text for b in protected)
            full_text = f"{protected_text}\n\n{compacted.text}".strip()

            response, floor = await self._router.complete(
                purpose, [{"role": "user", "content": full_text}], tools=None,
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

    async def _on_tick(self, message: Message) -> None:
        self._tick_seconds += 1
        if self._tick_seconds % 30 != 0:  # 03 section 4.1: refresh every ~30s, not every second tick
            return
        for status in [await b.status() for b in self._budgets.values()]:
            await self._ctx.bus.publish(Message.new(
                topics.COGNITION_PROVIDER_STATUS, source=self._ctx.source, payload={
                    "provider": status.provider, "available": not status.exhausted,
                    "budget": {
                        "window_seconds": status.window_seconds, "calls": status.calls_in_window,
                        "max_calls": status.max_calls, "spend_usd": status.spend_usd,
                        "max_spend_usd": status.max_spend_usd, "exhausted": status.exhausted,
                    },
                },
            ))

    async def _emit_status(self, provider) -> None:
        exhausted = False
        budget = self._budgets.get(provider.name)
        if budget is not None:
            status = await budget.status()
            exhausted = status.exhausted
        await self._ctx.bus.publish(Message.new(
            topics.COGNITION_PROVIDER_STATUS, source=self._ctx.source,
            payload={"provider": provider.name, "available": provider.available() and not exhausted, "budget": {}},
        ))

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
