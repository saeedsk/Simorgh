"""`Router` (docs/blueprint/subsystems/04-cognition.md section 5): ported
v1 `CognitionRouter` failover shape -- try each configured candidate in
order, skip an unavailable/exhausted/erroring one, fall through to the
floor unless `require_real_provider`."""

from __future__ import annotations

import asyncio
import time
import unittest

from simorgh.cognition.api import Budget, BudgetExceeded, NoRealProvider, ProviderUnavailable, Purpose
from simorgh.cognition.budget import RollingWindowBudget
from simorgh.cognition.config import ProviderConfig
from simorgh.cognition.providers.base import FloorProvider
from simorgh.ledger.factory import make_ledger
from simorgh.cognition.router import Router
from simorgh.contracts.protocols import ProviderResponse
from tests.simorgh.helpers import FakeClock


class _FakeProvider:
    def __init__(self, name: str, *, available: bool = True, error: Exception | None = None, response: ProviderResponse | None = None):
        self.name = name
        self._available = available
        self._error = error
        self._response = response or ProviderResponse(text=f"{name}-answer", provider=name)
        self.calls = 0

    def available(self) -> bool:
        return self._available

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._response


def _budget(**kw) -> Budget:
    kw.setdefault("max_cost_usd", 1.0)
    return Budget(max_tokens_in=1_000, max_tokens_out=100, **kw)


class _FakeProviderBudget:
    """A minimal stand-in for `RollingWindowBudget` -- just enough surface
    (`can_spend`, `estimate_cost`, `record`) for the Router's per-call
    budget check (04 section 7), without a real Ledger."""

    def __init__(self, *, price_in: float = 0.0, price_out: float = 0.0, spendable: bool = True):
        self._price_in = price_in
        self._price_out = price_out
        self._spendable = spendable
        self.recorded: list = []

    async def can_spend(self, est_cost_usd: float = 0.0) -> bool:
        return self._spendable

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens / 1_000_000) * self._price_in + (output_tokens / 1_000_000) * self._price_out

    async def record(self, response) -> None:
        self.recorded.append(response)


