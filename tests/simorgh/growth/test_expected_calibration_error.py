"""When Sim says 80%, does it happen 80% of the time?

Stage 6 item 1 asks for "calibration as expected calibration error".
The bins it needs -- confidence bucket to [n, hits] -- have been
recorded and persisted since the competence table was written, and
were read by nothing at all: `state()` wrote them out, `load()` read
them back, and no code in the tree ever looked at one.

`calibration()` is a different number and stays. It is the mean
absolute gap per outcome, which punishes a confident mistake harder.
ECE answers the binned question, which is the one about whether a
stated confidence means anything.
"""

import unittest

from simorgh.contracts.envelope import Event
from simorgh.growth.estimate.competence import CONFIDENCE_SAMPLES_KEPT, CompetenceTable

T0 = 1_700_000_000.0


def _table(task_type: str, *, confidence: float, hit_every: int, n: int = 100) -> CompetenceTable:
    table = CompetenceTable()
    for i in range(n):
        table.apply(Event(stream="learn:outcomes", type="outcome", ts=T0 + i,
                          trace_id="", causation_id=None,
                          payload={"task_type": task_type, "succeeded": i % 10 < hit_every,
                                   "stated_confidence": confidence}))
    return table


class WhatItMeasures(unittest.TestCase):
    def test_a_well_calibrated_claim_scores_near_zero(self):
        """Says 95%, right 9 times in 10."""
        table = _table("good", confidence=0.95, hit_every=9)
        self.assertLess(table.expected_calibration_error("good"), 0.1)

    def test_an_overconfident_one_scores_high(self):
        """Says 95%, right 3 times in 10."""
        table = _table("bad", confidence=0.95, hit_every=3)
        self.assertGreater(table.expected_calibration_error("bad"), 0.5)

    def test_underconfidence_counts_too(self):
        """Saying 15% and being right every time is just as wrong
        about itself, and a one-sided measure would call it fine."""
        table = _table("shy", confidence=0.15, hit_every=10)
        self.assertGreater(table.expected_calibration_error("shy"), 0.5)

    def test_nothing_recorded_is_no_opinion(self):
        self.assertIsNone(CompetenceTable().expected_calibration_error("unseen"))

    def test_outcomes_without_a_stated_confidence_say_nothing(self):
        table = CompetenceTable()
        for i in range(20):
            table.apply(Event(stream="learn:outcomes", type="outcome", ts=T0 + i,
                              trace_id="", causation_id=None,
                              payload={"task_type": "quiet", "succeeded": True}))
        self.assertIsNone(table.expected_calibration_error("quiet"))


class WhereItSurfaces(unittest.TestCase):
    def test_the_estimate_carries_it(self):
        table = _table("bad", confidence=0.95, hit_every=3)
        self.assertIn("ece", table.estimate("bad"))

    def test_an_estimate_with_no_calibration_data_omits_it(self):
        """An absent key reads as "not measured"; a 0.0 would read as
        "perfectly calibrated", which is the opposite."""
        table = CompetenceTable()
        table.apply(Event(stream="learn:outcomes", type="outcome", ts=T0,
                          trace_id="", causation_id=None,
                          payload={"task_type": "quiet", "succeeded": True}))
        self.assertNotIn("ece", table.estimate("quiet"))

    def test_it_survives_a_snapshot(self):
        table = _table("bad", confidence=0.95, hit_every=3)
        back = CompetenceTable()
        back.load(table.state())
        self.assertEqual(back.expected_calibration_error("bad"),
                         table.expected_calibration_error("bad"))


class TheSampleListIsBounded(unittest.TestCase):
    def test_it_stops_growing(self):
        """It is persisted in `state()` and nothing ever dropped from
        it: a year of turns would put a megabyte of floats in every
        snapshot for a number the last few hundred already answer."""
        table = _table("busy", confidence=0.8, hit_every=8, n=CONFIDENCE_SAMPLES_KEPT + 250)
        self.assertLessEqual(len(table._confidence_samples["busy"]), CONFIDENCE_SAMPLES_KEPT)

    def test_the_bins_keep_the_long_view(self):
        """Ten integers, so dropping old samples costs the ECE
        nothing."""
        table = _table("busy", confidence=0.95, hit_every=3, n=CONFIDENCE_SAMPLES_KEPT + 250)
        total = sum(n for n, _hits in table.get("busy").calib_bins.values())
        self.assertEqual(total, CONFIDENCE_SAMPLES_KEPT + 250)
        self.assertGreater(table.expected_calibration_error("busy"), 0.5)


if __name__ == "__main__":
    unittest.main()
