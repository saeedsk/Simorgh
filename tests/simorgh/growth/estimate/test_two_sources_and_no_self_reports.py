"""Stage 8 item 2: what an estimate is allowed to rest on.

Two sources, weighted: task outcomes a verification backed, and eval
pass rates. Nothing else -- and in particular not the task's own word
that it finished, which is what 'completed with no verification' is.
An estimate built on self-reports measures how confidently Sim finishes,
not how often it is right, and those two numbers came apart badly enough
in the live logs to be worth a rule.

The acceptance case is at the bottom: a seeded outcome stream plus an
eval history yields the posterior you can work out by hand.
"""

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.growth.estimate.competence import CompetenceTable
from simorgh.growth.estimate.config import Config
from simorgh.growth.estimate.service import Service
from simorgh.ledger.api import Event


def _outcome(seq: int, task_type: str, succeeded: bool, weight: float = 1.0) -> Event:
    return Event(seq=seq, stream="learn:outcomes", type="outcome", ts=float(seq), trace_id="t",
                 causation_id=None,
                 payload={"task_type": task_type, "succeeded": succeeded, "weight": weight,
                          "cost_usd": 0.0, "duration_s": 1.0})


class AnEvalIsEvidenceToo(unittest.TestCase):
    def test_a_suite_lands_under_its_own_key(self):
        """Kept apart from the task type's own counts, so "what a
        fixture says" and "what happened in this house" can be read
        separately."""
        table = CompetenceTable()
        table.record_eval("trials", passed=5, total=7, weight=1.0)
        self.assertEqual(table.samples("eval:trials"), 7)
        self.assertEqual(table.samples("patch"), 0)

    def test_an_empty_suite_records_nothing(self):
        table = CompetenceTable()
        table.record_eval("trials", passed=0, total=0)
        self.assertEqual(table.samples("eval:trials"), 0)

    def test_it_is_folded_in_only_when_asked_for(self):
        table = CompetenceTable()
        table.record_eval("trials", passed=4, total=4, weight=1.0)
        plain = table.posterior("patch")
        blended = table.posterior("patch", eval_suite="trials", eval_weight=1.0)
        self.assertEqual(plain, (1.0, 1.0, 0), "no outcomes and no suite asked for: no idea")
        self.assertEqual(blended, (5.0, 1.0, 4))

    def test_the_weight_scales_what_a_fixture_is_worth(self):
        table = CompetenceTable()
        table.record_eval("trials", passed=4, total=4, weight=1.0)
        alpha, beta, samples = table.posterior("patch", eval_suite="trials", eval_weight=0.5)
        self.assertEqual((alpha, beta), (3.0, 1.0))
        self.assertEqual(samples, 4, "the cases are still reported as cases")


class ASelfReportIsNotEvidence(unittest.TestCase):
    def test_a_verified_success_outweighs_an_unverified_one(self):
        verified, unverified = CompetenceTable(), CompetenceTable()
        verified.apply(_outcome(1, "patch", True, weight=1.0))
        unverified.apply(_outcome(1, "patch", True, weight=Config().unverified_sample_weight))
        self.assertGreater(verified.success_rate("patch"), unverified.success_rate("patch"))

    def test_an_unverified_success_still_counts_a_little(self):
        """Throwing it away entirely would leave whole task types with
        no estimate at all."""
        table = CompetenceTable()
        table.apply(_outcome(1, "patch", True, weight=Config().unverified_sample_weight))
        self.assertGreater(table.success_rate("patch"), 0.0)
        self.assertEqual(table.samples("patch"), 1)


class TheEvalRecord(unittest.TestCase):
    def setUp(self):
        self.service = Service(Config(eval_sample_weight=1.0))

    def _write(self, rows) -> Path:
        tmp = Path(tempfile.mkdtemp()) / "evals.jsonl"
        tmp.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return tmp

    def test_the_newest_report_per_suite_is_the_one_that_counts(self):
        """Older runs are history, not more evidence -- counting every
        one would let a suite run fifty times outvote the house."""
        path = self._write([{"suite": "household", "passed": 1, "total": 3},
                            {"suite": "household", "passed": 3, "total": 3}])
        self.assertEqual(self.service.load_evals(path), 1)
        table = self.service._competence  # noqa: SLF001
        self.assertEqual((table.samples("eval:household")), 3)
        alpha, _beta, _n = table.posterior("chat", eval_suite="household", eval_weight=1.0)
        self.assertEqual(alpha, 4.0, "3 passes on the newest run, not 1 + 3 over both")

    def test_a_missing_file_is_not_an_error(self):
        self.assertEqual(self.service.load_evals(Path("/nowhere/evals.jsonl")), 0)

    def test_a_broken_line_is_skipped_rather_than_fatal(self):
        path = self._write([{"suite": "household", "passed": 3, "total": 3}])
        path.write_text(path.read_text() + "\nnot json at all\n", encoding="utf-8")
        self.assertEqual(self.service.load_evals(path), 1)

    def test_the_suite_for_a_task_type_ignores_what_follows_the_colon(self):
        """A task type is `patch:src/memory`; the suite is about
        patching, not about that directory."""
        self.assertEqual(self.service._suite_for("patch:src/memory"), "trials")  # noqa: SLF001
        self.assertIsNone(self.service._suite_for("something_else"))  # noqa: SLF001


class TheAcceptanceCase(unittest.TestCase):
    """A seeded outcome stream plus an eval history yields the expected
    posterior -- worked out by hand here so a change to the weighting
    has to be deliberate."""

    def test_the_posterior_is_what_the_two_sources_add_up_to(self):
        config = Config(eval_sample_weight=0.5, unverified_sample_weight=0.25)
        service = Service(config)
        table = service._competence  # noqa: SLF001
        # Four verified patch outcomes: three good, one bad.
        for seq, ok in enumerate([True, True, True, False], start=1):
            table.apply(_outcome(seq, "patch:src/memory", ok, weight=1.0))
        # One completion nobody checked. It says success and counts as
        # a quarter of one.
        table.apply(_outcome(5, "patch:src/memory", True, weight=config.unverified_sample_weight))
        # And the trial suite, 5 of 7, at half weight per case.
        table.record_eval("trials", passed=5, total=7, weight=config.eval_sample_weight)

        estimate = table.estimate("patch:src/memory", eval_suite=service._suite_for("patch:src/memory"),  # noqa: SLF001
                                  eval_weight=config.eval_sample_weight)
        # alpha = 1 (prior) + 3 verified + 0.25 unverified + (5 * 0.5) * 0.5 = 5.5
        # beta  = 1 (prior) + (5 - 3.25) failures + (7 - 2.5) * 0.5 = 5.0
        self.assertAlmostEqual(estimate["alpha"], 5.5, places=3)
        self.assertAlmostEqual(estimate["beta"], 5.0, places=3)
        self.assertAlmostEqual(estimate["mean"], 5.5 / 10.5, places=3)
        self.assertAlmostEqual(estimate["samples"], 12, places=3,
                               msg="five outcomes and seven eval cases")
        self.assertEqual(estimate["eval_suite"], "trials")


if __name__ == "__main__":
    unittest.main()