class TestRouter(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.floor = FloorProvider()

    async def test_picks_the_first_available_candidate_in_order(self):
        primary = _FakeProvider("claude_code_cli")
        secondary = _FakeProvider("gemini")
        router = Router([secondary, primary], {}, self.floor, order=("claude_code_cli", "gemini"), clock=self.clock)
        response, floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertFalse(floor)
        self.assertEqual(response.provider, "claude_code_cli")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(secondary.calls, 0)

    async def test_unavailable_candidate_is_skipped(self):
        primary = _FakeProvider("claude_code_cli", available=False)
        secondary = _FakeProvider("gemini")
        router = Router([primary, secondary], {}, self.floor, order=("claude_code_cli", "gemini"), clock=self.clock)
        response, floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(response.provider, "gemini")
        self.assertEqual(primary.calls, 0)

    async def test_a_raising_candidate_falls_through_to_the_next(self):
        primary = _FakeProvider("claude_code_cli", error=ProviderUnavailable("not logged in"))
        secondary = _FakeProvider("gemini")
        router = Router([primary, secondary], {}, self.floor, order=("claude_code_cli", "gemini"), clock=self.clock)
        response, floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(response.provider, "gemini")
        self.assertFalse(floor)

    async def test_a_failed_provider_is_not_retried_again_within_the_cooldown(self):
        """Live-caught, 2026-09-09: with no circuit breaker at all, a
        provider that is genuinely down for the whole run (an exhausted
        API key, a real outage) got retried on EVERY complete() call --
        a single multi-step task logged 30+ consecutive identical
        failures for the same dead provider, paying a full network
        round trip each time before falling through. The second call
        here, made before the cooldown elapses, must skip straight to
        the fallback without calling the broken provider again."""
        primary = _FakeProvider("claude_code_cli", error=ProviderUnavailable("credit limit exceeded"))
        secondary = _FakeProvider("gemini")
        router = Router(
            [primary, secondary], {}, self.floor, order=("claude_code_cli", "gemini"),
            clock=self.clock, cooldown_s=30.0,
        )
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(primary.calls, 1)

        self.clock.advance(5.0)  # still inside the 30s cooldown
        response, _floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(response.provider, "gemini")
        self.assertEqual(primary.calls, 1, "the cooling-down provider must not be re-dialed")

    async def test_a_provider_is_retried_again_once_its_cooldown_elapses(self):
        primary = _FakeProvider("claude_code_cli", error=ProviderUnavailable("transient blip"))
        secondary = _FakeProvider("gemini")
        router = Router(
            [primary, secondary], {}, self.floor, order=("claude_code_cli", "gemini"),
            clock=self.clock, cooldown_s=30.0,
        )
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(primary.calls, 1)

        self.clock.advance(31.0)  # past the cooldown
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(primary.calls, 2, "a provider must be given another chance once its cooldown elapses")

    async def test_every_candidate_failing_falls_to_the_floor_by_default(self):
        primary = _FakeProvider("claude_code_cli", error=ProviderUnavailable("down"))
        router = Router([primary], {}, self.floor, order=("claude_code_cli",), clock=self.clock)
        response, floor = await router.complete(Purpose.PLAN, [], tools=None, budget=_budget(require_real=False), timeout=5.0)
        self.assertTrue(floor)
        self.assertEqual(response.provider, "floor")
        self.assertIn("[floor]", response.text)

    async def test_require_real_raises_instead_of_falling_to_the_floor(self):
        primary = _FakeProvider("claude_code_cli", error=ProviderUnavailable("down"))
        router = Router([primary], {}, self.floor, order=("claude_code_cli",), clock=self.clock)
        with self.assertRaises(NoRealProvider):
            await router.complete(Purpose.ENSEMBLE, [], tools=None, budget=_budget(require_real=True), timeout=5.0)

    async def test_no_candidates_configured_at_all_still_reaches_the_floor(self):
        router = Router([], {}, self.floor, order=(), clock=self.clock)
        response, floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertTrue(floor)

    async def test_candidate_names_lists_order_then_floor(self):
        primary = _FakeProvider("claude_code_cli")
        router = Router([primary], {}, self.floor, order=("claude_code_cli", "gemini"), clock=self.clock)
        # "gemini" has no provider instance -- filtered out, unlike "claude_code_cli".
        self.assertEqual(router.candidate_names(), ["claude_code_cli", "floor"])

    async def test_a_failed_but_billed_call_still_records_its_real_spend(self):
        # Live-caught, 2026-09-08: Together's own "reasoning only, no
        # answer" truncation (and Claude Code CLI's `is_error` exit) both
        # raise `ProviderUnavailable` *after* the remote call already
        # happened and was billed. The Router used to only ever call
        # `provider_budget.record()` on the success path, so that real
        # spend vanished the moment the call was treated as a failure --
        # silently undercounting the provider's own rolling-window budget.
        billed_but_failed = ProviderResponse(
            text="", provider="together", input_tokens=44, output_tokens=2, cost_usd=0.0000076,
        )
        primary = _FakeProvider(
            "together", error=ProviderUnavailable("reasoning only", billable=billed_but_failed),
        )
        secondary = _FakeProvider("gemini")
        provider_budget = _FakeProviderBudget()
        router = Router(
            [primary, secondary], {"together": provider_budget}, self.floor,
            order=("together", "gemini"), clock=self.clock,
        )
        response, floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertFalse(floor)
        self.assertEqual(response.provider, "gemini")
        # The failed together call's real usage was recorded even though
        # the Router moved on to gemini -- exactly one record, matching
        # the billed-but-unusable response, not the successful gemini one.
        self.assertEqual(provider_budget.recorded, [billed_but_failed])

    async def test_a_failed_call_with_no_billable_usage_records_nothing(self):
        # The common case (a network error, a bad key, "not found on
        # PATH") never reached the remote API at all -- no `billable`
        # attribute, so nothing should be recorded for it.
        primary = _FakeProvider("together", error=ProviderUnavailable("no api key"))
        secondary = _FakeProvider("gemini")
        provider_budget = _FakeProviderBudget()
        router = Router(
            [primary, secondary], {"together": provider_budget}, self.floor,
            order=("together", "gemini"), clock=self.clock,
        )
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(provider_budget.recorded, [])

    async def test_a_provider_failure_is_logged_not_silent(self):
        class _RecordingLogger:
            def __init__(self):
                self.warnings: list[tuple[str, dict]] = []

            def debug(self, event, **fields):
                pass

            def info(self, event, **fields):
                pass

            def warning(self, event, **fields):
                self.warnings.append((event, fields))

            def error(self, event, **fields):
                pass

        logger = _RecordingLogger()
        primary = _FakeProvider("together", error=ProviderUnavailable("down"))
        secondary = _FakeProvider("gemini")
        router = Router(
            [primary, secondary], {}, self.floor, order=("together", "gemini"), clock=self.clock, logger=logger,
        )
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=5.0)
        self.assertEqual(len(logger.warnings), 1)
        event, fields = logger.warnings[0]
        self.assertEqual(event, "cognition.provider_failed")
        self.assertEqual(fields["provider"], "together")


