from __future__ import annotations

import time
from dataclasses import dataclass

from src.cognition.provider import LLMProvider, LLMResponse, ProviderUnavailable
from src.memory.long_term import MemoryStore

SPEND_KIND = "llm_spend"
OUTCOME_KIND = "llm_outcome"


@dataclass(frozen=True)
class Budget:
    """A spend/call cap over a rolling time window (default: 24h)."""

    max_calls: int | None = None
    max_estimated_cost_usd: float | None = None
    window_seconds: float = 86400.0


class BudgetGuard(LLMProvider):
    """Wraps `provider`, enforcing `budget` before every call.

    Cost is estimated from `response.metadata["input_tokens"]` /
    `["output_tokens"]` (a real provider should populate these from the
    API's own usage report) times the given per-1M-token prices -- an
    estimate for guarding spend, not a substitute for the provider's own
    billing dashboard.
    """

    def __init__(
        self,
        provider: LLMProvider,
        store: MemoryStore,
        budget: Budget,
        price_per_1m_input: float = 0.0,
        price_per_1m_output: float = 0.0,
    ) -> None:
        self._provider = provider
        self._store = store
        self._budget = budget
        self._price_in = price_per_1m_input
        self._price_out = price_per_1m_output
        self.name = f"budgeted:{provider.name}"

    def available(self) -> bool:
        return self._provider.available() and not self._is_exhausted()

    def complete(self, prompt: str, **kwargs) -> LLMResponse:
        if self._is_exhausted():
            status = self.status()
            raise ProviderUnavailable(
                f"{self._provider.name} budget exhausted for this window "
                f"(calls={status['calls_in_window']}, "
                f"spend=${status['spend_in_window_usd']:.4f})"
            )
        response = self._provider.complete(prompt, **kwargs)
        self._store.remember(
            SPEND_KIND,
            self._provider.name,
            cost_usd=self._estimate_cost(response),
            input_tokens=response.metadata.get("input_tokens", 0),
            output_tokens=response.metadata.get("output_tokens", 0),
        )
        return response

    def record_outcome(self, success: bool, latency_seconds: float | None = None) -> None:
        """Record whether a dispatched task using this provider succeeded.

        Callers (e.g. the orchestrator's reflection loop) call this after
        the fact, once a task's real outcome is known -- `complete()`
        itself only knows the response was returned, not whether the
        caller's task actually succeeded.
        """
        self._store.remember(
            OUTCOME_KIND,
            self._provider.name,
            success=success,
            latency_seconds=latency_seconds,
        )

    def success_rate(self) -> float | None:
        """Fraction of recorded outcomes (this window) that succeeded, or
        None if no outcomes have been recorded yet -- distinct from 0.0,
        which would wrongly signal a proven-bad provider.
        """
        outcomes = self._recent_outcomes()
        if not outcomes:
            return None
        successes = sum(1 for o in outcomes if o.metadata.get("success"))
        return successes / len(outcomes)

    def status(self) -> dict:
        records = self._recent_records()
        spend = sum(r.metadata.get("cost_usd", 0.0) for r in records)
        outcomes = self._recent_outcomes()
        successes = sum(1 for o in outcomes if o.metadata.get("success"))
        latencies = [
            o.metadata["latency_seconds"]
            for o in outcomes
            if o.metadata.get("latency_seconds") is not None
        ]
        return {
            "calls_in_window": len(records),
            "spend_in_window_usd": round(spend, 6),
            "max_calls": self._budget.max_calls,
            "max_estimated_cost_usd": self._budget.max_estimated_cost_usd,
            "success_rate": (successes / len(outcomes)) if outcomes else None,
            "average_latency_seconds": (
                sum(latencies) / len(latencies) if latencies else None
            ),
        }

    def _recent_records(self) -> list:
        """Records for THIS wrapped provider only. A real, live bug lived
        here: this used to return every kind=SPEND_KIND record
        regardless of which provider made it, so when Claude Code CLI
        and Gemini were both registered (main.py's build_cognition_router
        always wraps each in its own BudgetGuard, sharing one
        MemoryStore), each guard's exhaustion check was actually counting
        the OTHER provider's calls too -- caught live: Claude Code CLI's
        guard reported itself exhausted at "110/30 calls" purely from
        Gemini's own heavy usage, silencing the flat-rate-subscription
        provider main.py deliberately prefers, entirely because of an
        unrelated provider's pay-per-token volume.
        """
        cutoff = time.time() - self._budget.window_seconds
        return [
            r
            for r in self._store.query(kind=SPEND_KIND)
            if r.created_at >= cutoff and r.content == self._provider.name
        ]

    def _recent_outcomes(self) -> list:
        """Outcome records for THIS wrapped provider only, same
        per-provider isolation as `_recent_records` and for the same
        reason: a shared MemoryStore must not let one provider's history
        bleed into another's.
        """
        cutoff = time.time() - self._budget.window_seconds
        return [
            r
            for r in self._store.query(kind=OUTCOME_KIND)
            if r.created_at >= cutoff and r.content == self._provider.name
        ]

    def _is_exhausted(self) -> bool:
        records = self._recent_records()
        if self._budget.max_calls is not None and len(records) >= self._budget.max_calls:
            return True
        if self._budget.max_estimated_cost_usd is not None:
            spend = sum(r.metadata.get("cost_usd", 0.0) for r in records)
            if spend >= self._budget.max_estimated_cost_usd:
                return True
        return False

    def _estimate_cost(self, response: LLMResponse) -> float:
        """Prefer a provider-reported cost (e.g. Claude Code CLI's own
        `total_cost_usd` -- a real, provider-computed figure, not an
        estimate) when present; otherwise fall back to token counts times
        the configured per-1M prices.
        """
        if "cost_usd" in response.metadata:
            return float(response.metadata["cost_usd"] or 0.0)
        input_tokens = response.metadata.get("input_tokens", 0)
        output_tokens = response.metadata.get("output_tokens", 0)
        return (
            (input_tokens / 1_000_000) * self._price_in
            + (output_tokens / 1_000_000) * self._price_out
        )


def preferred_provider(guards: list[BudgetGuard]) -> BudgetGuard | None:
    """Given several BudgetGuards wrapping different providers, pick the
    available one with the best track record of task success, breaking
    ties toward lower in-window spend.

    Falls back to the first available guard when none yet has outcome
    history recorded (via `record_outcome`), since there is no success
    signal yet to adapt toward -- cost alone shouldn't decide once real
    success data exists, but it's a reasonable default before it does.
    """
    available = [g for g in guards if g.available()]
    if not available:
        return None
    scored = [g for g in available if g.success_rate() is not None]
    if not scored:
        return available[0]
    return max(
        scored,
        key=lambda g: (g.success_rate(), -g.status()["spend_in_window_usd"]),
    )