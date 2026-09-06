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

DEFAULT_THINK_TIMEOUT_SECONDS = 8.0


class BusCognitionCaller:
    def __init__(self, bus: Bus, clock: Clock, *, source: str, timeout: float = DEFAULT_THINK_TIMEOUT_SECONDS) -> None:
        self._bus = bus
        self._clock = clock
        self._source = source
        self._timeout = timeout

    async def think(self, *, purpose: str, prompt: str, require_real_provider: bool = False) -> str | None:
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
            return None
        payload = reply.payload
        if payload.get("ok") is False:
            return None
        if payload.get("floor") or payload.get("non_answer"):
            return None
        text = payload.get("text") or ""
        return text or None


__all__ = ["DEFAULT_THINK_TIMEOUT_SECONDS", "BusCognitionCaller"]