class TestRouterPerCallBudget(unittest.IsolatedAsyncioTestCase):
    """Per-call budget accounting (04 section 7, "Budgets account;
    Guardian enforces"): a candidate whose *estimated* cost for this one
    request would exceed the request's own `max_cost_usd` is skipped
    before any money is spent -- distinct from the provider's own rolling
    window (`can_spend`), which only bounds spend over time."""

    def setUp(self):
        self.clock = FakeClock()
        self.floor = FloorProvider()

    async def test_a_candidate_priced_over_the_requests_own_budget_is_skipped(self):
        primary = _FakeProvider("gemini")
        pricey = _FakeProviderBudget(price_in=1_000_000.0, price_out=1_000_000.0)  # $1/token
        router = Router([primary], {"gemini": pricey}, self.floor, order=("gemini",), clock=self.clock)
        response, floor = await router.complete(
            Purpose.CHAT, [{"role": "user", "content": "hi"}], tools=None,
            budget=_budget(max_cost_usd=0.001), timeout=5.0,
        )
        self.assertTrue(floor)
        self.assertEqual(primary.calls, 0)

    async def test_require_real_with_every_candidate_over_the_per_call_budget_raises_budget_exceeded(self):
        primary = _FakeProvider("gemini")
        pricey = _FakeProviderBudget(price_in=1_000_000.0, price_out=1_000_000.0)
        router = Router([primary], {"gemini": pricey}, self.floor, order=("gemini",), clock=self.clock)
        with self.assertRaises(BudgetExceeded):
            await router.complete(
                Purpose.CHAT, [{"role": "user", "content": "hi"}], tools=None,
                budget=_budget(max_cost_usd=0.001, require_real=True), timeout=5.0,
            )

    async def test_an_unpriced_provider_is_never_blocked_by_the_pre_call_estimate(self):
        primary = _FakeProvider("claude_code_cli")
        free = _FakeProviderBudget(price_in=0.0, price_out=0.0)
        router = Router([primary], {"claude_code_cli": free}, self.floor, order=("claude_code_cli",), clock=self.clock)
        response, floor = await router.complete(
            Purpose.CHAT, [{"role": "user", "content": "hi"}], tools=None,
            budget=_budget(max_cost_usd=0.0), timeout=5.0,
        )
        self.assertFalse(floor)
        self.assertEqual(primary.calls, 1)

    async def test_an_unavailable_provider_still_raises_no_real_provider_not_budget_exceeded(self):
        # Availability failure takes precedence over a budget skip when
        # both could explain the outcome -- `last_error` set means a real
        # candidate was actually tried and failed, not merely priced out.
        primary = _FakeProvider("gemini", error=ProviderUnavailable("down"))
        free = _FakeProviderBudget(price_in=0.0, price_out=0.0)
        router = Router([primary], {"gemini": free}, self.floor, order=("gemini",), clock=self.clock)
        with self.assertRaises(NoRealProvider):
            await router.complete(
                Purpose.CHAT, [{"role": "user", "content": "hi"}], tools=None,
                budget=_budget(require_real=True), timeout=5.0,
            )


if __name__ == "__main__":
    unittest.main()


