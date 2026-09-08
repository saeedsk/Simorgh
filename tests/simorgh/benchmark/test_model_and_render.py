"""The run record, the store, and the unicode views."""

from __future__ import annotations

import unittest

from simorgh.benchmark.api import Case, CaseResult, RunRecord, Suite


def _record(model="glm", accuracy=(True, True, False, False), suite="gaia", started=0.0) -> RunRecord:
    record = RunRecord(suite=suite, model=model, started_at=started, suite_version="abc123")
    for index, correct in enumerate(accuracy):
        record.results.append(CaseResult(
            case_id=f"c{index}", level=str(index % 3 + 1), correct=correct,
            expected="x", answer="x" if correct else "y", seconds=1.0,
        ))
    return record


class SuiteTestCase(unittest.TestCase):
    def setUp(self):
        self.suite = Suite(name="gaia", version="v1", cases=tuple(
            Case(id=f"c{i}", question="q", answer="a", level=str(i % 3 + 1)) for i in range(9)
        ))

    def test_levels_are_reported_sorted(self):
        self.assertEqual(self.suite.levels(), ("1", "2", "3"))

    def test_a_sample_takes_the_first_n_so_a_run_repeats(self):
        first = self.suite.sample(3)
        second = self.suite.sample(3)
        self.assertEqual([c.id for c in first.cases], [c.id for c in second.cases])
        self.assertEqual(len(first), 3)

    def test_a_sample_can_be_one_level(self):
        level3 = self.suite.sample(0, level="3")
        self.assertTrue(all(c.level == "3" for c in level3.cases))
        self.assertEqual(len(level3), 3)

    def test_the_version_and_name_survive_sampling(self):
        self.assertEqual(self.suite.sample(2).version, "v1")
        self.assertEqual(self.suite.sample(2).name, "gaia")


class RunRecordTestCase(unittest.TestCase):
    def test_accuracy_ignores_skipped_cases(self):
        record = _record(accuracy=(True, False))
        record.results.append(CaseResult(case_id="s", level="1", correct=False, skipped=True))
        self.assertEqual(record.attempted, 2)
        self.assertEqual(record.skipped, 1)
        self.assertAlmostEqual(record.accuracy, 0.5)

    def test_an_empty_run_is_zero_not_a_crash(self):
        self.assertEqual(RunRecord().accuracy, 0.0)
        self.assertEqual(RunRecord().attempted, 0)

    def test_by_level_counts_correct_over_attempted(self):
        record = _record(accuracy=(True, True, False))
        self.assertEqual(record.by_level(), {"1": (1, 1), "2": (1, 1), "3": (0, 1)})

    def test_a_payload_round_trips(self):
        record = _record()
        back = RunRecord.from_payload(record.to_payload())
        self.assertEqual(back.correct, record.correct)
        self.assertEqual(back.attempted, record.attempted)
        self.assertEqual(back.by_level(), record.by_level())
        self.assertEqual(back.suite_version, "abc123")

    def test_a_compact_payload_still_reports_its_numbers(self):
        """The history endpoint stores no per-case detail; the record
        must still know its own score rather than reporting zero."""
        record = _record(accuracy=(True, True, False, False))
        compact = record.to_payload(with_cases=False)
        self.assertNotIn("cases", compact)
        back = RunRecord.from_payload(compact)
        self.assertEqual(back.attempted, 4)
        self.assertEqual(back.correct, 2)
        self.assertAlmostEqual(back.accuracy, 0.5)


if __name__ == "__main__":
    unittest.main()


class SummaryRoundTripTestCase(unittest.TestCase):
    """A run read back from the history summary must still report its
    own totals. Live-caught 2026-09-08: `benchmark` said "0s total" for
    a run that had really taken 31 seconds, because the round trip kept
    only what synthetic per-case results could carry."""

    def test_seconds_and_cost_survive_a_summary_round_trip(self):
        record = _record()
        for result in record.results:
            object.__setattr__(result, "seconds", 8.0)
            object.__setattr__(result, "cost_usd", 0.001)
        self.assertEqual(record.seconds, 32.0)
        back = RunRecord.from_payload(record.to_payload(with_cases=False))
        self.assertEqual(back.seconds, 32.0)
        self.assertAlmostEqual(back.cost_usd, 0.004)

    def test_a_full_payload_still_computes_from_its_cases(self):
        record = _record()
        back = RunRecord.from_payload(record.to_payload(with_cases=True))
        self.assertEqual(back.totals, {})
        self.assertEqual(back.seconds, record.seconds)
