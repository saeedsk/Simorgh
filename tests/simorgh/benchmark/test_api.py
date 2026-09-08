"""A stored run has to report its own numbers truthfully.

The history view reads the compact form, which keeps totals and throws
away the cases. Every property on `RunRecord` therefore has to be
recomputable from those totals, and two of them were not.
"""

from __future__ import annotations

import unittest

from simorgh.benchmark.api import CaseResult, RunRecord


class TestASummaryRoundTripKeepsItsOwnNumbers(unittest.TestCase):
    """The compact form drops per-case detail, so every total has to
    survive as a total. Two of them did not, and both understated a
    problem -- the direction that lets a benchmark flatter itself.
    """

    def _record(self) -> RunRecord:
        record = RunRecord(suite="gaia", model="glm-5.3")
        record.results = [
            CaseResult(case_id="a", level="1", correct=True, seconds=3.0),
            CaseResult(case_id="b", level="1", correct=True, seconds=3.0, blocked_by="verification objected"),
            CaseResult(case_id="c", level="1", correct=False, seconds=3.0, blocked_by="step budget"),
            CaseResult(case_id="d", level="2", correct=False, seconds=3.0),
            CaseResult(case_id="e", level="2", correct=False, skipped=True),
            CaseResult(case_id="f", level="2", correct=False, skipped=True),
        ]
        return record

    def test_skipped_cases_are_not_lost(self) -> None:
        original = self._record()
        rebuilt = RunRecord.from_payload(original.to_payload(with_cases=False))
        self.assertEqual(rebuilt.skipped, 2, "a run that skipped cases must still say so")
        self.assertEqual(rebuilt.attempted, original.attempted)

    def test_blocked_answers_are_not_lost(self) -> None:
        original = self._record()
        rebuilt = RunRecord.from_payload(original.to_payload(with_cases=False))
        self.assertEqual(rebuilt.blocked, 2)
        self.assertEqual(rebuilt.blocked_but_correct, 1,
                         "the count that says our own verifier cost us an answer")

    def test_accuracy_survives_a_suite_with_no_levels(self) -> None:
        """Only GAIA writes `by_level`; a BFCL run used to come back as a
        total failure because no synthetic cases were built at all."""
        payload = {"suite": "bfcl", "attempted": 20, "correct": 13, "accuracy": 0.65, "seconds": 44.0}
        rebuilt = RunRecord.from_payload(payload)
        self.assertEqual((rebuilt.attempted, rebuilt.correct), (20, 13))
        self.assertAlmostEqual(rebuilt.accuracy, 0.65)

    def test_the_headline_numbers_all_match(self) -> None:
        original = self._record()
        rebuilt = RunRecord.from_payload(original.to_payload(with_cases=False))
        for name in ("attempted", "correct", "skipped", "blocked", "blocked_but_correct"):
            self.assertEqual(getattr(rebuilt, name), getattr(original, name), name)
        self.assertAlmostEqual(rebuilt.accuracy, original.accuracy)
        self.assertAlmostEqual(rebuilt.seconds, original.seconds)