class TheTimeoutBoundsTheWholeCallTestCase(unittest.IsolatedAsyncioTestCase):
    """`timeout` is what the caller will wait for an answer, not what
    each candidate may take in turn.

    It used to be handed to every provider unchanged, so a chain of
    three could legitimately run for three times the number the caller
    was given -- and the caller, waiting once, always gave up first. An
    observer watched a task die as "blocked -- no real provider" 121
    seconds in, with Orchestration waiting 120s and each candidate
    allowed 180s: the failover chain existed and could never be reached,
    because nobody was still listening when the second candidate would
    have been dialled (2026-09-10).
    """

    def setUp(self):
        self.clock = FakeClock()
        self.floor = FloorProvider()

    async def test_a_later_candidate_only_gets_the_time_that_is_left(self):
        clock = self.clock
        seen: dict[str, float | None] = {}

        class _SlowFailure:
            name = "claude_code_cli"
            calls = 0

            def available(self):
                return True

            async def complete(self_inner, messages, *, tools, max_tokens, timeout=None):
                self_inner.calls += 1
                seen["claude_code_cli"] = timeout
                clock.advance(20.0)
                raise RuntimeError("took 20s, then failed")

        secondary = _FakeProvider("gemini")
        original = secondary.complete

        async def _record(messages, *, tools, max_tokens, timeout=None):
            seen["gemini"] = timeout
            return await original(messages, tools=tools, max_tokens=max_tokens, timeout=timeout)

        secondary.complete = _record
        router = Router([_SlowFailure(), secondary], {}, self.floor,
                        order=("claude_code_cli", "gemini"), clock=clock)
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=60.0)

        # This used to assert 60.0 -- the first candidate being handed the
        # WHOLE deadline -- which is exactly how a merely-slow primary
        # starved every candidate behind it (see
        # `test_a_merely_slow_primary_does_not_starve_the_chain_behind_it`).
        # Two candidates, so the first gets half.
        self.assertEqual(seen["claude_code_cli"], 30.0)
        # The first candidate spent 20 of the 60 seconds the caller will
        # wait; the second must not be handed a fresh 60. It is last, so it
        # gets everything still going: 40, including the 10 the first one
        # was allotted and did not use.
        self.assertAlmostEqual(seen["gemini"], 40.0, places=1)

    async def test_a_candidate_is_not_dialled_with_no_time_left(self):
        """Starting a call that cannot finish spends money and returns
        nothing."""
        clock = self.clock

        class _Burner:
            def __init__(self, name):
                self.name = name
                self.calls = 0


            def available(self):
                return True

            async def complete(self, messages, *, tools, max_tokens, timeout=None):
                self.calls += 1
                clock.advance(59.0)
                raise RuntimeError("slow and then failed")

        primary = _Burner("claude_code_cli")
        secondary = _FakeProvider("gemini")
        router = Router([primary, secondary], {}, self.floor,
                        order=("claude_code_cli", "gemini"), clock=clock)
        with self.assertRaises(Exception):
            await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(require_real=True),
                                  timeout=60.0)
        self.assertEqual(primary.calls, 1)
        self.assertEqual(secondary.calls, 0, "no time was left; dialling it would waste the call")


