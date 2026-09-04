import time
import unittest

from src.cognition.budget import Budget, BudgetGuard, SPEND_KIND
from src.cognition.provider import LLMResponse, ProviderUnavailable
from src.memory.long_term import InMemoryStore, MemoryRecord


class StubProvider:
    name = "stub"

    def __init__(self, input_tokens: int = 1000, output_tokens: int = 1000):
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self.calls = 0

    def available(self) -> bool:
        return True

    def complete(self, prompt: str, **kwargs) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            text=f"handled: {prompt}",
            provider_name=self.name,
            metadata={
                "input_tokens": self._input_tokens,
                "output_tokens": self._output_tokens,
            },
        )


class TestBudgetGuard(unittest.TestCase):
    def test_available_and_completes_under_budget(self):
        guard = BudgetGuard(StubProvider(), InMemoryStore(), Budget(max_calls=5))

        self.assertTrue(guard.available())
        response = guard.complete("hi")

        self.assertIn("hi", response.text)

    def test_raises_after_max_calls_exhausted(self):
        stub = StubProvider()
        guard = BudgetGuard(stub, InMemoryStore(), Budget(max_calls=2))

        guard.complete("a")
        guard.complete("b")

        with self.assertRaises(ProviderUnavailable):
            guard.complete("c")
        self.assertEqual(stub.calls, 2)  # third call never reached the provider

    def test_raises_after_max_cost_exhausted(self):
        stub = StubProvider(input_tokens=1_000_000, output_tokens=1_000_000)
        guard = BudgetGuard(
            stub,
            InMemoryStore(),
            Budget(max_estimated_cost_usd=1.5),
            price_per_1m_input=1.0,
            price_per_1m_output=1.0,
        )

        guard.complete("a")  # costs $2.00 (1M in + 1M out), already over $1.50

        with self.assertRaises(ProviderUnavailable):
            guard.complete("b")

    def test_available_false_once_exhausted(self):
        guard = BudgetGuard(StubProvider(), InMemoryStore(), Budget(max_calls=1))
        guard.complete("a")

        self.assertFalse(guard.available())

    def test_zero_price_still_enforces_call_cap(self):
        guard = BudgetGuard(
            StubProvider(), InMemoryStore(), Budget(max_calls=1),
            price_per_1m_input=0.0, price_per_1m_output=0.0,
        )
        guard.complete("a")

        with self.assertRaises(ProviderUnavailable):
            guard.complete("b")

    def test_status_reports_totals(self):
        guard = BudgetGuard(
            StubProvider(input_tokens=1_000_000, output_tokens=0),
            InMemoryStore(),
            Budget(max_calls=10, max_estimated_cost_usd=100.0),
            price_per_1m_input=2.0,
        )
        guard.complete("a")

        status = guard.status()

        self.assertEqual(status["calls_in_window"], 1)
        self.assertAlmostEqual(status["spend_in_window_usd"], 2.0)
        self.assertEqual(status["max_calls"], 10)

    def test_old_spend_outside_window_does_not_count(self):
        store = InMemoryStore()
        old_record = MemoryRecord(
            id="old",
            kind=SPEND_KIND,
            content="stub",
            created_at=time.time() - 1000,
            metadata={"cost_usd": 999.0},
        )
        store.add(old_record)
        guard = BudgetGuard(
            StubProvider(), store, Budget(max_estimated_cost_usd=1.0, window_seconds=1)
        )

        # the stale $999 record is outside the 1-second window, so budget
        # is not exhausted
        self.assertTrue(guard.available())

    def test_budget_persists_across_guard_instances_via_shared_store(self):
        store = InMemoryStore()
        budget = Budget(max_calls=1)
        first = BudgetGuard(StubProvider(), store, budget)
        first.complete("a")

        second = BudgetGuard(StubProvider(), store, budget)

        self.assertFalse(second.available())

    def test_two_different_providers_sharing_a_store_have_independent_budgets(self):
        # Live-caught bug: main.py's build_cognition_router wraps Claude
        # Code CLI and Gemini in separate BudgetGuards sharing ONE
        # MemoryStore. Heavy use of one must never count against the
        # other's cap -- previously it did, because _recent_records()
        # queried every kind="llm_spend" record regardless of which
        # provider made it.
        store = InMemoryStore()
        budget = Budget(max_calls=5)
        gemini_provider = StubProvider()
        gemini_provider.name = "gemini"
        gemini_guard = BudgetGuard(gemini_provider, store, budget)

        for _ in range(5):
            gemini_guard.complete("hi")
        self.assertFalse(gemini_guard.available())  # gemini is now exhausted

        claude_provider = StubProvider()
        claude_provider.name = "claude_code_cli"
        claude_guard = BudgetGuard(claude_provider, store, budget)

        self.assertTrue(claude_guard.available())
        claude_guard.complete("hi")  # must not raise
        status = claude_guard.status()
        self.assertEqual(status["calls_in_window"], 1)

    def test_unavailable_wrapped_provider_makes_guard_unavailable(self):
        class UnavailableProvider:
            name = "gone"

            def available(self) -> bool:
                return False

            def complete(self, prompt: str, **kwargs) -> LLMResponse:
                raise ProviderUnavailable("should not be called")

        guard = BudgetGuard(UnavailableProvider(), InMemoryStore(), Budget(max_calls=10))

        self.assertFalse(guard.available())

    def test_reported_cost_overrides_token_based_estimate(self):
        class ReportedCostProvider:
            name = "flat_rate"

            def available(self) -> bool:
                return True

            def complete(self, prompt: str, **kwargs) -> LLMResponse:
                return LLMResponse(
                    text="ok",
                    provider_name=self.name,
                    # a provider-reported cost, no token counts at all --
                    # token-based pricing would compute $0 here
                    metadata={"cost_usd": 0.037},
                )

        guard = BudgetGuard(
            ReportedCostProvider(),
            InMemoryStore(),
            Budget(max_calls=10),
            price_per_1m_input=999.0,  # would dominate if wrongly used
            price_per_1m_output=999.0,
        )

        guard.complete("a")

        self.assertAlmostEqual(guard.status()["spend_in_window_usd"], 0.037)


if __name__ == "__main__":
    unittest.main()
