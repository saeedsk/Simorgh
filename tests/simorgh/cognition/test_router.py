"""`Router` (docs/blueprint/subsystems/04-cognition.md section 5): ported
v1 `CognitionRouter` failover shape -- try each configured candidate in
order, skip an unavailable/exhausted/erroring one, fall through to the
floor unless `require_real_provider`."""

from __future__ import annotations

import unittest

from simorgh.cognition.api import Budget, BudgetExceeded, NoRealProvider, ProviderUnavailable, Purpose
from simorgh.cognition.providers.base import FloorProvider
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