class TheDeadlineIsSharedNotSpentByTheFirstCandidateTestCase(unittest.IsolatedAsyncioTestCase):
    """Bounding the whole chain with one deadline fixed the caller giving
    up first, and introduced its own version of the same bug one level
    down: the first candidate was handed the entire deadline, so a primary
    that was merely SLOW -- not failing, just slow -- consumed all of it
    and every candidate behind it was skipped as "no time left".

    Observed 2026-09-10 against the real `Router` with a 6s call budget:

        together.complete(timeout=6.00)
        cognition.provider_failed provider=together
        cognition.no_time_for_candidate provider=gemini remaining_s=0.0
        NoRealProvider: together: timed out after 6.0s
        slow.calls=[5.999]  good.calls=[]     <-- gemini was healthy

    A failover chain that only survives a *fast* failure is not a failover
    chain: the slow failure is the one it exists for.
    """

    def setUp(self):
        self.clock = FakeClock()
        self.floor = FloorProvider()

    async def test_a_merely_slow_primary_does_not_starve_the_chain_behind_it(self):
        clock = self.clock

        class _Slow:
            """Honours its timeout, burns all of it, then fails -- what a
            real HTTP client with a socket timeout does."""

            name = "together"

            def __init__(self):
                self.granted: list[float] = []

            def available(self):
                return True

            async def complete(self, messages, *, tools, max_tokens, timeout=None):
                self.granted.append(timeout)
                clock.advance(timeout)
                raise ProviderUnavailable(f"timed out after {timeout}s")

        slow = _Slow()
        healthy = _FakeProvider("gemini")
        router = Router([slow, healthy], {}, self.floor, order=("together", "gemini"), clock=clock)

        response, floor = await router.complete(
            Purpose.CHAT, [{"role": "user", "content": "hi"}], tools=None,
            budget=_budget(require_real=True), timeout=60.0,
        )

        self.assertEqual(slow.granted, [30.0], "the primary may have its share, not the whole deadline")
        self.assertEqual(healthy.calls, 1, "the healthy fallback must still get dialled")
        self.assertEqual(response.provider, "gemini")
        self.assertFalse(floor)

    async def test_the_last_candidate_is_never_handed_a_negative_timeout(self):
        clock = self.clock
        granted: list[float] = []

        class _Recorder:
            def __init__(self, name, burn):
                self.name = name
                self.burn = burn
                self.calls = 0

            def available(self):
                return True

            async def complete(self, messages, *, tools, max_tokens, timeout=None):
                self.calls += 1
                granted.append(timeout)
                clock.advance(self.burn)
                raise ProviderUnavailable("nope")

        a, b, c = _Recorder("together", 25.0), _Recorder("claude_code_cli", 20.0), _Recorder("gemini", 1.0)
        router = Router([a, b, c], {}, self.floor,
                        order=("together", "claude_code_cli", "gemini"), clock=clock)
        with self.assertRaises(NoRealProvider):
            await router.complete(Purpose.CHAT, [], tools=None,
                                  budget=_budget(require_real=True), timeout=60.0)
        self.assertTrue(all(t > 0 for t in granted), f"a candidate was dialled with {granted}")
        self.assertEqual([a.calls, b.calls, c.calls], [1, 1, 1], "every candidate got a real shot")

    async def test_a_provider_that_ignores_its_timeout_cannot_eat_the_deadline(self):
        """`GeminiProvider` accepted `timeout` and dropped it (fixed in the
        same pass). The Router must not be at any provider's mercy for the
        deadline it promised the caller, so it holds each call to its slice
        itself. Real wall-clock, deliberately: the point is that the Router
        stops waiting even when the clock it is told about never moves."""

        class _Ignores:
            name = "together"

            def __init__(self):
                self.calls = 0

            def available(self):
                return True

            async def complete(self, messages, *, tools, max_tokens, timeout=None):
                self.calls += 1
                await asyncio.sleep(300)  # the timeout argument, ignored
                raise AssertionError("unreachable")

        rude = _Ignores()
        router = Router([rude], {}, self.floor, order=("together",), clock=self.clock)
        started = time.monotonic()
        with self.assertRaises(NoRealProvider):
            await router.complete(Purpose.CHAT, [], tools=None,
                                  budget=_budget(require_real=True), timeout=5.0)
        self.assertEqual(rude.calls, 1)
        self.assertLess(time.monotonic() - started, 30.0, "the Router waited on a provider that never stops")

    async def test_running_out_of_time_is_not_reported_as_no_provider_available(self):
        """Honesty: providers were available and willing; the deadline had
        gone. Telling the operator "no real provider available" sends them
        hunting for a dead API key that is not there."""
        provider = _FakeProvider("together")
        router = Router([provider], {}, self.floor, order=("together",), clock=self.clock)
        with self.assertRaises(NoRealProvider) as caught:
            await router.complete(Purpose.CHAT, [], tools=None,
                                  budget=_budget(require_real=True), timeout=0.0)
        self.assertIn("deadline", str(caught.exception))
        self.assertEqual(provider.calls, 0)


