"""Stage 6 items 1-2: what Sim believes about its own competence, asked
for rather than announced -- and a consumer that acts on it."""

from __future__ import annotations

import unittest

from simorgh.growth.estimate.competence import CompetenceTable


def _table(task_type: str, results: list[bool], *, strategy: str = "direct") -> CompetenceTable:
    table = CompetenceTable()
    for ok in results:
        table._record(task_type=task_type, succeeded=ok, weight=1.0, cost_usd=0.0,  # noqa: SLF001
                      duration_s=1.0, strategy=strategy, stated_confidence=None)
    return table


class ThePosterior(unittest.TestCase):
    def test_nothing_recorded_is_a_flat_prior_not_a_coin_flip(self):
        estimate = CompetenceTable().estimate("patch")
        self.assertEqual((estimate["mean"], estimate["samples"]), (0.5, 0))
        self.assertGreater(estimate["spread"], 0.25, "a flat prior is wide; a consumer must see that")

    def test_a_record_of_failure_shows_as_one(self):
        estimate = _table("patch", [False] * 9 + [True]).estimate("patch")
        self.assertLess(estimate["mean"], 0.25)
        self.assertEqual(estimate["samples"], 10)
        self.assertLess(estimate["spread"], 0.15, "ten samples is narrower than none")

    def test_a_strategy_has_its_own(self):
        table = _table("patch", [True, True, True], strategy="careful")
        for ok in (False, False, False):
            table._record(task_type="patch", succeeded=ok, weight=1.0, cost_usd=0.0,  # noqa: SLF001
                          duration_s=1.0, strategy="hasty", stated_confidence=None)
        self.assertGreater(table.estimate("patch", strategy="careful")["mean"],
                           table.estimate("patch", strategy="hasty")["mean"])
        self.assertEqual(table.estimate("patch", strategy="careful")["strategy"], "careful")


class TheConsumer(unittest.TestCase):
    """Stage 6 item 2: Orchestration starts on the strong tier when Sim's
    own record at this kind of work is poor -- and never on no evidence."""

    def _runner(self, **kw):
        from simorgh.orchestration.session import SessionRunner

        class _Bus:
            source = "orchestration"

        return SessionRunner(_Bus(), None, escalate_from_attempt=3, escalate_below_posterior=0.45,
                             escalate_min_samples=8, **kw)

    def _session(self, estimate: dict):
        from simorgh.orchestration import profiles
        from simorgh.orchestration.api import Session

        session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        session.estimate = estimate
        return session

    def test_a_poor_record_starts_strong(self):
        tier = self._runner()._tier(self._session({"mean": 0.2, "samples": 12}))  # noqa: SLF001
        self.assertEqual(tier["tier"], "strong")
        self.assertIn("20% over 12", tier["tier_reason"])

    def test_a_good_record_does_not(self):
        self.assertEqual(self._runner()._tier(self._session({"mean": 0.8, "samples": 12})), {})  # noqa: SLF001

    def test_a_flat_prior_never_escalates(self):
        """Beta(1,1) reads 0.5 with nothing behind it; escalating on that
        would make every new task type expensive for no reason."""
        self.assertEqual(self._runner()._tier(self._session({"mean": 0.5, "samples": 0})), {})  # noqa: SLF001
        self.assertEqual(self._runner()._tier(self._session({"mean": 0.1, "samples": 3})), {})  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
