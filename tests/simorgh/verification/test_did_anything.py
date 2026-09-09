"""A patch task that wrote nothing did not patch anything.

Observed in a real project run, 2026-09-08. Child task `6d7b8ed1cf6c`
was asked to add an `__all__` list to a file. All ten of its steps were
`read_file` and `search_code`; no write tool ever ran. It answered "The
patch is applied with __all__ placed right after the imports", and
verification PASSED it. `git status` was clean, the file untouched, and
the project's rollup counted it as one of the three steps done.

The semantic checklist cannot catch this: it judges the answer's prose,
and the prose says the work was done. That is what a mechanical check is
for -- it looks at what happened, costs nothing, and runs before anyone
is asked to form an opinion.
"""

from __future__ import annotations

import unittest

from simorgh.verification.api import CheckContext, VerifyRequest
from simorgh.verification.checks import DidAnythingCheck
from simorgh.verification.config import VerificationConfig


def _request(kind: str, tools: list[str], result: str = "done") -> VerifyRequest:
    return VerifyRequest(
        verification_id="v1", task_id="t1", kind="task",
        subject={
            "kind": kind, "description": "add an __all__ list", "result": result,
            "steps": [{"tool": t, "ok": True, "phase": "act", "summary": ""} for t in tools],
        },
    )


class TestCatchingWorkThatNeverHappened(unittest.IsolatedAsyncioTestCase):
    async def _run(self, req: VerifyRequest):
        # This check reads only the request; the context is inert for
        # it, and building a real one would say the opposite.
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        return await DidAnythingCheck().run(req, ctx)

    async def test_the_observed_failure(self) -> None:
        req = _request("patch", ["read_file", "search_code", "read_file"],
                       result="The patch is applied with __all__ placed right after the imports.")
        self.assertTrue(DidAnythingCheck().applies(req))
        result = await self._run(req)
        self.assertEqual(result.status, "failed")
        self.assertIn("no write tool ran", result.detail)

    async def test_a_session_that_wrote_passes(self) -> None:
        result = await self._run(_request("patch", ["read_file", "apply_source_patch", "git_commit"]))
        self.assertEqual(result.status, "passed")

    async def test_a_failed_write_still_counts_as_having_happened(self) -> None:
        """A write that ran and failed is a different problem, and an
        already visible one. This looks only for work that never
        started."""
        req = VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={"kind": "patch", "description": "d", "result": "r",
                     "steps": [{"tool": "apply_source_patch", "ok": False, "phase": "act", "summary": "refused"}]},
        )
        self.assertEqual((await self._run(req)).status, "passed")

    async def test_an_honest_no_change_answer_is_not_failed_here(self) -> None:
        """Deciding not to write can be exactly right -- a protected
        path, or a file that already had what was asked for. The answer
        says so, and judging that is the checklist's job, not this
        check's."""
        for answer in ("The file already contains the constant; no change was needed.",
                       "Guardian denied the edit: the path is protected.",
                       "I refused to make this change because it would break the suite."):
            with self.subTest(answer=answer):
                result = await self._run(_request("patch", ["read_file"], result=answer))
                self.assertEqual(result.status, "passed")


class TestWhereItDoesNotApply(unittest.IsolatedAsyncioTestCase):
    def test_a_research_task_produces_an_answer_not_a_change(self) -> None:
        self.assertFalse(DidAnythingCheck().applies(_request("research", ["read_file"])))

    def test_a_chat_turn_is_not_a_change(self) -> None:
        self.assertFalse(DidAnythingCheck().applies(_request("chat", [])))

    def test_no_steps_means_we_were_not_told_not_that_nothing_happened(self) -> None:
        req = VerifyRequest(verification_id="v1", task_id="t1", kind="task",
                            subject={"kind": "patch", "description": "d", "result": "r", "steps": []})
        self.assertFalse(DidAnythingCheck().applies(req))


