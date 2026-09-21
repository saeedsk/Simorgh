"""What Sim was bad at in the spring must not outvote today.

Stage 6 item 1 asks for "exponential forgetting (half-life config)".
Without it the competence table is a monument: a bad fortnight in a
task type keeps routing away from it long after the bug behind it
was fixed, and nothing Sim does afterwards can outweigh enough
history.

The sums are aged on write, not read -- they are all this table
keeps, so decaying them in place is exact and costs one multiply,
where decaying at read time would need every outcome's timestamp
kept forever.
"""

import unittest

from simorgh.contracts.envelope import Event
from simorgh.growth.estimate.competence import HALF_LIFE_S, CompetenceTable

DAY = 86_400.0
#: A real timestamp. `ts=0.0` means "no timestamp" to this code and
#: never appears on a real event, so a test built on it measures the
#: unknown-time path rather than the decay -- which is how the first
#: version of this file fooled itself.
T0 = 1_700_000_000.0


def _outcome(task_type: str, succeeded: bool, ts: float, *, strategy: str | None = None) -> Event:
    payload = {"task_type": task_type, "succeeded": succeeded}
    if strategy:
        payload["strategy"] = strategy
    return Event(stream="learn:outcomes", type="outcome", ts=ts,
                 trace_id="", causation_id=None, payload=payload)


def _mean(table: CompetenceTable, task_type: str) -> float:
    alpha, beta, _n = table.posterior(task_type)
    return alpha / (alpha + beta)


class OldFailuresFade(unittest.TestCase):
    def test_three_recent_successes_outweigh_ten_ancient_failures(self):
        table = CompetenceTable()
        for i in range(10):
            table.apply(_outcome("patch", False, T0 + i))
        for i in range(3):
            table.apply(_outcome("patch", True, T0 + 90 * DAY + i))
        self.assertGreater(_mean(table, "patch"), 0.5,
                           "ninety days and three wins later, Sim is not still bad at this")

    def test_and_would_not_without_forgetting(self):
        """The same events with the half-life off: the spring wins."""
        table = CompetenceTable(half_life_s=0.0)
        for i in range(10):
            table.apply(_outcome("patch", False, T0 + i))
        for i in range(3):
            table.apply(_outcome("patch", True, T0 + 90 * DAY + i))
        self.assertLess(_mean(table, "patch"), 0.35)

    def test_one_half_life_halves_the_evidence(self):
        table = CompetenceTable()
        for i in range(8):
            table.apply(_outcome("patch", True, T0 + i))
        table.apply(_outcome("patch", True, T0 + HALF_LIFE_S))
        _alpha, _beta, samples = table.posterior("patch")
        self.assertAlmostEqual(samples, 8 * 0.5 + 1, places=1)


class WhatIsNotAged(unittest.TestCase):
    def test_recent_outcomes_are_not_discounted(self):
        table = CompetenceTable()
        for i in range(5):
            table.apply(_outcome("patch", True, T0 + i))
        _a, _b, samples = table.posterior("patch")
        self.assertAlmostEqual(samples, 5.0, places=3)

    def test_replay_out_of_order_never_ages_backwards(self):
        """A ledger replay can hand events in any order; aging on a
        negative interval would AMPLIFY old evidence."""
        table = CompetenceTable()
        table.apply(_outcome("patch", True, T0 + 90 * DAY))
        table.apply(_outcome("patch", True, T0))
        _a, _b, samples = table.posterior("patch")
        self.assertAlmostEqual(samples, 2.0, places=3)

    def test_an_event_with_no_timestamp_is_not_a_time_traveller(self):
        """`ts=0.0` means unknown, and an unknown age must not decay
        anything -- guessing an age would be inventing evidence."""
        table = CompetenceTable()
        for _ in range(4):
            table.apply(_outcome("patch", True, 0.0))
        _a, _b, samples = table.posterior("patch")
        self.assertAlmostEqual(samples, 4.0, places=3)


class Strategies(unittest.TestCase):
    def test_a_strategy_fades_with_its_task_type(self):
        table = CompetenceTable()
        for i in range(10):
            table.apply(_outcome("patch", False, T0 + i, strategy="brute"))
        table.apply(_outcome("patch", True, T0 + 120 * DAY, strategy="brute"))
        alpha, beta, _n = table.posterior("patch", strategy="brute")
        self.assertGreater(alpha / (alpha + beta), 0.5)


class ItSurvivesASnapshot(unittest.TestCase):
    def test_the_age_round_trips(self):
        table = CompetenceTable()
        for i in range(4):
            table.apply(_outcome("patch", True, T0 + i, strategy="s"))
        back = CompetenceTable()
        back.load(table.state())
        self.assertEqual(back.posterior("patch"), table.posterior("patch"))

    def test_a_snapshot_written_before_forgetting_existed_still_loads(self):
        """`at` is absent from every table stored until today."""
        old = {"by_type": {"patch": {"n": 4, "successes_w": 3.0, "cost_sum": 0.0, "dur_sum": 0.0,
                                     "strategies": {"s": {"n": 4, "successes_w": 3.0, "cost_sum": 0.0}}}}}
        table = CompetenceTable()
        table.load(old)
        _a, _b, samples = table.posterior("patch")
        self.assertAlmostEqual(samples, 4.0, places=3)


class ATableNobodyFeedsGoesQuiet(unittest.TestCase):
    def test_a_year_of_silence_then_one_outcome_reads_as_almost_new(self):
        table = CompetenceTable()
        for i in range(20):
            table.apply(_outcome("patch", False, T0 + i))
        table.apply(_outcome("patch", True, T0 + 365 * DAY))
        _a, _b, samples = table.posterior("patch")
        self.assertLess(samples, 2.0, "a year on, the old twenty are gone")


if __name__ == "__main__":
    unittest.main()


class AnEffectiveCountIsRoundedNotTruncated(unittest.TestCase):
    """The bug this change introduced, and the test that caught it.

    Five outcomes a few seconds apart come back as 4.999997 -- exactly
    right, and `int()` turns it into four. Every consumer that wanted
    a whole number was quietly losing one sample at each boundary,
    including the "5+ samples to trust an estimate" gates.
    """

    def test_thompson_rounds(self):
        from simorgh.contracts.envelope import Event
        from simorgh.growth.explore.thompson import unknowns_from

        table = CompetenceTable()
        for seq in range(1, 6):
            table.apply(Event(seq=seq, stream="learn:outcomes", type="outcome", ts=T0 + seq,
                              trace_id="t", causation_id=None,
                              payload={"task_type": "patch", "succeeded": False}))
        [found] = unknowns_from(competence=table, task_types=["patch"])
        self.assertEqual(found.samples, 5)

    def test_the_underlying_number_is_left_exact(self):
        """Rounding is for the people and the gates reading it; the
        table itself must keep what it measured."""
        from simorgh.contracts.envelope import Event

        table = CompetenceTable()
        for seq in range(1, 6):
            table.apply(Event(seq=seq, stream="learn:outcomes", type="outcome", ts=T0 + seq,
                              trace_id="t", causation_id=None,
                              payload={"task_type": "patch", "succeeded": False}))
        self.assertNotEqual(table.samples("patch"), 5)
        self.assertAlmostEqual(table.samples("patch"), 5, places=4)
