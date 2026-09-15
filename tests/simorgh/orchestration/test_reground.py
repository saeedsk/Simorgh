"""Re-grounding: the progress note replaces a long transcript
(docs/plans/long-run-context-design.md section 3)."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.contracts.registry import error_reply_payload
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Budget, Session
from simorgh.orchestration.progress import NOTE_HEADER, ProgressNote, compacted, due, parse_note
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition, FakeGuardianExecution
from .harness import Harness, run

NOTE = json.dumps({"goal": "Find the release year of the album", "done": ["searched the discography"],
                   "learned": ["the wiki page lists 2009"], "next": "confirm on a second source", "open_questions": []})


def _tool(path):
    return {"tool_calls": [{"tool": "read_file", "args": {"path": path}}]}


class _ErroringCognition(FakeCognition):
    """A script item `{"error": code}` replies with a Cognition error."""

    async def _on(self, message):
        self.calls.append(message)
        i = min(len(self.calls) - 1, len(self._script) - 1)
        step = self._script[i]
        if "error" in step:
            await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY,
                                  payload=error_reply_payload(step["error"], "too many tokens"))
            return
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
            "text": step.get("text", ""), "tool_calls": step.get("tool_calls", []), "provider": "fake",
            "cost_usd": 0.0, "tokens": 10, "floor": False, "non_answer": False})


def _session(task_id, steps=10):
    return Session(task_id=task_id, kind="research", mode="execute",
                   profile=replace(profiles.RESEARCH, verify=False, max_steps=steps), budget=Budget(max_steps=steps))


class NotePieces(unittest.TestCase):
    def test_a_fenced_note_parses_and_a_goalless_one_does_not(self):
        note = parse_note(f"Here you go:\n```json\n{NOTE}\n```")
        self.assertEqual(note.goal, "Find the release year of the album")
        self.assertEqual(note.done, ["searched the discography"])
        self.assertIsNone(parse_note('{"done": ["x"]}'), "a note with no goal is not a note")
        self.assertIsNone(parse_note("no json here"))

    def test_the_compacted_transcript_is_the_note_then_recent_steps_from_an_assistant_turn(self):
        msgs = []
        for n in range(5):
            msgs += [{"role": "assistant", "content": f"READ_FILE: f{n}"}, {"role": "user", "content": f"Result {n}"}]
        out = compacted(msgs, ProgressNote(goal="g", next="n"), keep_recent_steps=2)
        self.assertTrue(out[0]["content"].startswith(NOTE_HEADER))
        self.assertEqual([m["content"] for m in out[1:]], ["READ_FILE: f3", "Result 3", "READ_FILE: f4", "Result 4"])
        self.assertEqual(len(compacted(msgs, ProgressNote(goal="g"), keep_recent_steps=0)), 1)

    def test_due_counts_from_the_last_reground(self):
        self.assertFalse(due(2, 0, 3))
        self.assertTrue(due(3, 0, 3))
        self.assertFalse(due(5, 3, 3))
        self.assertFalse(due(99, 0, 0), "0 is off")


class RegroundFlow(unittest.TestCase):
    @run
    async def test_every_n_steps_the_transcript_becomes_the_note(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                _tool("a.md"), _tool("b.md"), _tool("c.md"), {"text": NOTE}, _tool("d.md"), {"text": "2009"}])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                   reground_every_steps=3, keep_recent_steps=1)
            session = _session("t-reground")
            outcome = await runner.run(session, user_text="When was the album released?")
            self.assertEqual(outcome.kind, "completed")
            purposes = [c.payload["purpose"] for c in cognition.calls]
            self.assertEqual(purposes[3], "reground")
            after = cognition.calls[4].payload["messages"]
            joined = "\n".join(str(m.get("content")) for m in after)
            self.assertIn(NOTE_HEADER, joined, "the next THINK sees the note")
            self.assertEqual(joined.count("Result of read_file"), 1,
                             "and only the one kept step, not the three it replaced")
            self.assertIn("confirm on a second source", session.progress)
            events = await h.ledger.read("task:t-reground")
            progress = [e for e in events if e.type == topics.TASK_PROGRESS]
            self.assertEqual(len(progress), 1)
            self.assertIn("Find the release year", progress[0].payload["note"])
            self.assertTrue(any(s.summary.startswith("reground:") for s in session.steps))
            await cognition.stop(); await gx.stop()

    @run
    async def test_an_unusable_note_keeps_the_transcript(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                _tool("a.md"), _tool("b.md"), _tool("c.md"), {"text": "sorry, no json"}, {"text": "2009"}])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                   reground_every_steps=3)
            session = _session("t-badnote")
            outcome = await runner.run(session, user_text="When?")
            self.assertEqual(outcome.kind, "completed")
            joined = "\n".join(str(m.get("content")) for m in cognition.calls[4].payload["messages"])
            self.assertEqual(joined.count("Result of read_file"), 3, "nothing was lost")
            self.assertNotIn(NOTE_HEADER, joined)
            self.assertTrue(any("reground skipped" in s.summary for s in session.steps))
            self.assertEqual(session.progress, "")
            await cognition.stop(); await gx.stop()

    @run
    async def test_off_by_default(self):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[
                _tool("a.md"), _tool("b.md"), _tool("c.md"), _tool("d.md"), {"text": "2009"}])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05)
            await runner.run(_session("t-off"), user_text="When?")
            self.assertNotIn("reground", [c.payload["purpose"] for c in cognition.calls])
            await cognition.stop(); await gx.stop()


class ContextTooLarge(unittest.TestCase):
    @run
    async def test_it_is_regrounded_and_retried_once(self):
        async with Harness() as h:
            cognition = _ErroringCognition(h.client("cognition"), script=[
                _tool("a.md"), _tool("b.md"), {"error": "context_too_large"}, {"text": NOTE}, {"text": "2009"}])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05,
                                   reground_every_steps=50)
            session = _session("t-toolarge")
            outcome = await runner.run(session, user_text="When?")
            self.assertEqual(outcome.kind, "completed", outcome.reason)
            self.assertEqual(outcome.result_summary, "2009")
            self.assertTrue(any("(context too large)" in s.summary for s in session.steps))
            await cognition.stop(); await gx.stop()

    @run
    async def test_still_too_large_blocks_with_the_true_reason(self):
        async with Harness() as h:
            cognition = _ErroringCognition(h.client("cognition"), script=[
                _tool("a.md"), {"error": "context_too_large"}, {"text": NOTE}, {"error": "context_too_large"}])
            gx = FakeGuardianExecution(h.client("guardian"))
            await cognition.start(); await gx.start()
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now, assemble_timeout_s=0.05)
            outcome = await runner.run(_session("t-toolarge-2"), user_text="When?")
            self.assertEqual(outcome.kind, "blocked")
            self.assertIn("context too large", outcome.reason)
            self.assertNotIn("no real provider", outcome.reason)
            await cognition.stop(); await gx.stop()


if __name__ == "__main__":
    unittest.main()
