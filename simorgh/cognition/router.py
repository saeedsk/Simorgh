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

import asyncio

from simorgh.contracts.protocols import Clock, Logger, Provider, ProviderResponse

from .api import Budget, BudgetExceeded, NoRealProvider, Purpose
from .budget import RollingWindowBudget
from .providers.base import FloorProvider
from .tokens import estimate_tokens


#: Below this there is no point starting another provider.
_MIN_CANDIDATE_SECONDS = 5.0

#: How long past its own stated timeout a provider is allowed to run before
#: the Router stops waiting for it. A provider that honours its timeout
#: raises its own (much more informative) error well inside this; one that
#: ignores it is cut off rather than being allowed to eat the deadline.
_OVERRUN_GRACE_SECONDS = 1.0


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
        ran_out_of_time = False
        prompt_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
        now = self._clock.now()
        # `timeout` bounds this CALL, not each candidate in turn. It used
        # to be handed to every provider unchanged, so a chain of three
        # could legitimately run for three times the number the caller
        # was told -- and the caller, waiting for one, always gave up
        # first. An observer watched a task die as "blocked -- no real
        # provider" 121 seconds in, with Orchestration waiting 120s and
        # each candidate allowed 180s: the failover chain existed and
        # could never be reached, because nobody was still listening by
        # the time the second candidate was dialled (2026-09-10).
        deadline = now + timeout
        for name in self._order:
            provider = self._by_name.get(name)
            if provider is None or not provider.available():
                continue
            if self._cooldown_until.get(name, 0.0) > self._clock.now():
                continue
            provider_budget = self._budgets.get(name)
            if provider_budget is not None:
                est_cost = provider_budget.estimate_cost(prompt_tokens, budget.max_tokens_out)
                if est_cost > budget.max_cost_usd:
                    any_available_but_over_budget = True
                    continue
                # `can_spend` has taken an estimate since it was written and
                # nobody ever passed one -- the classic one-sided wire. So
                # the rolling window only ever refused a call *after* it had
                # already gone over: with $0.01 of a $2.00 daily cap left, a
                # call estimated at $7 was waved straight through, and the
                # cap was discovered blown on the next call. Observed
                # 2026-09-10 with a real `RollingWindowBudget`: spend went
                # from $1.99 to $9.49 against a $2.00 cap in one call.
                if not await provider_budget.can_spend(est_cost):
                    continue
            remaining = deadline - self._clock.now()
            if remaining < _MIN_CANDIDATE_SECONDS:
                # Not enough time left to be worth dialling: starting a
                # call we know cannot finish spends money and returns
                # nothing.
                ran_out_of_time = True
                if self._logger is not None:
                    self._logger.warning(
                        "cognition.no_time_for_candidate", provider=name, purpose=purpose.value,
                        remaining_s=round(max(0.0, remaining), 1),
                    )
                continue
            # Bounding the whole chain is only half of it: the first
            # candidate used to be handed the ENTIRE remaining deadline, so
            # a primary that was merely slow (not failing) ate all of it and
            # every candidate behind it was skipped with
            # `no_time_for_candidate`. Watched 2026-09-10 with a 6s call
            # budget: `together` was given 6.00s, burned it, and a perfectly
            # healthy `gemini` behind it was never dialled once -- the same
            # "the failover chain exists and can never be reached" failure
            # the deadline was introduced to fix, one level down. The
            # deadline is now *shared*: each candidate gets its fair slice
            # of what is left, so the last one still gets a real shot, and a
            # candidate that fails fast hands its unused time to the next.
            share = self._share_of(name, remaining)
            try:
                # A provider is asked to honour `timeout`, and then held to
                # it: `GeminiProvider` accepted the argument and dropped it
                # entirely (fixed in the same pass), and any provider can
                # simply overrun. Without this, one provider ignoring its
                # timeout puts the whole-call deadline back at its mercy.
                # A `to_thread` provider's thread is not killed by the
                # cancellation -- it is abandoned, which is why providers
                # are still passed a timeout of their own.
                response = await asyncio.wait_for(
                    provider.complete(
                        messages, tools=tools, max_tokens=budget.max_tokens_out, timeout=share,
                    ),
                    timeout=share + _OVERRUN_GRACE_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001 -- ProviderUnavailable or anything else: try the next candidate
                last_error = exc
                # `now` is when this whole call STARTED, which can be a
                # provider timeout ago. Stamping `now + cooldown_s` meant a
                # provider that took longer than the cooldown to fail was
                # put into a cooldown that had ALREADY EXPIRED when it was
                # written -- so the circuit breaker was a no-op for exactly
                # the failure it exists for: the provider that hangs and
                # burns a full timeout, not the one that refuses in 200ms.
                # Caught through a real Kernel boot, 2026-09-10: a cooldown
                # stamped 64,836 seconds in the past, and the "cooling
                # down" provider re-dialled on the very next call.
                self._cooldown_until[name] = self._clock.now() + self._cooldown_s
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
            if last_error is not None:
                raise NoRealProvider(str(last_error))
            if ran_out_of_time:
                # Saying "no real provider available" here was simply
                # untrue: providers were available and willing, the call's
                # own deadline had already gone. The distinction is what
                # tells an operator to raise the timeout rather than go
                # hunting for a dead API key.
                raise NoRealProvider(
                    f"the {timeout:.0f}s call deadline was exhausted before any provider could be dialled",
                )
            raise NoRealProvider("no real provider available")
        return self._floor.respond_for_purpose(purpose), True

    def _share_of(self, name: str, remaining: float) -> float:
        """This candidate's fair slice of the time that is left, so a slow
        primary cannot starve every candidate behind it. Never less than
        `_MIN_CANDIDATE_SECONDS` (a slice too small to answer in is not a
        chance, it is a wasted call) and never more than what is left."""
        now = self._clock.now()
        still_to_try = 0
        seen_self = False
        for other in self._order:
            if other == name:
                seen_self = True
                continue
            if not seen_self:
                continue
            provider = self._by_name.get(other)
            # Budget checks need an await and are deliberately not consulted
            # here: this only has to be a good-faith count of who is behind
            # this candidate, and over-counting merely makes each slice a
            # little smaller than it had to be.
            if provider is not None and provider.available() and self._cooldown_until.get(other, 0.0) <= now:
                still_to_try += 1
        if still_to_try == 0:
            return remaining
        return min(remaining, max(_MIN_CANDIDATE_SECONDS, remaining / (still_to_try + 1)))


__all__ = ["Router"]
