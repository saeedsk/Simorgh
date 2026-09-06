"""`RollingWindowBudget` (docs/blueprint/subsystems/04-cognition.md
section 4): durable, replayed-from-the-Ledger accounting, and the one
real v1 bug this port deliberately does not reintroduce -- one
provider's spend must never count against another provider's cap."""

from __future__ import annotations

import unittest

from simorgh.cognition.budget import RollingWindowBudget, stream_for
from simorgh.cognition.config import ProviderConfig
from simorgh.contracts.protocols import ProviderResponse
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock


class TestRollingWindowBudget(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()

    async def test_status_starts_empty(self):
        budget = RollingWindowBudget("claude_code_cli", ProviderConfig(max_calls=5), self.ledger, clock=self.clock)
        status = await budget.status()
        self.assertEqual(status.calls_in_window, 0)
        self.assertFalse(status.exhausted)

    async def test_record_then_status_reflects_the_new_call(self):
        budget = RollingWindowBudget("claude_code_cli", ProviderConfig(max_calls=5), self.ledger, clock=self.clock)
        await budget.record(ProviderResponse(text="x", provider="claude_code_cli", cost_usd=0.01))
        status = await budget.status()
        self.assertEqual(status.calls_in_window, 1)
        self.assertAlmostEqual(status.spend_usd, 0.01)

    async def test_exhausted_by_call_count(self):
        budget = RollingWindowBudget("claude_code_cli", ProviderConfig(max_calls=2), self.ledger, clock=self.clock)
        for _ in range(2):
            await budget.record(ProviderResponse(text="x", provider="claude_code_cli", cost_usd=0.0))
        self.assertTrue((await budget.status()).exhausted)
        self.assertFalse(await budget.can_spend())

    async def test_exhausted_by_spend_cap(self):
        budget = RollingWindowBudget(
            "gemini", ProviderConfig(max_calls=1_000, max_spend_usd=1.0), self.ledger, clock=self.clock,
        )
        await budget.record(ProviderResponse(text="x", provider="gemini", cost_usd=1.5))
        self.assertTrue((await budget.status()).exhausted)

    async def test_records_outside_the_window_do_not_count(self):
        budget = RollingWindowBudget(
            "claude_code_cli", ProviderConfig(max_calls=2, window_seconds=100.0), self.ledger, clock=self.clock,
        )
        await budget.record(ProviderResponse(text="x", provider="claude_code_cli", cost_usd=0.0))
        self.clock.advance(200.0)  # past the window
        status = await budget.status()
        self.assertEqual(status.calls_in_window, 0)
        self.assertFalse(status.exhausted)

    async def test_accounting_survives_a_fresh_client_over_the_same_stream(self):
        # "the Ledger is the truth" -- a brand new RollingWindowBudget
        # instance replaying the same stream sees the same state, not an
        # in-memory counter that resets with the object.
        first = RollingWindowBudget("claude_code_cli", ProviderConfig(max_calls=5), self.ledger, clock=self.clock)
        await first.record(ProviderResponse(text="x", provider="claude_code_cli", cost_usd=0.02))
        second = RollingWindowBudget("claude_code_cli", ProviderConfig(max_calls=5), self.ledger, clock=self.clock)
        status = await second.status()
        self.assertEqual(status.calls_in_window, 1)
        self.assertAlmostEqual(status.spend_usd, 0.02)

    async def test_per_provider_isolation_the_live_caught_v1_bug(self):
        # v1 originally let one provider's spend count against another
        # provider's own cap -- claude_code_cli's own budget would report
        # itself exhausted purely from Gemini's unrelated volume. Records
        # are filtered by stream (provider name), never by kind alone.
        claude_budget = RollingWindowBudget("claude_code_cli", ProviderConfig(max_calls=2), self.ledger, clock=self.clock)
        gemini_budget = RollingWindowBudget("gemini", ProviderConfig(max_calls=2), self.ledger, clock=self.clock)

        for _ in range(5):
            await gemini_budget.record(ProviderResponse(text="x", provider="gemini", cost_usd=0.0))

        claude_status = await claude_budget.status()
        self.assertEqual(claude_status.calls_in_window, 0)
        self.assertFalse(claude_status.exhausted)
        self.assertTrue((await gemini_budget.status()).exhausted)
        self.assertNotEqual(stream_for("claude_code_cli"), stream_for("gemini"))

    async def test_estimate_cost_prefers_provider_reported_cost(self):
        budget = RollingWindowBudget(
            "gemini", ProviderConfig(price_in=1.0, price_out=1.0), self.ledger, clock=self.clock,
        )
        await budget.record(ProviderResponse(text="x", provider="gemini", input_tokens=1_000_000, output_tokens=0, cost_usd=0.0))
        status = await budget.status()
        # cost_usd=0.0 is provider-reported (not None) -- must win over the token*price estimate.
        self.assertEqual(status.spend_usd, 0.0)

    async def test_estimate_cost_falls_back_to_token_prices_when_unreported(self):
        budget = RollingWindowBudget(
            "gemini", ProviderConfig(price_in=2.0, price_out=4.0), self.ledger, clock=self.clock,
        )
        await budget.record(ProviderResponse(text="x", provider="gemini", input_tokens=1_000_000, output_tokens=500_000, cost_usd=None))
        status = await budget.status()
        self.assertAlmostEqual(status.spend_usd, 2.0 + 2.0)


if __name__ == "__main__":
    unittest.main()
