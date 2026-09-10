"""A patch that changes code has to be checked against the WHOLE suite,
not whatever slice the model chose to run.

`IsolatedSuiteCheck` was meant to be this gate and never fires for a
real orchestration-driven patch task -- it needs subject fields only
Learning's unreachable `PatchPipeline` ever populates. Two real trials
found the consequence on 2026-09-08: `breaks-the-suite` and
`already-done` both committed a change after `run_tests` on a narrowed
target satisfied "run the tests" literally, unchecked against anything
it might have broken elsewhere.
"""

from __future__ import annotations

import unittest

from simorgh.verification.api import CheckContext, VerifyRequest
from simorgh.verification.checks import FullSuiteRanCheck
from simorgh.verification.config import VerificationConfig


def _step(tool: str, ok: bool = True, summary: str = "") -> dict:
    return {"tool": tool, "ok": ok, "phase": "act", "summary": summary}


def _request(kind: str, steps: list[dict], complete_log: bool = True) -> VerifyRequest:
    return VerifyRequest(
        verification_id="v1", task_id="t1", kind="task",
        subject={"kind": kind, "description": "d", "result": "done", "steps": steps,
                 "complete_log": complete_log},
    )


class TestTheObservedFailures(unittest.IsolatedAsyncioTestCase):
    async def _run(self, req: VerifyRequest):
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        return await FullSuiteRanCheck().run(req, ctx)

    async def test_a_narrowed_run_tests_target_does_not_pass(self) -> None:
        """The exact `breaks-the-suite`/`already-done` shape: a real
        run_tests call, real success, on one file rather than the
        whole tree."""
        req = _request("patch", [
            _step("apply_source_patch"),
            _step("run_tests", summary="[ran target='tests/simorgh/interface/test_parser.py']\n7 passed"),
            _step("git_commit"),
        ])
        self.assertTrue(FullSuiteRanCheck().applies(req))
        result = await self._run(req)
        self.assertEqual(result.status, "failed")
        self.assertIn("narrower target", result.detail)

    async def test_no_run_tests_call_at_all_does_not_pass(self) -> None:
        req = _request("patch", [_step("apply_source_patch"), _step("git_commit")])
        result = await self._run(req)
        self.assertEqual(result.status, "failed")
        self.assertIn("no run_tests call", result.detail)

    async def test_the_whole_suite_run_and_passed_is_accepted(self) -> None:
        for target_text in ("tests", "tests/"):
            with self.subTest(target=target_text):
                req = _request("patch", [
                    _step("apply_source_patch"),
                    _step("run_tests", summary=f"[ran target={target_text!r}]\n3070 passed"),
                    _step("git_commit"),
                ])
                self.assertEqual((await self._run(req)).status, "passed")

    async def test_a_failed_whole_suite_run_does_not_pass_even_though_it_ran(self) -> None:
        """`ok=False` on the step -- the suite ran and something broke.
        This check requires it to have PASSED, not merely run."""
        req = _request("patch", [
            _step("run_tests", ok=False, summary="[ran target='tests']\n1 failed, 3069 passed"),
        ])
        result = await self._run(req)
        self.assertEqual(result.status, "failed")

    async def test_a_whole_suite_target_that_collected_zero_tests_does_not_pass(self) -> None:
        """`RunTestsTool` reports `ok=True` on pytest exit code 5 ("no
        tests collected"), by design, so a brand-new file with no tests
        yet does not block a commit -- but that means a `run_tests`
        call whose target textually matches the whole suite can still
        report `ok=True` while zero tests actually ran (e.g. a
        self_patch that guts every test file). Live-probed 2026-09-09:
        `RunTestsTool` appends the exact "no tests cover this target
        yet -- nothing was run" string to its output in that case, and
        this must not be accepted as "the whole suite ran and passed."
        """
        req = _request("self_patch", [
            _step("apply_source_patch"),
            _step(
                "run_tests", ok=True,
                summary="[ran target='tests']\n\n"
                        "[no tests cover this target yet -- nothing was run]",
            ),
            _step("git_commit"),
        ])
        result = await self._run(req)
        self.assertEqual(result.status, "failed")

    async def test_a_run_tests_step_recorded_before_the_marker_existed_is_not_trusted(self) -> None:
        """No `[ran target=...]` prefix at all -- an old ledger record,
        or one truncated past the marker. Cannot tell what it ran, so
        this must not assume the best case."""
        req = _request("patch", [_step("run_tests", summary="7 passed in 0.02s")])
        result = await self._run(req)
        self.assertEqual(result.status, "failed")


class TestWhereItDoesNotApply(unittest.IsolatedAsyncioTestCase):
    def test_a_research_task_changes_nothing_to_break(self) -> None:
        self.assertFalse(FullSuiteRanCheck().applies(_request("research", [_step("read_file")])))

    def test_a_skill_has_its_own_sandbox_smoke_gate(self) -> None:
        self.assertFalse(FullSuiteRanCheck().applies(_request("skill", [_step("apply_skill")])))

    def test_no_steps_means_we_were_not_told(self) -> None:
        self.assertFalse(FullSuiteRanCheck().applies(_request("patch", [])))

    def test_an_incomplete_retry_log_is_not_judged_alone(self) -> None:
        """Same completeness gate as `DidAnythingCheck`: an attempt that
        only commits, with the whole suite already run by an earlier
        attempt, must not be failed for a log that is known partial."""
        req = _request("patch", [_step("git_commit")], complete_log=False)
        self.assertFalse(FullSuiteRanCheck().applies(req))


