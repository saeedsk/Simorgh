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
