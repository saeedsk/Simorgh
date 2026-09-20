"""Stage 4 item 9: the evals package reports honestly.

The three things worth pinning are the ones a report can lie about: a
skipped case must not count as a pass, a suite that could not start must
not read as a zero, and the interval must not move when nothing moved.
The household suite itself is measured live by `simloader bless`; what
is tested here is the arithmetic and the wiring around it.
"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from simorgh.evals.api import Case, FAILED, Outcome, PASSED, Report, SKIPPED, bootstrap_ci, outcomes_from
from simorgh.evals.runner import last, record, run, table
from simorgh.evals.suites import PAID, SUITES, find


def _outcome(name: str, status: str, level: str = "") -> Outcome:
    return Outcome(case=Case(name=name, kind="probe", level=level), status=status)


class AReportCounts(unittest.TestCase):
    def test_a_skipped_case_is_not_in_the_denominator(self):
        report = Report(suite="s", outcomes=[_outcome("a", PASSED), _outcome("b", SKIPPED),
                                             _outcome("c", FAILED)])
        self.assertEqual((report.passed, report.total, report.skipped), (1, 2, 1))
        self.assertEqual(report.rate, 0.5)

    def test_a_suite_that_could_not_start_scores_nothing_rather_than_zero(self):
        report = Report(suite="s", outcomes=[_outcome("s", SKIPPED)])
        self.assertEqual(report.total, 0)
        self.assertEqual(report.rate, 0.0, "no cases means no rate")
        self.assertEqual(report.as_dict()["skipped"], 1)

    def test_levels_are_reported_separately(self):
        report = Report(suite="s", outcomes=[_outcome("a", PASSED, "1"), _outcome("b", FAILED, "3"),
                                             _outcome("c", PASSED, "1")])
        self.assertEqual(report.by_level(), {"1": (2, 2), "3": (0, 1)})

    def test_the_interval_does_not_move_when_nothing_moved(self):
        values = [1.0, 1.0, 0.0, 1.0, 0.0, 1.0]
        self.assertEqual(bootstrap_ci(values), bootstrap_ci(values))
        low, high = bootstrap_ci(values)
        self.assertLessEqual(low, sum(values) / len(values))
        self.assertGreaterEqual(high, sum(values) / len(values))

    def test_one_result_admits_it_knows_nothing(self):
        self.assertEqual(bootstrap_ci([1.0]), (0.0, 1.0))


class AReportSurvivesJson(unittest.TestCase):
    """Each repeat runs in its own process, so the outcomes come back
    through JSON; what goes out has to come back the same."""

    def test_the_cases_round_trip(self):
        report = Report(suite="s", outcomes=[_outcome("a", PASSED, "1"), _outcome("b", FAILED, "2")])
        back = outcomes_from(json.loads(json.dumps(report.as_dict()))["cases"])
        self.assertEqual([(o.case.name, o.case.level, o.status) for o in back],
                         [("a", "1", PASSED), ("b", "2", FAILED)])


class TheRecord(unittest.TestCase):
    def test_a_run_is_appended_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            record(Report(suite="household", outcomes=[_outcome("a", PASSED)]), data_dir=tmp)
            record(Report(suite="household", outcomes=[_outcome("a", FAILED)]), data_dir=tmp)
            record(Report(suite="trials", outcomes=[_outcome("t", PASSED)]), data_dir=tmp)
            lines = (Path(tmp) / "evals.jsonl").read_text().strip().splitlines()
            self.assertEqual(len(lines), 3, "appended, never rewritten")
            self.assertEqual(last(tmp, suite="household")["passed"], 0, "the most recent household run")
            self.assertEqual(last(tmp)["suite"], "trials")

    def test_no_record_yet_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(last(tmp))


class TheSuites(unittest.TestCase):
    def test_every_paid_suite_is_registered(self):
        self.assertTrue(PAID.issubset(set(SUITES)))

    def test_household_is_free(self):
        self.assertNotIn("household", PAID, "the bless runs it on every commit")

    def test_an_unknown_suite_names_the_ones_that_exist(self):
        with self.assertRaises(KeyError) as caught:
            find("nope")
        self.assertIn("household", str(caught.exception))


class TheTable(unittest.TestCase):
    def test_it_says_the_rate_the_interval_and_what_failed(self):
        report = Report(suite="household", repeats=2,
                        outcomes=[_outcome("a", PASSED), Outcome(case=Case(name="b"), status=FAILED,
                                                                 why="the fact never reached the prompt")])
        text = table(report)
        self.assertIn("household: 1/2", text)
        self.assertIn("95% CI", text)
        self.assertIn("the fact never reached the prompt", text)


class ARepeatThatDies(unittest.IsolatedAsyncioTestCase):
    """A child that crashes must not shrink the denominator silently --
    that is how a suite comes to report 3/3 having run one case."""

    async def test_it_becomes_a_skipped_case_that_says_so(self):
        from simorgh.evals import runner as runner_mod

        async def _die(suite, index):
            from simorgh.evals.api import Case as C, Outcome as O

            return [O(case=C(name=f"repeat {index + 1}", kind=suite), status=SKIPPED,
                      why="the repeat did not finish: boom")]

        original = runner_mod._one_in_a_child  # noqa: SLF001
        runner_mod._one_in_a_child = _die  # noqa: SLF001
        try:
            report = await run("household", repeats=2, isolate=True)
        finally:
            runner_mod._one_in_a_child = original  # noqa: SLF001
        self.assertEqual(report.total, 0)
        self.assertEqual(report.skipped, 2)
        self.assertIn("boom", report.outcomes[0].why)


if __name__ == "__main__":
    unittest.main()