class TestAnIncompleteRetryLogIsNotJudgedAlone(unittest.IsolatedAsyncioTestCase):
    """`session.py` sets `complete_log=False` on the verify subject for a
    retry that carried an uncommitted edit forward from an earlier
    attempt (`session.attempt <= 1 and not session.carried`) -- the same
    signal it already sends to `unsupported_claims`. That attempt's own
    `steps` are not the whole session: attempt 1 can apply the patch and
    run out of steps, and attempt 2 may legitimately show no write tool
    at all (e.g. it only re-runs the tests and reports, with the edit
    already committed by a later step or another attempt). This check
    must not fail that continuation on mechanical grounds it cannot
    support from a partial log.
    """

    async def _run(self, req: VerifyRequest):
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        return await DidAnythingCheck().run(req, ctx)

    def test_an_incomplete_log_with_no_write_tool_does_not_apply(self) -> None:
        req = VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={
                "kind": "patch", "description": "d", "result": "the tests pass", "complete_log": False,
                "steps": [{"tool": "run_tests", "ok": True, "phase": "act", "summary": ""}],
            },
        )
        self.assertFalse(DidAnythingCheck().applies(req))

    def test_a_complete_log_with_no_write_tool_still_applies(self) -> None:
        req = VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={
                "kind": "patch", "description": "d", "result": "the tests pass", "complete_log": True,
                "steps": [{"tool": "run_tests", "ok": True, "phase": "act", "summary": ""}],
            },
        )
        self.assertTrue(DidAnythingCheck().applies(req))

    def test_a_missing_complete_log_field_defaults_to_complete(self) -> None:
        """Older producers, and the tests above, never set the field at
        all -- that must keep meaning "this is the whole story", not
        silently start exempting every caller that has not been updated."""
        req = _request("patch", ["read_file", "search_code"])
        self.assertNotIn("complete_log", req.subject)
        self.assertTrue(DidAnythingCheck().applies(req))

    def test_an_incomplete_log_does_not_apply_even_when_this_attempt_did_write(self) -> None:
        """`applies()` gates on completeness alone, the same way
        `unsupported_claims` skips itself wholesale on `complete_log=False`
        rather than trying to partially trust an incomplete log. A write
        in this attempt's own steps is real evidence and would pass
        anyway (see `test_a_session_that_wrote_passes`); the point of the
        gate is the other direction -- no need to run a check whose only
        way to fail is unsound against a log we know is partial."""
        req = VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={
                "kind": "patch", "description": "d", "result": "done", "complete_log": False,
                "steps": [{"tool": "apply_source_patch", "ok": True, "phase": "act", "summary": ""}],
            },
        )
        self.assertFalse(DidAnythingCheck().applies(req))


class TestABookkeepingStepIsNotAnAction(unittest.IsolatedAsyncioTestCase):
    """A "verify" phase entry -- the record `session.py` writes for a
    rejected verdict, before a revision -- has no tool and is not an
    attempt at anything.

    Counting it as "we were told about a step" broke a real integration
    test: a scripted session that never calls a real tool at all picked
    up exactly one such bookkeeping entry between its first and second
    verification, and this check failed BOTH verdicts (the second
    should have passed) -- exhausting max_revisions and leaving a task
    the test expected to complete stuck blocked, a TimeoutError two
    layers away from the actual cause (2026-09-08).
    """

    async def _run(self, req: VerifyRequest):
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        return await DidAnythingCheck().run(req, ctx)

    async def test_a_bare_verify_bookkeeping_step_does_not_apply(self) -> None:
        req = VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={"kind": "patch", "description": "d", "result": "r",
                     "steps": [{"tool": None, "ok": False, "phase": "verify", "summary": "verification fail: ..."}]},
        )
        self.assertFalse(DidAnythingCheck().applies(req))

    async def test_a_real_action_step_still_applies_alongside_a_verify_step(self) -> None:
        req = VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={"kind": "patch", "description": "d", "result": "r", "steps": [
                {"tool": "read_file", "ok": True, "phase": "act", "summary": ""},
                {"tool": None, "ok": False, "phase": "verify", "summary": "verification fail: ..."},
            ]},
        )
        self.assertTrue(DidAnythingCheck().applies(req))
        self.assertEqual((await self._run(req)).status, "failed")


if __name__ == "__main__":
    unittest.main()
