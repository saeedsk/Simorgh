"""The `Connector` protocol (contracts/connector.py): the lifecycle every
account-backed integration shares, and the two helpers each one leans
on so any-of credential groups and rate budgets are implemented once.

No connector here touches an account or the network -- `FakeConnector`
is the model every real connector's own fake follows."""

from __future__ import annotations

import unittest

from simorgh.contracts.connector import (
    Budget,
    BudgetExhausted,
    Connector,
    ConnectorStatus,
    FakeConnector,
    missing_packages,
    missing_requirements,
)


class MissingRequirementsTestCase(unittest.TestCase):
    def test_present_needs_are_not_reported(self):
        self.assertEqual(missing_requirements(("A", "B"), {"A": True, "B": True}), ())

    def test_absent_needs_are_reported_in_order(self):
        self.assertEqual(missing_requirements(("A", "B", "C"), {"B": True}), ("A", "C"))

    def test_an_any_of_group_is_satisfied_by_one_member(self):
        self.assertEqual(missing_requirements(("GEMINI_API_KEY|GOOGLE_API_KEY",), {"GOOGLE_API_KEY": True}), ())

    def test_an_unsatisfied_group_is_reported_whole_so_the_person_sees_every_option(self):
        self.assertEqual(missing_requirements(("A|B",), {}), ("A|B",))


class MissingPackagesTestCase(unittest.TestCase):
    def test_stdlib_modules_are_present(self):
        self.assertEqual(missing_packages(("json", "sqlite3")), ())

    def test_a_package_that_does_not_exist_is_named(self):
        self.assertEqual(missing_packages(("json", "no_such_package_zz")), ("no_such_package_zz",))


class BudgetTestCase(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.budget = Budget("imap", limit=3, window_s=60.0, clock=lambda: self.now)

    def test_calls_within_the_limit_are_allowed(self):
        for _ in range(3):
            self.budget.take()
        self.assertEqual(self.budget.remaining(), 0)

    def test_the_call_over_the_limit_refuses_and_says_when(self):
        for _ in range(3):
            self.budget.take()
        self.now += 10.0
        with self.assertRaises(BudgetExhausted) as caught:
            self.budget.take()
        self.assertIn("imap", str(caught.exception))
        self.assertIn("try again in 50s", str(caught.exception))
        self.assertAlmostEqual(caught.exception.retry_after_s, 50.0)

    def test_the_window_slides(self):
        for _ in range(3):
            self.budget.take()
        self.now += 61.0
        self.budget.take()  # no raise
        self.assertEqual(self.budget.remaining(), 2)

    def test_a_zero_limit_always_refuses(self):
        with self.assertRaises(BudgetExhausted):
            Budget("x", limit=0, clock=lambda: 0.0).take()

    def test_backoff_is_exponential_and_capped(self):
        budget = Budget("x", base_backoff_s=1.0, max_backoff_s=10.0)
        self.assertEqual([budget.backoff_s(n) for n in (0, 1, 2, 3, 4, 5, 9)],
                         [0.0, 1.0, 2.0, 4.0, 8.0, 10.0, 10.0])


class FakeConnectorTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_the_fake_satisfies_the_protocol(self):
        fake = FakeConnector("caldav", needs=("caldav:home",), packages=("caldav",))
        self.assertIsInstance(fake, Connector)
        status = await fake.probe()
        self.assertIsInstance(status, ConnectorStatus)
        self.assertTrue(status.ok)

    async def test_a_configured_failure_names_what_is_missing(self):
        fake = FakeConnector("imap", ok=False, detail="set IMAP_PASSWORD", missing=("IMAP_PASSWORD",))
        status = await fake.probe()
        self.assertFalse(status.ok)
        self.assertEqual(status.missing, ("IMAP_PASSWORD",))
        self.assertEqual(fake.probes, 1)

    async def test_close_is_idempotent(self):
        fake = FakeConnector()
        await fake.close()
        await fake.close()
        self.assertEqual(fake.closed, 2)


if __name__ == "__main__":
    unittest.main()
