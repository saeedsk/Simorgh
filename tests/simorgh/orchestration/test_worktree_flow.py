"""A code task works in its own worktree and lands on main
(`session.py::_open_worktree`/`_land`/`_close_worktree`): the runner
asks Execution for the tree before the first step, and after
verification asks it to land; a refusal keeps the tree for the next
attempt, a dead task's tree is closed."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import LANDING_REASON, SessionRunner
from simorgh.orchestration.tools import forget_registered, note_registered

from .fakes import FakeCognition, FakeVerification
from .harness import Harness, run


class WorktreeExecution:
    """Guardian+Execution with the three worktree tools, answering
    `worktree_open` with a real directory and `worktree_land` however
    the test says."""

    def __init__(self, bus, path: Path, *, land_ok: bool = True, open_ok: bool = True) -> None:
        self._bus = bus
        self._path = path
        self._land_ok = land_ok
        self._open_ok = open_ok
        self.proposals: list[Message] = []
        self._sub = None

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def stop(self) -> None:
        if self._sub:
            await self._sub.unsubscribe()

    @property
    def tools(self) -> list[str]:
        return [m.payload["tool"] for m in self.proposals]

    async def _on(self, message: Message) -> None:
        self.proposals.append(message)
        tool = message.payload["tool"]
        args = message.payload.get("args") or {}
        payload = {"action_id": message.payload["action_id"], "ok": True, "output_ref": "",
                   "stdout_preview": f"ran {tool}", "duration_ms": 1, "side_effects": []}
        if tool == "worktree_open":
            if self._open_ok:
                payload["stdout_preview"] = f"{self._path}\nabc123def\ncreated sim/task-x"
            else:
                payload.update(ok=False, stdout_preview="", error="could not open a worktree: no git")
        elif tool == "worktree_land":
            if self._land_ok:
                payload["stdout_preview"] = "landed 1 commit(s) on main: 1111111 -> 2222222"
                payload["side_effects"] = ["worktree_land:2222222"]
            else:
                payload.update(ok=False, stdout_preview="FAILED tests/x.py::test_a",
                               error="refused: the whole suite is red on the rebased tree (exit_code=1, 40s) -- fix it and commit again")
        elif tool == "apply_source_patch":
            payload["side_effects"] = [f"file_write:{args.get('subject')}", f"file_create:{args.get('subject')}"]
        elif tool == "git_commit":
            payload["side_effects"] = [f"git_commit:{args.get('path')}"]
        await self._bus.publish(message.caused(topics.ACTION_RESULT, payload, source="execution"))


_SCRIPT = [
    {"tool_calls": [{"tool": "apply_source_patch", "args": {"subject": "simorgh/new.py", "code": "X = 1\n"}}]},
    {"tool_calls": [{"tool": "git_commit", "args": {"path": "simorgh/new.py", "message": "add X"}}]},
    {"text": "Added simorgh/new.py with X = 1 and committed it."},
]


class TestAPatchTaskLandsThroughItsWorktree(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name)
        # `known_tools()` is process-global: a Kernel booted by another
        # test in this process leaves its registrations behind, and a
        # runner only asks for a worktree when Execution announced the
        # tool. Say what this Execution offers, and forget it after.
        forget_registered()
        for name in (*profiles.PATCH.tools, "worktree_open", "worktree_land", "worktree_close"):
            note_registered(name)

    def tearDown(self) -> None:
        forget_registered()
        self._tmp.cleanup()

    @run
    async def test_open_before_the_first_step_then_land_after_verification(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=_SCRIPT)
            gx = WorktreeExecution(h.client("guardian"), self.path)
            verification = FakeVerification(h.client("verification"), ["pass"])
            for fake in (cognition, gx, verification):
                await fake.start()

            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, worktrees=True)
            session = Session(task_id="t-wt", kind="patch", mode="execute", profile=profiles.PATCH)
            outcome = await runner.run(session, user_text="add X")

            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(gx.tools, ["worktree_open", "apply_source_patch", "git_commit", "worktree_land"])
            self.assertIn("[landed 1 commit(s) on main", outcome.result_summary)
            self.assertEqual(session.worktree, "")  # landing removed it
            self.assertEqual(session.base_ref, "abc123def")
            opened = session.steps[0]
            self.assertEqual(opened.tool, "worktree_open")
            self.assertEqual(opened.phase, "gather")
            self.assertIn(str(self.path), opened.summary)
            self.assertEqual(session.steps[-1].tool, "worktree_land")
            self.assertTrue(session.steps[-1].ok)
            # The verify subject says where the files are.
            subject_ref = verification.requests[0].payload["subject_ref"]
            import json
            subject = json.loads(await h.ledger.get_blob(subject_ref))
            self.assertEqual(subject["repo_root"], str(self.path))

            for fake in (cognition, gx, verification):
                await fake.stop()

    @run
    async def test_a_refused_landing_blocks_the_attempt_and_keeps_the_tree(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=_SCRIPT)
            gx = WorktreeExecution(h.client("guardian"), self.path, land_ok=False)
            verification = FakeVerification(h.client("verification"), ["pass"])
            for fake in (cognition, gx, verification):
                await fake.start()

            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, worktrees=True)
            session = Session(task_id="t-wt2", kind="patch", mode="execute", profile=profiles.PATCH)
            outcome = await runner.run(session, user_text="add X")

            self.assertEqual(outcome.kind, "blocked")
            self.assertTrue(outcome.reason.startswith(LANDING_REASON), outcome.reason)
            self.assertIn("suite is red", outcome.reason)
            self.assertEqual(outcome.result_summary, _SCRIPT[-1]["text"])
            self.assertNotIn("worktree_close", gx.tools)  # kept for the next attempt
            self.assertEqual(session.worktree, str(self.path))
            self.assertFalse(session.steps[-1].ok)

            for fake in (cognition, gx, verification):
                await fake.stop()

    @run
    async def test_without_the_switch_no_worktree_is_asked_for(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=_SCRIPT)
            gx = WorktreeExecution(h.client("guardian"), self.path)
            verification = FakeVerification(h.client("verification"), ["pass"])
            for fake in (cognition, gx, verification):
                await fake.start()

            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t-wt3", kind="patch", mode="execute", profile=profiles.PATCH)
            outcome = await runner.run(session, user_text="add X")

            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(gx.tools, ["apply_source_patch", "git_commit"])
            self.assertEqual(session.worktree, "")

            for fake in (cognition, gx, verification):
                await fake.stop()

    @run
    async def test_a_chat_session_never_opens_one(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[{"text": "hi"}])
            gx = WorktreeExecution(h.client("guardian"), self.path)
            await cognition.start()
            await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, worktrees=True)
            session = Session(task_id="t-chat", kind="chat", mode="execute", profile=profiles.CHAT)
            outcome = await runner.run(session, user_text="hello")
            self.assertEqual(outcome.kind, "completed")
            self.assertEqual(gx.tools, [])
            await cognition.stop()
            await gx.stop()

    @run
    async def test_when_no_worktree_can_be_opened_the_live_tree_is_used_and_said_so(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=_SCRIPT)
            gx = WorktreeExecution(h.client("guardian"), self.path, open_ok=False)
            verification = FakeVerification(h.client("verification"), ["pass"])
            for fake in (cognition, gx, verification):
                await fake.start()

            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, worktrees=True)
            session = Session(task_id="t-wt4", kind="patch", mode="execute", profile=profiles.PATCH)
            outcome = await runner.run(session, user_text="add X")

            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(gx.tools, ["worktree_open", "apply_source_patch", "git_commit"])
            self.assertEqual(session.worktree, "")
            self.assertIn("working in the live tree", session.steps[0].summary)
            self.assertIn("no git", session.steps[0].summary)

            for fake in (cognition, gx, verification):
                await fake.stop()

    @run
    async def test_a_cancelled_task_closes_its_worktree(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=_SCRIPT)
            gx = WorktreeExecution(h.client("guardian"), self.path)
            await cognition.start()
            await gx.start()

            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, worktrees=True,
                                   is_cancelled=lambda task_id: True)
            session = Session(task_id="t-wt5", kind="patch", mode="execute", profile=profiles.PATCH)
            outcome = await runner.run(session, user_text="add X")

            self.assertEqual(outcome.kind, "failed")
            self.assertEqual(gx.tools, ["worktree_open", "worktree_close"])
            self.assertEqual(session.worktree, "")

            await cognition.stop()
            await gx.stop()


if __name__ == "__main__":
    unittest.main()
