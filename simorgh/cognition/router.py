"""Provider failover and selection (docs/blueprint/subsystems/04-
cognition.md section 5). Ported from v1 `CognitionRouter`'s failover
shape: try each candidate in configured order, catch `ProviderUnavailable`
and move on, fall through to the floor unless `require_real_provider`.

Scoped this build session to ordered failover only -- `CapabilityRegistry`
(best_with_context_window/cheapest_for/leaderboard) and ensemble
reconciliation are Phase 4 (see the spec's own step 5 and this package's
README); `select()` already returns an ordered candidate list so that
work is additive, not a redesign.
"""

from __future__ import annotations

from simorgh.contracts.protocols import Clock, Provider, ProviderResponse

from .api import Budget, BudgetExceeded, NoRealProvider, Purpose
from .budget import RollingWindowBudget
from .providers.base import FloorProvider
from .tokens import estimate_tokens


class Router:
    def __init__(
        self, providers: list[Provider], budgets: dict[str, RollingWindowBudget],
        floor: FloorProvider, *, order: tuple[str, ...], clock: Clock,
    ) -> None:
        self._by_name = {p.name: p for p in providers}
        self._budgets = budgets
        self._floor = floor
        self._order = order
        self._clock = clock

    def candidate_names(self) -> list[str]:
        return [name for name in self._order if name in self._by_name] + [self._floor.name]

    async def complete(
        self, purpose: Purpose, messages: list[dict], *, tools: list[dict] | None,
        budget: Budget, timeout: float,
    ) -> tuple[ProviderResponse, bool]:
        """Returns (response, floor). Raises `NoRealProvider` if every
        real candidate failed/was exhausted and `budget.require_real`;
        raises `BudgetExceeded` instead when every candidate was actually
        *available* but skipped purely because its estimated cost for
        this one request would exceed `budget.max_cost_usd` -- per-call
        budget accounting (04 section 7), distinct from availability."""
        last_error: Exception | None = None
        any_available_but_over_budget = False
        prompt_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        for name in self._order:
            provider = self._by_name.get(name)
            if provider is None or not provider.available():
                continue
            provider_budget = self._budgets.get(name)
            if provider_budget is not None and not await provider_budget.can_spend():
                continue
            if provider_budget is not None:
                est_cost = provider_budget.estimate_cost(prompt_tokens, budget.max_tokens_out)
                if est_cost > budget.max_cost_usd:
                    any_available_but_over_budget = True
                    continue
            try:
                response = await provider.complete(
                    messages, tools=tools, max_tokens=budget.max_tokens_out, timeout=timeout,
                )
            except Exception as exc:  # noqa: BLE001 -- ProviderUnavailable or anything else: try the next candidate
                last_error = exc
                continue
            if provider_budget is not None:
                await provider_budget.record(response)
            return response, False
        if budget.require_real:
            if last_error is None and any_available_but_over_budget:
                raise BudgetExceeded(f"every candidate's estimated cost exceeds max_cost_usd={budget.max_cost_usd}")
            raise NoRealProvider(str(last_error) if last_error else "no real provider available")
        return self._floor.respond_for_purpose(purpose), True


__all__ = ["Router"]
