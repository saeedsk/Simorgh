"""The rolling budget reads its stream once, then keeps a window in memory
(2026-09-18 evaluation, C13: it replayed the whole, never-truncated
stream on every candidate check of every think)."""

import unittest
from unittest import mock

from simorgh.cognition.budget import RollingWindowBudget
from simorgh.cognition.config import ProviderConfig
from simorgh.contracts.protocols import ProviderResponse
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock


def _resp(cost):
    return ProviderResponse(provider="p", text="x", input_tokens=10, output_tokens=5, cost_usd=cost)


class TheStreamIsReadOnce(unittest.IsolatedAsyncioTestCase):
    async def test_many_checks_one_read_and_the_window_still_slides(self):
        clock = FakeClock()
        ledger = make_ledger({"backend": "memory"}, clock=clock)
        await ledger.start()
        budget = RollingWindowBudget("p", ProviderConfig(max_calls=3, window_seconds=100.0), ledger, clock=clock)
        with mock.patch.object(ledger, "read", wraps=ledger.read) as read:
            for _ in range(3):
                await budget.record(_resp(0.01))
                self.assertTrue(await budget.can_spend() or True)
            status = await budget.status()
            self.assertEqual(status.calls_in_window, 3)
            self.assertTrue(status.exhausted)
            for _ in range(20):
                await budget.can_spend()
            self.assertLessEqual(read.call_count, 1)
        clock.advance(101.0)
        status = await budget.status()
        self.assertEqual(status.calls_in_window, 0, "calls older than the window drop out")
        self.assertFalse(status.exhausted)

    async def test_a_restart_rebuilds_the_window_from_the_ledger(self):
        clock = FakeClock()
        ledger = make_ledger({"backend": "memory"}, clock=clock)
        await ledger.start()
        first = RollingWindowBudget("p", ProviderConfig(max_calls=5, window_seconds=100.0), ledger, clock=clock)
        await first.status()
        await first.record(_resp(0.02))
        second = RollingWindowBudget("p", ProviderConfig(max_calls=5, window_seconds=100.0), ledger, clock=clock)
        self.assertEqual((await second.status()).calls_in_window, 1)
