"""Per-provider rolling-window spend/call accounting, durable via the
Ledger stream `cognition:budget:<provider>` (docs/blueprint/subsystems/
04-cognition.md section 4). Ported from v1 `src/cognition/budget.py`'s
`BudgetGuard`, with the one real, live-caught bug already fixed rather
than re-introduced: records are filtered by *this* provider's name, not
by kind alone -- v1 originally counted every provider's calls against
every guard, so Claude Code CLI's own budget reported itself exhausted
purely from Gemini's unrelated volume.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Clock, Ledger, ProviderResponse

from .api import BudgetStatus
from .config import ProviderConfig

SPEND_KIND = "spend.recorded"


def stream_for(provider: str) -> str:
    return f"cognition:budget:{provider}"


class RollingWindowBudget:
    """One provider's durable budget. `record()`/`status()` replay the
    stream's events within the window rather than keeping only an
    in-memory counter, so accounting survives a restart -- the Ledger is
    the truth (principle 4.4)."""

    def __init__(self, provider: str, config: ProviderConfig, ledger: Ledger, *, clock: Clock) -> None:
        self._provider = provider
        self._config = config
        self._ledger = ledger
        self._clock = clock

    async def can_spend(self, est_cost_usd: float = 0.0) -> bool:
        status = await self.status()
        if status.exhausted:
            return False
        if self._config.max_spend_usd is not None and status.spend_usd + est_cost_usd > self._config.max_spend_usd:
            return False
        return True

    async def record(self, response: ProviderResponse) -> None:
        cost = self._estimate_cost(response)
        await self._ledger.append(
            stream_for(self._provider),
            Event(
                stream=stream_for(self._provider), type=SPEND_KIND, ts=self._clock.now(),
                trace_id="", causation_id=None,
                payload={"cost_usd": cost, "input_tokens": response.input_tokens, "output_tokens": response.output_tokens},
            ),
        )

    async def status(self) -> BudgetStatus:
        cutoff = self._clock.now() - self._config.window_seconds
        events = await self._ledger.read(stream_for(self._provider))
        recent = [e for e in events if e.ts >= cutoff]
        spend = sum(e.payload.get("cost_usd", 0.0) for e in recent)
        calls = len(recent)
        exhausted = (self._config.max_calls is not None and calls >= self._config.max_calls) or (
            self._config.max_spend_usd is not None and spend >= self._config.max_spend_usd
        )
        return BudgetStatus(
            provider=self._provider, calls_in_window=calls, max_calls=self._config.max_calls,
            spend_usd=round(spend, 6), max_spend_usd=self._config.max_spend_usd,
            window_seconds=self._config.window_seconds, exhausted=exhausted,
        )

    def _estimate_cost(self, response: ProviderResponse) -> float:
        """Prefer a provider-reported cost (Claude Code CLI's own
        `total_cost_usd`) when present; otherwise token counts times the
        configured per-1M prices."""
        if response.cost_usd is not None:
            return float(response.cost_usd)
        return (
            (response.input_tokens / 1_000_000) * self._config.price_in
            + (response.output_tokens / 1_000_000) * self._config.price_out
        )


__all__ = ["RollingWindowBudget", "SPEND_KIND", "stream_for"]
