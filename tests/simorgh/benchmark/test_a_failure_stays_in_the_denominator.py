"""28003d9 made the pytest parser take the worst outcome. The Django
parser kept the older rule, and it hides a failure a different way.

`parse_django` records AMBIGUOUS whenever two progress lines under one
key disagree -- right when one says `ok` and the other `FAIL`, because a
passing namesake must never certify a failing test. But `FAIL` and
`ERROR` also "disagree" as strings, and they agree about the only thing
that matters. The key went to AMBIGUOUS, `judge` returned
`skipped=True`, and `api.py:165` drops a skipped case out of
`attempted` entirely -- so a run in which EVERY reading of the name was
a failure left the denominator, and the resolve rate went UP because the
evaluator saw more failures. Reproduced 2026-09-10.

The second case here is smaller and reads wrong rather than scores
wrong: a row naming one test in both `FAIL_TO_PASS` and `PASS_TO_PASS`
judged it twice.
"""

from __future__ import annotations

import json
import unittest

from simorgh.benchmark import swebench


class TwoReadingsThatBothSayFailedTestCase(unittest.TestCase):
    LOG = ("test_a (app.tests.A)\nTests the shared behaviour. ... FAIL\n"
           "test_b (app.tests.B)\nTests the shared behaviour. ... ERROR\n"
           "======\nFAIL: test_a (app.tests.A)\nERROR: test_b (app.tests.B)\n")

    def test_the_key_is_a_failure_not_an_unknown(self):
        self.assertIn(swebench.parse_django(self.LOG)["Tests the shared behaviour."],
                      swebench._BAD)

    def test_the_case_is_counted_as_a_failure_not_skipped(self):
        verdict = swebench.judge(self.LOG, {
            "log_parser": "parse_log_django",
            "FAIL_TO_PASS": json.dumps(["Tests the shared behaviour."])})
        self.assertFalse(verdict.resolved)
        self.assertFalse(verdict.skipped, "a case whose every reading failed must stay in "
                                          "`attempted` -- api.py:165 drops skipped cases")
        self.assertEqual(verdict.failed, ("Tests the shared behaviour.",))

    def test_a_passing_namesake_is_still_ambiguous(self):
        """The rule this narrows must keep doing its own job."""
        log = ("test_a (app.tests.A)\nTests the shared behaviour. ... FAIL\n"
               "test_b (app.tests.B)\nTests the shared behaviour. ... ok\n")
        self.assertEqual(swebench.parse_django(log)["Tests the shared behaviour."],
                         swebench.AMBIGUOUS)


class ANameInBothListsIsOneTestTestCase(unittest.TestCase):
    INSTANCE = {"log_parser": "parse_log_pytest",
                "FAIL_TO_PASS": json.dumps(["tests/t.py::test_a"]),
                "PASS_TO_PASS": json.dumps(["tests/t.py::test_a"])}

    def test_one_failing_test_is_reported_once(self):
        verdict = swebench.judge("FAILED tests/t.py::test_a - boom\n", self.INSTANCE)
        self.assertFalse(verdict.resolved)
        self.assertEqual(verdict.failed, ("tests/t.py::test_a",))
        self.assertIn("1 test(s) still failing", verdict.detail)

    def test_a_fail_to_pass_test_is_not_called_a_regression(self):
        verdict = swebench.judge("FAILED tests/t.py::test_a - boom\n", self.INSTANCE)
        self.assertNotIn("passed before the patch", verdict.detail)

    def test_a_real_regression_is_still_named_as_one(self):
        verdict = swebench.judge(
            "PASSED tests/t.py::test_a\nFAILED tests/t.py::test_b - boom\n",
            {"log_parser": "parse_log_pytest",
             "FAIL_TO_PASS": json.dumps(["tests/t.py::test_a"]),
             "PASS_TO_PASS": json.dumps(["tests/t.py::test_b"])})
        self.assertIn("1 that passed before the patch", verdict.detail)


class WorstStillWinsForPytestTestCase(unittest.TestCase):
    """Re-checked, not assumed: three results with the worst in the
    middle, and the same test in both of pytest's line shapes."""

    def test_worst_in_the_middle(self):
        log = ("PASSED tests/t.py::test_a\nFAILED tests/t.py::test_a - boom\n"
               "PASSED tests/t.py::test_a\n")
        self.assertEqual(swebench.parse_pytest(log), {"tests/t.py::test_a": "FAILED"})

    def test_both_line_shapes_either_order(self):
        self.assertEqual(swebench.parse_pytest(
            "tests/t.py::test_a PASSED\nFAILED tests/t.py::test_a - boom\n"),
            {"tests/t.py::test_a": "FAILED"})
        self.assertEqual(swebench.parse_pytest(
            "FAILED tests/t.py::test_a - boom\ntests/t.py::test_a PASSED\n"),
            {"tests/t.py::test_a": "FAILED"})


if __name__ == "__main__":
    unittest.main()
