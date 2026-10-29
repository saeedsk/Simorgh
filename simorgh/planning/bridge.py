"""`CognitionThink` over the bus, with a bounded timeout and an honest
"nothing answered" result -- the graceful-degradation rule every Phase 1
track was built to (spec section 8: "Provider down / budget exhausted:
decomposition returns no steps", "a non-answer is not evidence of drift").
Cognition may not exist yet (this session, or ever, for a given
deployment); Planning must never hang or crash because of that.
"""

from __future__ import annotations

import asyncio

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Bus, Clock

# Was 8.0. A decomposition is a real model call and measured at exactly
# 8.0s -> None -> zero steps on every single watched run (2026-09-07), so
# no plan revision ever produced a step. Orchestration learned this lesson
# (`orchestration/config.py::think_timeout_s` = 120s); Planning never got
# the fix.
DEFAULT_THINK_TIMEOUT_SECONDS = 120.0


class BusCognitionCaller:
    def __init__(self, bus: Bus, clock: Clock, *, source: str, timeout: float = DEFAULT_THINK_TIMEOUT_SECONDS,
                 telemetry=None) -> None:
        self._bus = bus
        self._clock = clock
        self._source = source
        self._timeout = timeout
        # Optional `ctx.telemetry`: when handed one, every degradation of
        # `think()` to None is recorded as an event and a counter, with the
        # reason. Without it the "no steps ever produced" failure mode is
        # completely silent -- it hid for weeks (2026-09-07) because a
        # timeout looked identical to a plan that legitimately had no steps.
        self._telemetry = telemetry

    def _degraded(self, reason: str, request: Message) -> None:
        """Record one degradation. Telemetry must never break think()."""
        if self._telemetry is None:
            return
        try:
            counters = getattr(self._telemetry, "counters", None)
            if isinstance(counters, dict):
                counters["think_degraded"] = counters.get("think_degraded", 0) + 1
            self._telemetry.event(
                "planning.think_degraded",
                trace_id=getattr(request, "trace_id", ""),
                span_id=getattr(request, "id", ""),
                attrs={"reason": reason, "purpose": self._last_purpose},
            )
        except Exception:  # noqa: BLE001 -- telemetry never takes planning down
            pass

    async def think(self, *, purpose: str, prompt: str, require_real_provider: bool = False) -> str | None:
        self._last_purpose = purpose
        request = Message.new(
            topics.COGNITION_THINK, source=self._source,
            payload={
                "purpose": purpose, "messages": [{"role": "user", "content": prompt}],
                "budget": {"max_tokens": 2000, "max_cost_usd": 0.5},
                "require_real_provider": require_real_provider,
            },
        )
        try:
            reply = await self._bus.request(request, timeout=self._timeout)
        except asyncio.TimeoutError:
            self._degraded("timeout", request)
            return None
        payload = reply.payload
        if payload.get("ok") is False:
            self._degraded("ok_false", request)
            return None
        if payload.get("floor") or payload.get("non_answer"):
            self._degraded("floor_or_non_answer", request)
            return None
        text = payload.get("text") or ""
        if not text:
            self._degraded("empty_text", request)
            return None
        return text


__all__ = ["DEFAULT_THINK_TIMEOUT_SECONDS", "BusCognitionCaller"]