class ThePreCallEstimateIsCheckedAgainstTheWindowTestCase(unittest.IsolatedAsyncioTestCase):
    """`RollingWindowBudget.can_spend` has taken an `est_cost_usd` since it
    was written and the Router never passed one -- so the daily cap was only
    ever noticed *after* it had been blown. Observed 2026-09-10 with a real
    ledger-backed budget: $1.99 spent of a $2.00 cap, one call waved
    through, $9.49 spent afterwards.
    """

    def setUp(self):
        self.clock = FakeClock()
        self.floor = FloorProvider()

    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()

    async def test_a_call_estimated_over_the_remaining_window_is_refused_before_it_is_made(self):
        config = ProviderConfig(max_calls=1_000, max_spend_usd=2.0, price_in=0.15, price_out=0.60)
        window = RollingWindowBudget("together", config, self.ledger, clock=self.clock)
        await window.record(ProviderResponse(text="x", provider="together", cost_usd=1.99))

        provider = _FakeProvider("together")
        router = Router([provider], {"together": window}, self.floor, order=("together",), clock=self.clock)
        huge_prompt = [{"role": "user", "content": "word " * 400_000}]  # ~$0.08 of input alone
        with self.assertRaises(NoRealProvider):
            await router.complete(
                Purpose.CHAT, huge_prompt, tools=None,
                # generous per-request ceiling: the provider's own remaining
                # window is what has to stop this, not `max_cost_usd`
                budget=Budget(max_tokens_in=1_000_000, max_tokens_out=100, max_cost_usd=100.0, require_real=True),
                timeout=60.0,
            )
        self.assertEqual(provider.calls, 0, "the call was made anyway, past a cap it could not fit under")
        self.assertAlmostEqual((await window.status()).spend_usd, 1.99)

    async def test_a_call_that_fits_the_remaining_window_still_goes_through(self):
        config = ProviderConfig(max_calls=1_000, max_spend_usd=2.0, price_in=0.15, price_out=0.60)
        window = RollingWindowBudget("together", config, self.ledger, clock=self.clock)
        await window.record(ProviderResponse(text="x", provider="together", cost_usd=1.0))
        provider = _FakeProvider("together")
        router = Router([provider], {"together": window}, self.floor, order=("together",), clock=self.clock)
        response, floor = await router.complete(
            Purpose.CHAT, [{"role": "user", "content": "hi"}], tools=None,
            budget=_budget(require_real=True), timeout=60.0,
        )
        self.assertEqual(response.provider, "together")
        self.assertFalse(floor)


class TheCooldownIsStampedWhenTheFailureHappensTestCase(unittest.IsolatedAsyncioTestCase):
    """The circuit breaker was stamping `call_start + cooldown_s`, not
    `failure_time + cooldown_s`. A provider that fails in 200ms was
    therefore cooled down properly, and one that hangs for a full timeout
    before failing -- the expensive case the breaker was written for -- got
    a cooldown that had already expired the moment it was written.

    Caught through a real Kernel boot, 2026-09-10: `cooldown_until` for
    `together` came back as 1700324360.0 against a clock reading
    1700389196.0, and the "cooling down" provider was re-dialled on the
    very next call.
    """

    def setUp(self):
        self.clock = FakeClock()
        self.floor = FloorProvider()

    async def test_a_provider_that_takes_longer_than_the_cooldown_to_fail_is_still_cooled_down(self):
        clock = self.clock

        class _HangsThenFails:
            name = "together"

            def __init__(self):
                self.calls = 0

            def available(self):
                return True

            async def complete(self, messages, *, tools, max_tokens, timeout=None):
                self.calls += 1
                clock.advance(40.0)  # a real provider timeout: longer than the 30s cooldown
                raise ProviderUnavailable("timed out")

        primary = _HangsThenFails()
        secondary = _FakeProvider("gemini")
        router = Router([primary, secondary], {}, self.floor, order=("together", "gemini"),
                        clock=clock, cooldown_s=30.0)
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=600.0)
        self.assertEqual(primary.calls, 1)

        clock.advance(1.0)  # one second later, well inside the cooldown
        response, _floor = await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=600.0)
        self.assertEqual(primary.calls, 1, "the hung provider was re-dialled inside its own cooldown")
        self.assertEqual(response.provider, "gemini")

        clock.advance(35.0)  # past it
        await router.complete(Purpose.CHAT, [], tools=None, budget=_budget(), timeout=600.0)
        self.assertEqual(primary.calls, 2, "the cooldown must still expire")
