"""A step budget bounds one attempt; the work spans attempts.

The creator, 2026-09-07: "why do we limit the tool budget? what if a
task requires long and multiple tool access, aren't we limiting sim?"
The cap was fine; the retry was the bug. A task blocked on "step budget
exhausted" came back with every earlier step counted against a budget
it had already spent, and no memory of what those steps did.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import Assembler
from simorgh.orchestration.resume import carried_note, restore_session
from simorgh.orchestration.worker import MAX_STEP_CAP, step_cap

from .harness import Harness, run


def _ev(type_: str, **payload) -> Event:
    return Event(stream="task:t1", type=type_, ts=0.0, trace_id="t1", causation_id=None, payload=payload)


def _attempt(steps: list[tuple[str, str, bool]], ended: str | None, reason: str = "") -> list[Event]:
    events = [_ev(topics.TASK_STARTED, task_id="t1", worker_id="w1")]
    for n, (tool, summary, ok) in enumerate(steps, start=1):
        events.append(_ev(topics.TASK_STEP, task_id="t1", step_no=n, phase="act", tool=tool, summary=summary, ok=ok))
    if ended == "blocked":
        events.append(_ev(topics.TASK_BLOCKED, task_id="t1", reason=reason))
        events.append(_ev("status_changed", status="blocked", note=reason))
    elif ended == "failed":
        events.append(_ev("status_changed", status="failed", note=reason))
    return events


class _Ledger:
    def __init__(self, events):
        self._events = events

    async def read(self, stream, **_):
        return list(self._events)


class RetryIsANewAttemptTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_finished_attempt_leaves_a_fresh_budget_and_a_memory(self):
        events = _attempt(
            [("search_code", "found it in simorgh/x.py", True), ("apply_source_patch", "wrote simorgh/x.py\n+NEW = 1", True)],
            "blocked", "step budget exhausted before the task was finished",
        )
        session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        session.budget.max_steps = 20
        spent = await restore_session(session, _Ledger(events))
        self.assertEqual(spent, 0)
        self.assertEqual(session.budget.steps_used, 0)
        self.assertEqual(session.steps, [])
        self.assertEqual(session.attempt, 2)
        self.assertIn("Attempt 1 ended blocked: step budget exhausted", session.carried)
        self.assertIn("- apply_source_patch: wrote simorgh/x.py\n+NEW = 1  ok", session.carried)

    async def test_a_crashed_attempt_is_continued_with_its_steps_counted(self):
        events = _attempt([("read_file", "x", True), ("read_file", "y", True)], ended=None)
        session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        spent = await restore_session(session, _Ledger(events))
        self.assertEqual(spent, 2)
        self.assertEqual(session.budget.steps_used, 2)
        self.assertEqual(len(session.steps), 2)
        self.assertEqual(session.carried, "")
        self.assertEqual(session.attempt, 1)

    async def test_a_crash_after_an_earlier_attempt_keeps_both_truths(self):
        events = _attempt([("read_file", "a", True)], "blocked", "step budget exhausted") + _attempt([("read_file", "b", True)], None)
        session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        spent = await restore_session(session, _Ledger(events))
        self.assertEqual(spent, 1)
        self.assertIn("Attempt 1 ended blocked", session.carried)
        self.assertNotIn("- read_file: b", session.carried)

    async def test_no_history_means_a_first_attempt(self):
        session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        self.assertEqual(await restore_session(session, _Ledger([])), 0)
        self.assertEqual(session.attempt, 1)
        self.assertEqual(session.carried, "")

    def test_the_memory_keeps_the_latest_attempt_whole_when_long(self):
        attempts = [
            {"steps": [{"tool": "read_file", "summary": "x" * 300, "ok": True}] * 40, "ended": "blocked", "reason": "old"},
            {"steps": [{"tool": "run_tests", "summary": "3 passed", "ok": True}], "ended": "blocked", "reason": "recent"},
        ]
        note = carried_note(attempts)
        self.assertLessEqual(len(note), 6000)
        self.assertIn("Attempt 2 ended blocked: recent", note)
        self.assertIn("- run_tests: 3 passed  ok", note)
        self.assertTrue(note.startswith("(earlier attempts omitted)"))


class TheModelIsToldTestCase(unittest.TestCase):
    @run
    async def test_the_carried_note_is_a_turn_after_the_task(self):
        async with Harness() as h:
            assembler = Assembler(h.client("orchestration"), timeout_s=0.05)
            session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH,
                              user_text="add NEW", carried="Attempt 1 ended blocked\n- read_file: x  ok", attempt=2)
            messages = await assembler.assemble(session, "patch")
            users = [m["content"] for m in messages if m["role"] == "user"]
            self.assertEqual(users[0], "add NEW")
            self.assertIn("This is attempt 2 at the task.", users[1])
            self.assertIn("- read_file: x  ok", users[1])
            self.assertIn("left uncommitted were discarded", users[1])

    @run
    async def test_a_first_attempt_gets_no_such_turn(self):
        async with Harness() as h:
            assembler = Assembler(h.client("orchestration"), timeout_s=0.05)
            session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH, user_text="add NEW")
            messages = await assembler.assemble(session, "patch")
            self.assertEqual([m["content"] for m in messages if m["role"] == "user"], ["add NEW"])


class PerTaskStepCapTestCase(unittest.TestCase):
    def test_a_task_may_set_its_own_cap(self):
        self.assertEqual(step_cap(40, 20), 40)
        self.assertEqual(step_cap("8", 20), 8)

    def test_no_cap_means_the_profile(self):
        self.assertEqual(step_cap(None, 20), 20)
        self.assertEqual(step_cap(0, 20), 20)
        self.assertEqual(step_cap("lots", 20), 20)

    def test_the_cap_is_bounded(self):
        self.assertEqual(step_cap(10_000, 20), MAX_STEP_CAP)


if __name__ == "__main__":
    unittest.main()


class KeptEditsTestCase(unittest.IsolatedAsyncioTestCase):
    """An attempt that ran out of steps leaves its uncommitted edits in
    the tree for the next one (bounded), and the next one inherits them
    so its own end can still clean up."""

    async def test_the_next_attempt_inherits_the_kept_paths(self):
        from simorgh.orchestration.session import EDITS_KEPT

        events = _attempt([("apply_source_patch", "wrote simorgh/x.py", True)], ended=None)
        events.insert(2, _ev(EDITS_KEPT, task_id="t1", paths=["simorgh/x.py"], created=[]))
        events.append(_ev(topics.TASK_BLOCKED, task_id="t1", reason="step budget exhausted before the task was finished"))
        session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        await restore_session(session, _Ledger(events))
        self.assertEqual(session.uncommitted, {"simorgh/x.py"})
        self.assertEqual(session.created, set())
        self.assertIn("Left in the tree, uncommitted, for the next attempt: simorgh/x.py", session.carried)

    def test_only_a_continuation_below_the_limit_keeps(self):
        from simorgh.orchestration.api import Outcome
        from simorgh.orchestration.session import KEEP_EDITS_UNTIL_ATTEMPT, SessionRunner

        def session(attempt):
            s = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
            s.attempt = attempt
            return s

        exhausted = Outcome("blocked", reason="step budget exhausted before the task was finished")
        self.assertTrue(SessionRunner._continues(session(1), exhausted))
        self.assertTrue(SessionRunner._continues(session(KEEP_EDITS_UNTIL_ATTEMPT - 1), exhausted))
        self.assertFalse(SessionRunner._continues(session(KEEP_EDITS_UNTIL_ATTEMPT), exhausted))
        self.assertFalse(SessionRunner._continues(session(1), Outcome("blocked", reason="verification failed after max revisions")))
        self.assertFalse(SessionRunner._continues(session(1), Outcome("completed", result_summary="done")))

    @run
    async def test_the_model_is_told_the_edits_are_still_there(self):
        async with Harness() as h:
            assembler = Assembler(h.client("orchestration"), timeout_s=0.05)
            session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH,
                              user_text="add NEW", carried="Attempt 1 ended blocked", attempt=2)
            session.uncommitted.add("simorgh/x.py")
            messages = await assembler.assemble(session, "patch")
            note = [m["content"] for m in messages if m["role"] == "user"][1]
            self.assertIn("simorgh/x.py are STILL IN THE TREE", note)
            self.assertNotIn("were discarded", note)


class LastStepMayStillFinishTestCase(unittest.TestCase):
    """Refusing a git_commit on the last step threw away the whole
    attempt: an applied, tested change was reported as "step budget
    exhausted" and then discarded. A finishing tool ends the work."""

    @run
    async def test_a_commit_asked_for_on_the_last_step_is_honoured(self):
        from .fakes import FakeCognition, FakeGuardianExecution

        async with Harness() as h:
            gx = FakeGuardianExecution(h.client("guardian"))
            await gx.start()
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "git_commit", "args": {"path": "simorgh/x.py", "message": "add it"}}]},
            ])
            await cognition.start()
            try:
                from simorgh.orchestration.session import SessionRunner

                session = Session(task_id="t-last", kind="patch", mode="execute", profile=profiles.PATCH)
                session.budget.max_steps = 1
                session.uncommitted.add("simorgh/x.py")
                runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, verify_timeout_s=0.05)
                outcome = await runner.run(session, user_text="add a constant")
                self.assertEqual(outcome.kind, "completed", outcome.reason)
                self.assertIn("Committed the change", outcome.result_summary)
                self.assertEqual([s.tool for s in session.steps if s.tool], ["git_commit"])
            finally:
                await cognition.stop()
                await gx.stop()

    @run
    async def test_an_ordinary_tool_on_the_last_step_still_blocks(self):
        from .fakes import FakeCognition, FakeGuardianExecution

        async with Harness() as h:
            gx = FakeGuardianExecution(h.client("guardian"))
            await gx.start()
            cognition = FakeCognition(h.client("cognition"), script=[
                {"tool_calls": [{"tool": "read_file", "args": {"path": "simorgh/x.py"}}]},
            ])
            await cognition.start()
            try:
                from simorgh.orchestration.session import SessionRunner

                session = Session(task_id="t-last2", kind="patch", mode="execute", profile=profiles.PATCH)
                session.budget.max_steps = 1
                session.uncommitted.add("simorgh/x.py")
                runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, verify_timeout_s=0.05)
                outcome = await runner.run(session, user_text="add a constant")
                self.assertEqual(outcome.kind, "blocked")
                self.assertIn("step budget exhausted", outcome.reason)
            finally:
                await cognition.stop()
                await gx.stop()
