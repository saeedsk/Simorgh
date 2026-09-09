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

from simorgh.contracts.protocols import Clock, Logger, Provider, ProviderResponse

from .api import Budget, BudgetExceeded, NoRealProvider, Purpose
from .budget import RollingWindowBudget
from .providers.base import FloorProvider
from .tokens import estimate_tokens


class Router:
    def __init__(
        self, providers: list[Provider], budgets: dict[str, RollingWindowBudget],
        floor: FloorProvider, *, order: tuple[str, ...], clock: Clock, logger: Logger | None = None,
        cooldown_s: float = 30.0,
    ) -> None:
        self._by_name = {p.name: p for p in providers}
        self._budgets = budgets
        self._floor = floor
        self._order = order
        self._clock = clock
        self._logger = logger
        # No circuit breaker existed at all before this: a provider that
        # is genuinely down for the whole run (an exhausted API key, a
        # revoked credential, a real outage) got retried on EVERY single
        # `complete()` call for the rest of the process's life, paying a
        # full network round trip -- and its own timeout, if it hangs
        # rather than fails fast -- before falling through to the next
        # candidate. Live-caught, 2026-09-09: Together's credits ran out
        # mid-session and a single multi-step task logged 30+ consecutive
        # `cognition.provider_failed` entries for the identical 402,
        # visibly slowing the whole task while it re-learned the same
        # fact on every step. `_cooldown_until` remembers a failure for
        # `cooldown_s` and skips straight to the next candidate during
        # that window -- short enough that a real transient blip (a
        # dropped connection, a momentary rate limit) still recovers on
        # its own within one task, long enough that a truly-dead
        # provider is not re-dialed every single step.
        self._cooldown_s = cooldown_s
        self._cooldown_until: dict[str, float] = {}

    def candidate_names(self) -> list[str]:
        return [name for name in self._order if name in self._by_name] + [self._floor.name]

    def selected_name(self) -> str:
        """The provider a call would go to right now: first in the
        configured order that is actually available. Budget exhaustion is
        not consulted -- that needs an await, and this exists to answer
        "what is thinking for me", which should not require I/O."""
        now = self._clock.now()
        for name in self._order:
            provider = self._by_name.get(name)
            if provider is not None and provider.available() and self._cooldown_until.get(name, 0.0) <= now:
                return name
        return self._floor.name

    def model_of(self, name: str) -> str:
        provider = self._by_name.get(name)
        if provider is None:
            return self._floor.model if name == self._floor.name else ""
        return getattr(provider, "model", "") or ""

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
        now = self._clock.now()
        for name in self._order:
            provider = self._by_name.get(name)
            if provider is None or not provider.available():
                continue
            if self._cooldown_until.get(name, 0.0) > now:
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
                self._cooldown_until[name] = now + self._cooldown_s
                # Live-caught, 2026-09-08: a failover used to be
                # completely silent -- nothing on the Ledger, nothing in
                # any log, not even a debug line -- so the only trace of
                # a real primary-provider failure was an absence (the
                # successful candidate's name in `cognition:calls`,
                # never saying who was tried first and why they were
                # skipped). Visible even when this is the last candidate
                # and the exception is about to surface as `last_error`.
                if self._logger is not None:
                    self._logger.warning(
                        "cognition.provider_failed", provider=name, purpose=purpose.value, error=str(exc),
                    )
                # Some failures reach here *after* the remote call already
                # happened and was billed (Together's reasoning-only
                # truncation, Claude Code CLI's `is_error` exit both
                # attach `billable` for exactly this) -- record that real
                # spend against this provider's own budget before moving
                # on, so a failed-but-billed call is never silently free.
                billable = getattr(exc, "billable", None)
                if billable is not None and provider_budget is not None:
                    await provider_budget.record(billable)
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
