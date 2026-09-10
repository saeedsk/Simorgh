"""The SWE-bench evaluator: what it reads, and what it refuses to guess.

The log fixtures here are cut from real runs on 2026-09-10 -- astropy
under pytest, django under its own runner -- because the whole risk in
this module is reading a shape nobody has actually seen.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from simorgh.benchmark import swebench

# Django prints the test id and the verdict on ONE line only when the
# test has no docstring. With a docstring, the id is on its own line and
# the label in front of the verdict is the docstring -- which is the
# name the dataset then uses. Both forms are here, in the order the
# runner prints them, with the failure summary that follows.
DJANGO_LOG = """
Testing against Django installed in '/testbed/django'
test_custom_fields (inspectdb.tests.InspectDBTestCase) ... FAIL
test_digits_column_name_introspection (inspectdb.tests.InspectDBTestCase)
Introspection of column names consist/start with digits (#16536/#17676) ... ok
test_field_types (inspectdb.tests.InspectDBTestCase)
Test introspection of various Django field types ... ok
test_introspection_errors (inspectdb.tests.InspectDBTestCase) ... ok
test_unsupported (inspectdb.tests.InspectDBTestCase) ... skipped 'no sqlite'
======================================================================
FAIL: test_custom_fields (inspectdb.tests.InspectDBTestCase)
----------------------------------------------------------------------
FAILED (failures=1)
"""

PYTEST_LOG = """
PASSED astropy/modeling/tests/test_separable.py::test_separable[compound_model6-result6]
FAILED astropy/modeling/tests/test_separable.py::test_separable[compound_model9-result9] - assert False
"""


class DjangoParserTestCase(unittest.TestCase):
    def test_both_shapes_django_prints(self) -> None:
        results = swebench.parse_django(DJANGO_LOG)
        self.assertEqual(results["test_custom_fields (inspectdb.tests.InspectDBTestCase)"], "FAIL")
        self.assertEqual(results["test_introspection_errors (inspectdb.tests.InspectDBTestCase)"],
                         "PASSED")

    def test_a_documented_test_is_keyed_by_its_docstring(self) -> None:
        """Not by its id -- the dataset names it the way the runner
        printed it, and reading the id instead loses every documented
        test, which in Django's suite is most of them."""
        results = swebench.parse_django(DJANGO_LOG)
        self.assertEqual(
            results["Introspection of column names consist/start with digits (#16536/#17676)"],
            "PASSED")
        self.assertEqual(results["Test introspection of various Django field types"], "PASSED")

    def test_a_skip_is_not_a_pass(self) -> None:
        results = swebench.parse_django(DJANGO_LOG)
        self.assertEqual(results["test_unsupported (inspectdb.tests.InspectDBTestCase)"], "SKIPPED")


class PytestParserTestCase(unittest.TestCase):
    def test_status_first_lines(self) -> None:
        results = swebench.parse_pytest(PYTEST_LOG)
        key = "astropy/modeling/tests/test_separable.py::test_separable[compound_model6-result6]"
        self.assertEqual(results[key], "PASSED")
        self.assertEqual(len(results), 2)

    def test_an_unknown_parser_is_refused_not_guessed(self) -> None:
        results, problem = swebench.parse_log(PYTEST_LOG, "parse_log_pylint")
        self.assertEqual(results, {})
        self.assertIn("parse_log_pylint", problem)


class JudgeTestCase(unittest.TestCase):
    instance = {
        "log_parser": "parse_log_pytest",
        "FAIL_TO_PASS": json.dumps(
            ["astropy/modeling/tests/test_separable.py::test_separable[compound_model6-result6]"]),
        "PASS_TO_PASS": json.dumps([]),
    }

    def test_resolved_when_the_named_test_passes(self) -> None:
        verdict = swebench.judge(PYTEST_LOG, self.instance)
        self.assertTrue(verdict.resolved)
        self.assertFalse(verdict.skipped)

    def test_unresolved_names_what_still_fails(self) -> None:
        instance = dict(self.instance, FAIL_TO_PASS=json.dumps([
            "astropy/modeling/tests/test_separable.py::test_separable[compound_model9-result9]"]))
        verdict = swebench.judge(PYTEST_LOG, instance)
        self.assertFalse(verdict.resolved)
        self.assertFalse(verdict.skipped)
        self.assertIn("compound_model9", verdict.failed[0])

    def test_a_named_test_the_log_never_mentions_is_unmeasured(self) -> None:
        """Not a failure. The run did not do what we think it did, and
        blaming the model for our blind spot would be a wrong score."""
        instance = dict(self.instance, PASS_TO_PASS=json.dumps(["tests/test_nothing.py::test_gone"]))
        verdict = swebench.judge(PYTEST_LOG, instance)
        self.assertFalse(verdict.resolved)
        self.assertTrue(verdict.skipped)
        self.assertEqual(verdict.missing, ("tests/test_nothing.py::test_gone",))

    def test_an_empty_log_is_unmeasured(self) -> None:
        verdict = swebench.judge("Traceback: ImportError\n", self.instance)
        self.assertTrue(verdict.skipped)


class TestOutputTestCase(unittest.TestCase):
    def test_only_the_test_run_is_read(self) -> None:
        """The eval script prints `git show` first, and a diff can
        contain lines that look exactly like test results."""
        log = ("+PASSED tests/test_thing.py::test_from_the_diff\n"
               ">>>>> Start Test Output\n"
               "PASSED tests/test_thing.py::test_real\n"
               ">>>>> End Test Output\n")
        cut = swebench.test_output(log)
        self.assertIn("test_real", cut)
        self.assertNotIn("test_from_the_diff", cut)

    def test_a_log_without_markers_is_read_whole(self) -> None:
        self.assertEqual(swebench.test_output(PYTEST_LOG), PYTEST_LOG)


class EvaluateTestCase(unittest.TestCase):
    instance = {"image": "img", "eval_script": "true", "log_parser": "parse_log_pytest"}

    def test_no_patch_is_a_wrong_answer_not_an_unmeasured_one(self) -> None:
        with mock.patch.object(swebench, "docker_path", return_value="/usr/bin/docker"):
            verdict, log = swebench.evaluate(self.instance, "   \n")
        self.assertFalse(verdict.resolved)
        self.assertFalse(verdict.skipped)
        self.assertEqual(log, "")
        self.assertIn("no patch", verdict.detail)

    def test_without_docker_the_case_is_unmeasured(self) -> None:
        with mock.patch.object(swebench, "docker_path", return_value=""):
            verdict, _ = swebench.evaluate(self.instance, "diff --git a/x b/x\n")
        self.assertTrue(verdict.skipped)

    def test_a_patch_that_does_not_apply_is_a_wrong_answer(self) -> None:
        with mock.patch.object(swebench, "docker_path", return_value="/usr/bin/docker"), \
                mock.patch.object(swebench, "_run", return_value=(90, "SIMORGH_PATCH_FAILED\n")):
            verdict, _ = swebench.evaluate(self.instance, "diff --git a/x b/x\n")
        self.assertFalse(verdict.resolved)
        self.assertFalse(verdict.skipped)
        self.assertIn("did not apply", verdict.detail)

    def test_a_timeout_is_unmeasured(self) -> None:
        with mock.patch.object(swebench, "docker_path", return_value="/usr/bin/docker"), \
                mock.patch.object(swebench, "_run", return_value=(124, "timed out after 60s")):
            verdict, _ = swebench.evaluate(self.instance, "diff --git a/x b/x\n", timeout=60)
        self.assertTrue(verdict.skipped)


class DiffTestCase(unittest.TestCase):
    def test_test_edits_are_dropped_from_the_patch(self) -> None:
        """SWE-bench restores the test files before running, so a test
        edit changes nothing -- dropping it here makes that visible in
        the patch we record rather than silent in the container."""
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "tests").mkdir()
            (root / "pkg.py").write_text("value = 1\n")
            (root / "tests" / "test_pkg.py").write_text("assert True\n")
            for args in (["init", "-q"], ["add", "-A"],
                         ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"]):
                subprocess.run(["git", "-C", str(root), *args], check=True,
                               capture_output=True)
            (root / "pkg.py").write_text("value = 2\n")
            (root / "tests" / "test_pkg.py").write_text("assert False\n")
            patch, problem = swebench.diff_of(root)
        self.assertEqual(problem, "")
        self.assertIn("pkg.py", patch)
        self.assertNotIn("test_pkg.py", patch)


if __name__ == "__main__":
    unittest.main()


class RunnerSwebenchCaseTestCase(unittest.IsolatedAsyncioTestCase):
    def _case(self, **fields):
        from simorgh.benchmark.api import Case
        base = dict(id="astropy__astropy-12907", question="separability is wrong",
                    answer="diff --git a/gold b/gold", mode="swebench", suite="swebench-verified",
                    data=json.dumps({"image": "img", "eval_script": "true",
                                     "log_parser": "parse_log_pytest"}))
        base.update(fields)
        return Case(**base)

    def _runner(self):
        from simorgh.benchmark.runner import Runner
        return Runner(mock.MagicMock(), repo_root=Path("/tmp/does-not-matter"))

    async def _run(self, case, *, verdict, ask=("done", 4, 0.02, ""), patch="diff --git a/x b/x\n",
                   materialize="", available=(True, "")):
        runner = self._runner()
        with mock.patch.object(swebench, "available", return_value=available), \
                mock.patch.object(swebench, "materialize", return_value=materialize), \
                mock.patch.object(swebench, "diff_of", return_value=(patch, "")), \
                mock.patch.object(swebench, "evaluate", return_value=(verdict, "log")), \
                mock.patch("shutil.rmtree"), \
                mock.patch.object(type(runner), "_ask", new=mock.AsyncMock(return_value=ask)):
            return await runner.run_case(case)

    async def test_a_case_is_correct_when_the_tests_say_so(self):
        result = await self._run(self._case(), verdict=swebench.Verdict(True, "all tests pass"))
        self.assertTrue(result.correct)
        self.assertFalse(result.skipped)
        self.assertEqual(result.cost_usd, 0.02)

    async def test_the_reply_text_is_never_what_is_scored(self):
        """The system can say anything it likes; the tests decide."""
        result = await self._run(self._case(), ask=("I fixed it, definitely", 3, 0.0, ""),
                                 verdict=swebench.Verdict(False, "1 test(s) still failing"))
        self.assertFalse(result.correct)
        self.assertIn("still failing", result.error)

    async def test_without_docker_the_case_is_skipped_not_failed(self):
        result = await self._run(self._case(), verdict=swebench.Verdict(True, ""),
                                 available=(False, "the Docker daemon is not running"))
        self.assertTrue(result.skipped)
        self.assertIn("Docker", result.error)

    async def test_a_checkout_that_cannot_be_made_is_skipped(self):
        result = await self._run(self._case(), verdict=swebench.Verdict(True, ""),
                                 materialize="could not copy the checkout out of img")
        self.assertTrue(result.skipped)
        self.assertIn("checkout", result.error)

    async def test_a_case_from_an_old_cache_says_to_reload_the_suite(self):
        result = await self._run(self._case(data=""), verdict=swebench.Verdict(True, ""))
        self.assertTrue(result.skipped)
        self.assertIn("benchmark load", result.error)

    async def test_the_prompt_names_the_checkout_and_forbids_editing_tests(self):
        prompt = self._runner().patch_prompt(self._case(), "workspace/swebench/astropy__astropy-12907")
        self.assertIn("workspace/swebench/astropy__astropy-12907", prompt)
        self.assertIn("separability is wrong", prompt)
        self.assertIn("Do not edit or add tests", prompt)


class NothingCheckedIsNotAPassTestCase(unittest.TestCase):
    """Four ways this evaluator could report a score it had not earned,
    all found by an observer attacking it on the day it was written
    (2026-09-10). A wrong score is worse than no score, and every one of
    these produced a wrong score silently.
    """

    def test_a_row_naming_no_tests_is_refused_not_resolved(self):
        """`_names` returns () for a FAIL_TO_PASS that is missing, empty
        or in a shape it cannot decode, and the success return then said
        "all 0 fail-to-pass and 0 pass-to-pass test(s) pass" -- a case
        certified without a single check."""
        for row in ({"FAIL_TO_PASS": "[]"}, {"FAIL_TO_PASS": "not json"}, {}):
            verdict = swebench.judge(PYTEST_LOG, dict(row, log_parser="parse_log_pytest"))
            self.assertFalse(verdict.resolved)
            self.assertTrue(verdict.skipped)
            self.assertIn("no fail-to-pass tests", verdict.detail)

    def test_a_name_two_tests_share_cannot_certify_either(self):
        """Django names a documented test by its docstring, and one
        docstring can belong to two classes. The last line written won,
        so a passing namesake could mark a failing test as passed."""
        log = ("test_zzz_broken (app.tests.A)\nTests the shared behaviour. ... FAIL\n"
               "test_aaa_fine (app.tests.B)\nTests the shared behaviour. ... ok\n")
        self.assertEqual(swebench.parse_django(log)["Tests the shared behaviour."],
                         swebench.AMBIGUOUS)
        verdict = swebench.judge(log, {"log_parser": "parse_log_django",
                                       "FAIL_TO_PASS": json.dumps(["Tests the shared behaviour."])})
        self.assertFalse(verdict.resolved)
        self.assertTrue(verdict.skipped)

    def test_a_skipped_test_is_not_a_test_the_patch_broke(self):
        log = "PASSED tests/a.py::t1\nSKIPPED tests/a.py::t2\n"
        verdict = swebench.judge(log, {"log_parser": "parse_log_pytest",
                                       "FAIL_TO_PASS": json.dumps(["tests/a.py::t1"]),
                                       "PASS_TO_PASS": json.dumps(["tests/a.py::t2"])})
        self.assertFalse(verdict.resolved)
        self.assertTrue(verdict.skipped, "a test that never ran did not fail")
        self.assertEqual(verdict.failed, ())
        self.assertEqual(verdict.unmeasured, ("tests/a.py::t2",))

    def test_a_real_failure_still_outranks_an_unmeasured_one(self):
        """The patch broke something. That is true whatever else could
        not be read, and must not be softened into "unmeasured"."""
        log = "FAILED tests/a.py::t1 - AssertionError\nSKIPPED tests/a.py::t2\n"
        verdict = swebench.judge(log, {"log_parser": "parse_log_pytest",
                                       "FAIL_TO_PASS": json.dumps(["tests/a.py::t1"]),
                                       "PASS_TO_PASS": json.dumps(["tests/a.py::t2"])})
        self.assertFalse(verdict.skipped)
        self.assertIn("still failing", verdict.detail)


class PytestIdsSurviveTheirOwnPunctuationTestCase(unittest.TestCase):
    """A parametrised id can contain spaces and dashes inside its
    brackets, and pytest appends `- <message>` to a failure line.
    Cutting at the first " - " turned `test_param[x - y]` into
    `test_param[x`, and `judge` then reported the dataset's test "never
    appeared in the log" and threw away a run that had measured it
    (observer, 2026-09-10)."""

    def test_a_parametrised_id_containing_a_dash_is_kept_whole(self):
        results = swebench.parse_pytest("PASSED tests/t.py::test_param[x - y]\n")
        self.assertIn("tests/t.py::test_param[x - y]", results)

    def test_a_failure_message_is_still_stripped(self):
        results = swebench.parse_pytest("FAILED tests/t.py::test_other[a-b] - AssertionError: no\n")
        self.assertEqual(results, {"tests/t.py::test_other[a-b]": "FAILED"})

    def test_a_skip_tally_is_not_a_test(self):
        """`SKIPPED [1] tests/t.py:9: needs network` names a file and a
        line, and was read as a test called "[1] tests/t.py:9: ..."."""
        results = swebench.parse_pytest("SKIPPED [1] tests/t.py:9: needs network\n")
        self.assertEqual(results, {})

    def test_a_status_first_line_is_not_glued_to_the_next_line(self):
        """The trailing-status pattern used `\\s+`, which matches a
        newline, so two status-first lines matched as one id ending in
        the second line's verdict."""
        results = swebench.parse_pytest(
            "PASSED tests/t.py::test_one[a b]\nFAILED tests/t.py::test_two - boom\n")
        self.assertEqual(results, {"tests/t.py::test_one[a b]": "PASSED",
                                   "tests/t.py::test_two": "FAILED"})


class OneLogSayingTwoThingsTakesTheWorseTestCase(unittest.TestCase):
    """A later PASSED overwrote an earlier FAILED, and the case then
    resolved on a test the log had recorded as failing.

    A rerun plugin, a flaky retry, or the same result printed in both
    line shapes all produce this. Observed 2026-09-10, the day after
    this evaluator was written: `FAILED tests/a.py::t1` followed by
    `PASSED tests/a.py::t1` gave `resolved=True, "all 1 fail-to-pass
    ... pass"`. If a run ever said a required test failed, it failed.
    """

    def _judge(self, log: str):
        return swebench.judge(log, {"log_parser": "parse_log_pytest",
                                    "FAIL_TO_PASS": json.dumps(["tests/a.py::t1"]),
                                    "PASS_TO_PASS": "[]"})

    def test_a_failure_then_a_pass_is_a_failure(self):
        self.assertFalse(self._judge("FAILED tests/a.py::t1 - boom\nPASSED tests/a.py::t1\n").resolved)

    def test_a_pass_then_a_failure_is_a_failure(self):
        self.assertFalse(self._judge("PASSED tests/a.py::t1\nFAILED tests/a.py::t1 - boom\n").resolved)

    def test_the_two_line_shapes_cannot_launder_each_other(self):
        self.assertFalse(self._judge("PASSED tests/a.py::t1\ntests/a.py::t1 FAILED\n").resolved)

    def test_a_clean_pass_is_still_a_pass(self):
        self.assertTrue(self._judge("PASSED tests/a.py::t1\n").resolved)

    def test_a_skip_does_not_hide_a_failure(self):
        verdict = self._judge("FAILED tests/a.py::t1 - boom\nSKIPPED tests/a.py::t1\n")
        self.assertFalse(verdict.resolved)
        self.assertEqual(verdict.failed, ("tests/a.py::t1",))
