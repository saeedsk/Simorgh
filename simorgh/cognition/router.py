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
import re

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


_TRANSIENT = re.compile(
    r"HTTP (?:429|5\d\d)\b|timed out|TimeoutError|RemoteDisconnected|Connection (?:reset|aborted|refused)"
    r"|temporarily unavailable|Service unavailable|overloaded", re.IGNORECASE)


def _is_transient(exc: BaseException) -> bool:
    """A failure worth one quick retry: the provider is up, this call was
    unlucky. An exhausted key or a bad request is not."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    return bool(_TRANSIENT.search(str(exc)))


class Router:
    def __init__(
        self, providers: list[Provider], budgets: dict[str, RollingWindowBudget],
        floor: FloorProvider, *, order: tuple[str, ...], clock: Clock, logger: Logger | None = None,
        cooldown_s: float = 30.0, transient_backoff_s: float = 2.0,
        purpose_filter: dict[str, set[str]] | None = None,
    ) -> None:
        # name -> the purposes that provider may answer (absent: all).
        self._purpose_filter = {k: set(v) for k, v in (purpose_filter or {}).items() if v}
        # One retry after this wait for a transient failure (HTTP 429/5xx, a
        # timeout, a dropped connection) before the provider is cooled down:
        # a single Together 503 skipped 14 of 26 benchmark cases (2026-09-15).
        self._transient_backoff_s = max(0.0, float(transient_backoff_s))
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
        budget: Budget, timeout: float, order: tuple[str, ...] | None = None,
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
        names = tuple(order) if order else self._order
        for name in names:
            provider = self._by_name.get(name)
            if name in self._purpose_filter and purpose.value not in self._purpose_filter[name]:
                continue
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
            share = self._share_of(name, remaining, names)
            try:
                # A provider is asked to honour `timeout`, and then held to
                # it: `GeminiProvider` accepted the argument and dropped it
                # entirely (fixed in the same pass), and any provider can
                # simply overrun. Without this, one provider ignoring its
                # timeout puts the whole-call deadline back at its mercy.
                # A `to_thread` provider's thread is not killed by the
                # cancellation -- it is abandoned, which is why providers
                # are still passed a timeout of their own.
                response = await self._dial(
                    name, provider, messages, tools, budget.max_tokens_out, share, provider_budget, purpose,
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
                if not getattr(exc, "truncated", False):
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

    async def _dial(self, name, provider, messages, tools, max_tokens, share, provider_budget, purpose):
        """One candidate's call, retried once with twice the output room
        when the reply was cut off by `max_tokens`.

        A reasoning model that spends the whole output budget thinking has
        not failed as a provider; this call was simply too tight. Falling
        through to the next candidate -- for Sim usually the floor -- turned
        one tight review into a canned "no real reviewer" for every call
        during the cooldown (benchmark wave, 2026-09-14)."""
        started = self._clock.now()
        try:
            return await asyncio.wait_for(
                provider.complete(messages, tools=tools, max_tokens=max_tokens, timeout=share),
                timeout=share + _OVERRUN_GRACE_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001 -- truncations and transient failures retry once; the caller handles the rest
            left = share - (self._clock.now() - started)
            truncated = bool(getattr(exc, "truncated", False))
            # Quick failures only: a provider that hung for most of its slice
            # before failing gets no second slice -- that is what the cooldown
            # is for (TheCooldownIsStampedWhenTheFailureHappens).
            elapsed = self._clock.now() - started
            transient = not truncated and _is_transient(exc) and elapsed <= min(10.0, share / 3)
            wait = self._transient_backoff_s if transient else 0.0
            if not (truncated or transient) or left - wait < _MIN_CANDIDATE_SECONDS:
                raise
            billable = getattr(exc, "billable", None)
            if billable is not None and provider_budget is not None:
                await provider_budget.record(billable)
            if self._logger is not None:
                if truncated:
                    self._logger.warning("cognition.truncated_retry", provider=name, purpose=purpose.value,
                                         max_tokens=max_tokens * 2)
                else:
                    self._logger.warning("cognition.transient_retry", provider=name, purpose=purpose.value,
                                         error=str(exc)[:200], wait_s=wait)
            if wait:
                await asyncio.sleep(wait)
                left -= wait
        next_tokens = max_tokens * 2 if truncated else max_tokens
        return await asyncio.wait_for(
            provider.complete(messages, tools=tools, max_tokens=next_tokens, timeout=left),
            timeout=left + _OVERRUN_GRACE_SECONDS,
        )

    def _share_of(self, name: str, remaining: float, order: tuple[str, ...] | None = None) -> float:
        """This candidate's fair slice of the time that is left, so a slow
        primary cannot starve every candidate behind it. Never less than
        `_MIN_CANDIDATE_SECONDS` (a slice too small to answer in is not a
        chance, it is a wasted call) and never more than what is left."""
        now = self._clock.now()
        still_to_try = 0
        seen_self = False
        for other in (order or self._order):
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
