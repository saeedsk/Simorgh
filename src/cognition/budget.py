"""Budget guard for LLM providers: caps spend/call volume before it happens.

Wraps a real LLMProvider and refuses to call it once `budget` is exhausted
for the current rolling time window -- tracked durably via a MemoryStore,
so the cap survives process restarts, not just the current session. When
exhausted, `complete()` raises ProviderUnavailable, which CognitionRouter
already knows how to handle: fall through to the next provider, ultimately
DeterministicFallbackProvider. An expensive provider degrades exactly like
an unreachable one -- gracefully, to the guaranteed-available floor --
rather than silently spending past a limit nobody approved.

See docs/BIOMIMICRY.md, "Metabolic conservation under starvation": an
organism under caloric restriction doesn't keep spending at full rate
until it collapses, it rations. This is that rationing, for API spend.

Any real provider (Claude, Gemini, etc.) should be wrapped in a
BudgetGuard *before* being registered in a CognitionRouter -- that's the
required pattern, not an optional extra.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.cognition.provider import LLMProvider, LLMResponse, ProviderUnavailable
from src.memory.long_term import MemoryStore

SPEND_KIND = "llm_spend"


@dataclass(frozen=True)
class Budget:
    """A spend/call cap over a rolling time window (default: 24h).

    `high_priority_reserve_fraction` reserves that fraction of `max_calls`
    / `max_estimated_cost_usd` for calls made with `priority="high"` --
    the router sets that when a task is flagged high-risk or
    high-ambiguity, so those calls keep headroom even once ordinary
    traffic would otherwise have exhausted the window. The default, 0.0,
    reserves nothing: every priority sees the same limit, exactly as
    before this field existed.
    """

    max_calls: int | None = None
    max_estimated_cost_usd: float | None = None
    window_seconds: float = 86400.0
    high_priority_reserve_fraction: float = 0.0


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
        priority = kwargs.pop("priority", "normal")
        if self._is_exhausted(priority):
            status = self.status()
            raise ProviderUnavailable(
                f"{self._provider.name} budget exhausted for this window "
                f"(calls={status['calls_in_window']}, "
                f"spend=${status['spend_in_window_usd']:.4f}, "
                f"priority={priority})"
            )
        response = self._provider.complete(prompt, **kwargs)
        self._store.remember(
            SPEND_KIND,
            self._provider.name,
            cost_usd=self._estimate_cost(response),
            input_tokens=response.metadata.get("input_tokens", 0),
            output_tokens=response.metadata.get("output_tokens", 0),
            priority=priority,
        )
        return response

    def status(self) -> dict:
        records = self._recent_records()
        spend = sum(r.metadata.get("cost_usd", 0.0) for r in records)
        return {
            "calls_in_window": len(records),
            "spend_in_window_usd": round(spend, 6),
            "max_calls": self._budget.max_calls,
            "max_estimated_cost_usd": self._budget.max_estimated_cost_usd,
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

    def _is_exhausted(self, priority: str = "normal") -> bool:
        records = self._recent_records()
        max_calls = self._effective_limit(self._budget.max_calls, priority)
        if max_calls is not None and len(records) >= max_calls:
            return True
        max_cost = self._effective_limit(self._budget.max_estimated_cost_usd, priority)
        if max_cost is not None:
            spend = sum(r.metadata.get("cost_usd", 0.0) for r in records)
            if spend >= max_cost:
                return True
        return False

    def _effective_limit(self, limit, priority: str):
        """Shrink `limit` for non-high-priority calls, reserving the
        difference for `priority="high"` traffic. With the default
        `high_priority_reserve_fraction` of 0.0, this returns `limit`
        completely untouched for every priority.
        """
        if limit is None or priority == "high" or self._budget.high_priority_reserve_fraction <= 0:
            return limit
        return limit * (1 - self._budget.high_priority_reserve_fraction)

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