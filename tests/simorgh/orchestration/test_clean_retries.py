"""Clean retries and revisions: continue from the progress note, not the
old transcript (docs/plans/long-run-context-design.md section 4)."""

from __future__ import annotations

import unittest
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.progress import NOTE_HEADER
from simorgh.orchestration.resume import _attempts, carried_note, restore_session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution, FakeVerification
from .harness import Harness, run

NOTE = "Goal: fix the parser\nDone:\n- found the bug in parse.py\nLearned:\n- the tokenizer is fine\nNext: patch parse.py"


def _ev(type_, **payload):
    return Event(stream="task:t1", type=type_, ts=0.0, trace_id="t1", causation_id=None, payload=payload)


def _history(*, ended: str | None):
    events = [_ev(topics.TASK_STARTED, task_id="t1", worker_id="w1")]
    for n, summary in enumerate(["searched for parse", "read tokenizer.py", "read parse.py"], start=1):
        events.append(_ev(topics.TASK_STEP, task_id="t1", step_no=n, phase="act", tool="read_file", summary=summary, ok=True))
    events.append(_ev(topics.TASK_PROGRESS, task_id="t1", note=NOTE, step_no=3, attempt=1))
    events.append(_ev(topics.TASK_STEP, task_id="t1", step_no=5, phase="act", tool="search_code", summary="grep for callers", ok=True))
    if ended:
        events.append(_ev(topics.TASK_BLOCKED, task_id="t1", reason="step budget exhausted before the task was finished"))
    return events


class _Ledger:
    def __init__(self, events):
        self._events = events

    async def read(self, stream, **_):
        return list(self._events)


class NoteBasedRetry(unittest.IsolatedAsyncioTestCase):
    def test_the_attempt_remembers_its_latest_note_and_where(self):
        attempt = _attempts(_history(ended="blocked"))[0]
        self.assertEqual(attempt["note"], NOTE)
        self.assertEqual(attempt["note_at"], 3)

    def test_a_retry_is_told_the_note_and_only_the_later_steps(self):
        text = carried_note(_attempts(_history(ended="blocked")))
        self.assertIn("Its progress note:", text)
        self.assertIn("patch parse.py", text)
        self.assertIn("grep for callers", text, "a step after the note is still listed")
        self.assertNotIn("read tokenizer.py", text, "steps the note summarised are not repeated")

    async def test_a_crash_resume_opens_with_the_note(self):
        session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        session.budget.max_steps = 20
        spent = await restore_session(session, _Ledger(_history(ended=None)))
        self.assertEqual(spent, 4)
        self.assertEqual(session.progress, NOTE)
        self.assertEqual(session.reground_at, 3)
        self.assertTrue(session.messages[0]["content"].startswith(NOTE_HEADER))


class CleanRevision(unittest.TestCase):
    async def _revision_messages(self, h, *, clean: bool) -> str:
        cognition = FakeCognition(h.client("cognition"), script=[
            {"tool_calls": [{"tool": "read_file", "args": {"path": p}}]} for p in ("a", "b", "c")
        ] + [{"text": "first answer"}, {"text": "revised answer"}])
        gx = FakeGuardianExecution(h.client("guardian"))
        verification = FakeVerification(h.client("verification"), verdicts=["fail", "pass"])
        await cognition.start(); await gx.start(); await verification.start()
        runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                               keep_recent_steps=2, clean_revisions=clean)
        session = Session(task_id=f"t-rev-{'clean' if clean else 'plain'}", kind="research", mode="execute",
                          profile=replace(profiles.RESEARCH, verify=True, max_revisions=1, max_steps=10),
                          budget=Budget(max_steps=10))
        outcome = await runner.run(session, user_text="answer it")
        self.assertEqual(outcome.kind, "completed", outcome.reason)
        self.assertEqual(outcome.result_summary, "revised answer")
        messages = cognition.calls[4].payload["messages"]
        await cognition.stop(); await gx.stop(); await verification.stop()
        return "\n".join(str(m.get("content")) for m in messages)

    @run
    async def test_a_clean_revision_keeps_only_the_recent_steps(self):
        async with Harness() as h:
            joined = await self._revision_messages(h, clean=True)
            self.assertIn("Verification feedback", joined)
            self.assertEqual(joined.count("Result of read_file"), 1)

    @run
    async def test_off_by_default_the_revision_sees_everything(self):
        async with Harness() as h:
            joined = await self._revision_messages(h, clean=False)
            self.assertIn("Verification feedback", joined)
            self.assertEqual(joined.count("Result of read_file"), 3)


if __name__ == "__main__":
    unittest.main()
