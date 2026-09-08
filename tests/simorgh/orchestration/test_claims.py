"""A final answer must not claim work the step log does not show.

`_transcript_echo` catches a fabrication written in our own bracket
syntax, because that syntax came from a transcript stand-in we put
there ourselves. Plain prose walked straight past it. On 2026-09-08 a
session answered "I've added the docstring and committed the change as
a3f19c2" with no git_commit step in its log at all; the task was
recorded completed and the cleanup then deleted the real, tested patch.

The rules are deliberately asymmetric: a false negative costs nothing,
a false positive throws away real work. The negative cases below are
therefore the important half of this file.
"""

from __future__ import annotations

import unittest

from simorgh.orchestration.claims import unsupported_claims

PATCH_TOOLS = ("read_file", "apply_source_patch", "run_tests", "git_commit")


class _Step:
    def __init__(self, tool: str | None = None, ok: bool = True) -> None:
        self.tool, self.ok = tool, ok


class TestCatchingTheRealFabrication(unittest.TestCase):
    def test_the_answer_that_started_this(self) -> None:
        claims = unsupported_claims(
            "I've added the docstring and committed the change as a3f19c2.",
            [_Step("read_file"), _Step("search_code")], PATCH_TOOLS,
        )
        self.assertIn("says it committed, and no commit was made", claims)

    def test_claiming_a_commit_hash(self) -> None:
        claims = unsupported_claims("Done. Commit hash: 9b1e40f.", [_Step("read_file")], PATCH_TOOLS)
        self.assertTrue(claims)

    def test_claiming_the_tests_pass_without_running_them(self) -> None:
        claims = unsupported_claims(
            "I ran the tests and they all pass.", [_Step("apply_source_patch"), _Step("git_commit")], PATCH_TOOLS,
        )
        self.assertIn("says it ran the tests, and no test run happened", claims)

    def test_claiming_an_edit_that_was_never_applied(self) -> None:
        claims = unsupported_claims(
            "I updated simorgh/interface/api.py with a module docstring.",
            [_Step("read_file")], PATCH_TOOLS,
        )
        self.assertIn("says it changed a file, and no edit was applied", claims)


class TestNotPunishingHonestAnswers(unittest.TestCase):
    """Every one of these is a real answer. Rejecting any of them costs
    a whole attempt for nothing."""

    def test_a_commit_that_actually_happened(self) -> None:
        self.assertEqual(
            unsupported_claims("Committed it as a3f19c2.", [_Step("git_commit")], PATCH_TOOLS), [])

    def test_a_commit_that_was_attempted_and_refused(self) -> None:
        """A step that ran and failed still happened. This looks for
        invention; a refused commit is verification's problem, and
        punishing it twice costs an attempt."""
        self.assertEqual(
            unsupported_claims("I committed the change.", [_Step("git_commit", ok=False)], PATCH_TOOLS), [])

    def test_the_future_tense_is_not_a_claim(self) -> None:
        self.assertEqual(
            unsupported_claims("Next I will commit this and run the tests.", [_Step("read_file")], PATCH_TOOLS), [])

    def test_a_recommendation_is_not_a_claim(self) -> None:
        self.assertEqual(
            unsupported_claims("You should run the tests before committing.", [_Step("read_file")], PATCH_TOOLS), [])

    def test_a_research_session_reporting_what_it_read(self) -> None:
        """A research profile has no `run_tests` and no `git_commit`, so
        it cannot be accused of inventing either. "The tests pass" here
        describes the repository, not this session."""
        research_tools = ("read_file", "search_code", "web_fetch")
        self.assertEqual(
            unsupported_claims(
                "The suite passes on main, and the docs say the change was committed in v2.",
                [_Step("read_file")], research_tools,
            ), [])

    def test_an_empty_answer_claims_nothing(self) -> None:
        self.assertEqual(unsupported_claims("", [], PATCH_TOOLS), [])
        self.assertEqual(unsupported_claims("   ", [_Step("read_file")], PATCH_TOOLS), [])

    def test_describing_someone_elses_change(self) -> None:
        self.assertEqual(
            unsupported_claims(
                "The docstring was added by commit 4f21a in 2024, before this file was split.",
                [_Step("read_file")], PATCH_TOOLS,
            ), [])


if __name__ == "__main__":
    unittest.main()


class TestTheSessionRejectsAnUnsupportedCompletion(unittest.IsolatedAsyncioTestCase):
    """The check has to sit on the path a completion actually takes,
    not just exist as a function."""

    async def test_a_completion_claiming_an_uncommitted_commit_is_downgraded(self) -> None:
        from simorgh.orchestration import profiles
        from simorgh.orchestration.api import Outcome, Session
        from simorgh.orchestration.session import FABRICATED_REASON, SessionRunner
        from tests.simorgh.orchestration.harness import Harness

        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)

            async def _fake_run(_session, *, user_text=""):
                return Outcome("completed", result_summary="I've added it and committed the change as a3f19c2.")

            runner._run = _fake_run  # noqa: SLF001
            outcome = await runner.run(session, user_text="add a docstring")

        self.assertEqual(outcome.kind, "blocked")
        self.assertIn(FABRICATED_REASON, outcome.reason)
        self.assertTrue(any(not step.ok for step in session.steps),
                        "the rejection must be in the step log, not only in the reason")

    async def test_a_real_completion_still_completes(self) -> None:
        from simorgh.orchestration import profiles
        from simorgh.orchestration.api import Outcome, Session, Step
        from simorgh.orchestration.session import SessionRunner
        from tests.simorgh.orchestration.harness import Harness

        async with Harness() as h:
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)

            async def _fake_run(_session, *, user_text=""):
                _session.record(Step(1, "act", "applied the patch", tool="apply_source_patch", ok=True))
                _session.record(Step(2, "act", "committed", tool="git_commit", ok=True))
                return Outcome("completed", result_summary="I've added the docstring and committed it.")

            runner._run = _fake_run  # noqa: SLF001
            outcome = await runner.run(session, user_text="add a docstring")

        self.assertEqual(outcome.kind, "completed")