if __name__ == "__main__":
    unittest.main()


class TestAnHonestNoOpIsNotForcedToRunTheSuite(unittest.TestCase):
    """`DidAnythingCheck` already owns judging whether skipping the write
    was correct. Nothing was written, so there is nothing this check
    could have broken -- forcing a suite run here would fail a
    legitimate "already has what was asked for" answer."""

    def test_no_write_tool_at_all_does_not_apply(self) -> None:
        req = _request("patch", [_step("read_file")])
        self.assertFalse(FullSuiteRanCheck().applies(req))


class TestOnlyPythonChangesNeedThePythonSuite(unittest.IsolatedAsyncioTestCase):
    """Live-caught 2026-09-09, second 95120 trial: a task whose whole
    product was one `.html` page wrote it, ran `run_tests` on the page
    itself (a pytest usage error), and blocked here demanding a suite
    run that could not have said anything about an HTML file. The page
    was correct and finished; it was left uncommitted.

    A `.py` change still needs the suite -- that is the bug this check
    exists to catch, and it is unchanged.
    """

    def _req(self, written: list[str]) -> VerifyRequest:
        return VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={"kind": "patch", "description": "d", "result": "done", "complete_log": True,
                     "steps": [_step("apply_source_patch"), _step("git_commit")],
                     "written_paths": written, "subject": ""},
        )

    def test_an_html_only_task_is_not_asked_for_a_python_suite_run(self):
        self.assertFalse(FullSuiteRanCheck().applies(self._req(["docs/games/real_estate.html"])))

    def test_a_python_change_still_needs_it(self):
        self.assertTrue(FullSuiteRanCheck().applies(self._req(["simorgh/execution/tools.py"])))

    def test_a_mixed_change_still_needs_it(self):
        self.assertTrue(FullSuiteRanCheck().applies(self._req(["docs/x.html", "simorgh/y.py"])))

    def test_an_absent_written_paths_field_keeps_the_old_conservative_behaviour(self):
        req = VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={"kind": "patch", "description": "d", "result": "done", "complete_log": True,
                     "steps": [_step("apply_source_patch")]},
        )
        self.assertTrue(FullSuiteRanCheck().applies(req))


class TestScratchIsNotSource(unittest.IsolatedAsyncioTestCase):
    """Live-caught 2026-09-10. Sim was asked to build a throwaway script
    under `workspace/`, and did: a correct 33-line script and a real
    1200x960 PNG, confirmed on disk. It then spent its entire revision
    budget here, because a `.py` path made this check apply and the
    check wanted the whole 4,600-test suite run first.

    `workspace/` is gitignored, no test imports it, and review never
    sees it -- the suite has nothing to say about a file there. This is
    the same exemption the `.html` case above already earned, one
    directory over.
    """

    def _req(self, written: list[str]) -> VerifyRequest:
        return VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={"kind": "patch", "description": "d", "result": "done", "complete_log": True,
                     "steps": [_step("apply_source_patch"), _step("run_script")],
                     "written_paths": written, "subject": ""},
        )

    def test_a_scratch_script_is_not_asked_for_a_suite_run(self):
        self.assertFalse(FullSuiteRanCheck().applies(self._req(["workspace/wordfreq.py"])))

    def test_a_nested_scratch_path_counts_too(self):
        self.assertFalse(FullSuiteRanCheck().applies(self._req(["./workspace/tmp/a/b.py"])))

    def test_a_change_touching_real_source_as_well_still_needs_it(self):
        self.assertTrue(FullSuiteRanCheck().applies(
            self._req(["workspace/wordfreq.py", "simorgh/execution/tools.py"])))

    def test_a_directory_that_merely_starts_with_the_word_is_still_source(self):
        self.assertTrue(FullSuiteRanCheck().applies(self._req(["workspace-notes/thing.py"])))


class TestAFailedSuiteIsNotCalledANarrowedOne(unittest.IsolatedAsyncioTestCase):
    """The model ran exactly what it was told to run, the suite failed,
    and this check answered "run_tests was called on a narrower target
    than the whole suite, or never called at all" -- both halves untrue,
    with the same hint attached, so the only move left was to run it
    again. Observed 2026-09-10, three revisions in a row.
    """

    async def _run(self, req: VerifyRequest):
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        return await FullSuiteRanCheck().run(req, ctx)

    def _failed_suite(self):
        return _request("patch", [
            _step("apply_source_patch"),
            _step("run_tests", ok=False, summary="[ran target='tests']\n1 failed, 4657 passed"),
        ])

    async def test_the_detail_says_the_suite_failed(self):
        result = await self._run(self._failed_suite())
        self.assertEqual(result.status, "failed")
        self.assertIn("FAILED", result.detail)
        self.assertNotIn("narrower target", result.detail)
        self.assertNotIn("never called at all", result.detail)

    async def test_the_hint_sends_it_to_the_failures_not_back_to_the_same_command(self):
        result = await self._run(self._failed_suite())
        self.assertIn("Read the failures", result.feedback.revise_hint)

    async def test_the_evidence_records_which_story_it_told(self):
        result = await self._run(self._failed_suite())
        self.assertTrue(result.evidence["whole_suite_failed"])

    async def test_a_genuinely_narrowed_target_still_says_narrower(self):
        req = _request("patch", [
            _step("apply_source_patch"),
            _step("run_tests", ok=False, summary="[ran target='tests/simorgh/interface']\n1 failed"),
        ])
        result = await self._run(req)
        self.assertIn("narrower target", result.detail)
        self.assertFalse(result.evidence["whole_suite_failed"])
