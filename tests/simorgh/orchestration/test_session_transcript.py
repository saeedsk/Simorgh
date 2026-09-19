"""Stage 4 item 2: a session's messages are its `session:<id>` stream, and a
resumed session gets them back (evaluation L5)."""

import unittest

from simorgh.contracts import topics
from simorgh.contracts import session as s
from simorgh.contracts.envelope import Event
from simorgh.ledger.factory import make_ledger
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.resume import restore_session
from simorgh.orchestration.transcript import SNAPSHOT_EVERY, TranscriptWriter, fold

MESSAGES = [
    {"role": "user", "content": "add a docstring to a.py"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "tool": "read_file", "args": {"path": "a.py"}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": "x = 1"},
    {"role": "user", "content": "If the task is now finished, reply... Otherwise take the next step."},
    {"role": "assistant", "content": "READ_FILE: b.py"},
]


class TheTranscriptStream(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"})
        await self.ledger.start()

    async def test_messages_round_trip_one_event_per_turn(self):
        writer = TranscriptWriter(self.ledger)
        messages = list(MESSAGES[:3])
        await writer.persist("t1", messages)
        messages += MESSAGES[3:]
        await writer.persist("t1", messages)
        events = await self.ledger.read("session:t1")
        self.assertEqual([e.type for e in events], [s.TURN_APPENDED] * 5)
        self.assertEqual(fold(events), MESSAGES)

    async def test_a_replaced_list_is_one_compacted_event(self):
        writer = TranscriptWriter(self.ledger)
        await writer.persist("t1", list(MESSAGES))
        await writer.persist("t1", [{"role": "user", "content": "progress note: read a.py, next b.py"}])
        events = await self.ledger.read("session:t1")
        self.assertEqual(events[-1].type, s.COMPACTED)
        self.assertEqual(fold(events), [{"role": "user", "content": "progress note: read a.py, next b.py"}])

    async def test_a_long_session_snapshots(self):
        writer = TranscriptWriter(self.ledger)
        messages = [{"role": "user", "content": f"turn {i}"} for i in range(SNAPSHOT_EVERY + 5)]
        await writer.persist("t1", messages)
        events = await self.ledger.read("session:t1")
        self.assertEqual(sum(1 for e in events if e.type == s.SNAPSHOT), 1)
        self.assertEqual(fold(events), messages)

    async def test_a_resumed_session_gets_its_context_back(self):
        # The dead worker: an attempt started, two steps recorded, its
        # transcript written; then nothing (a SIGKILL).
        def ev(type_, **payload):
            return Event(stream="task:t1", type=type_, ts=0.0, trace_id="t1", causation_id=None, payload=payload)

        for event in (ev(topics.TASK_STARTED, task_id="t1", worker_id="w1"),
                      ev(topics.TASK_STEP, task_id="t1", step_no=1, phase="act", tool="read_file", summary="x = 1", ok=True)):
            await self.ledger.append("task:t1", event)
        await TranscriptWriter(self.ledger).persist("t1", list(MESSAGES))
        session = Session(task_id="t1", kind="patch", mode="execute", profile=profiles.PATCH)
        session.budget.max_steps = 20
        spent = await restore_session(session, self.ledger)
        self.assertEqual(spent, 1)
        self.assertEqual(session.messages, MESSAGES)


class AConversationIsOnePersistentSession(unittest.IsolatedAsyncioTestCase):
    """Stage 4 item 3: one session per (channel, person), durable."""

    async def test_exchanges_are_appended_and_read_back_in_order(self):
        from simorgh.orchestration.transcript import append_exchange, conversation_id, recent_lines

        ledger = make_ledger({"backend": "memory"})
        await ledger.start()
        conv = conversation_id("voice", "Ira")
        self.assertEqual(conv, "conv:voice:ira")
        await append_exchange(ledger, conv, user_text="my laptop is called Falcon", answer="Noted.", who="Ira")
        await append_exchange(ledger, conv, user_text="what is it called?", answer="Falcon.", who="Ira")
        lines = await recent_lines(ledger, conv, 10)
        self.assertEqual(lines, ["Ira: my laptop is called Falcon", "Sim: Noted.",
                                 "Ira: what is it called?", "Sim: Falcon."])

    async def test_the_block_survives_a_restart(self):
        """A fresh Assembler over the same ledger -- a new process -- still
        sees the conversation; Memory's window was process memory."""
        from simorgh.orchestration.context import Assembler
        from simorgh.orchestration.transcript import append_exchange, conversation_id

        ledger = make_ledger({"backend": "memory"})
        await ledger.start()
        await append_exchange(ledger, conversation_id("cli", ""), user_text="the desktop is Orca",
                              answer="Got it.", who="User")
        session = Session(task_id="line-2", kind="chat", mode="execute", profile=profiles.CHAT, channel="cli")
        block = await Assembler(bus=None, ledger=ledger)._working_block(session)  # noqa: SLF001
        self.assertIn("User: the desktop is Orca", block)
        self.assertIn("Sim: Got it.", block)


class ALongTurnIsStoredAside(unittest.IsolatedAsyncioTestCase):
    """Live 2026-09-19 (trial round): an 8k task text broke the ledger's
    4096-char inline rule and the session's transcript was never written."""

    async def test_long_text_and_results_round_trip_through_blobs(self):
        from simorgh.orchestration.transcript import INLINE_MAX, hydrate

        ledger = make_ledger({"backend": "memory"})
        await ledger.start()
        long_task, long_result = "t" * 8241, "r" * 9000
        messages = [{"role": "user", "content": long_task},
                    {"role": "tool", "tool_call_id": "c1", "name": "read_file", "content": long_result}]
        await TranscriptWriter(ledger).persist("t9", messages)
        events = await ledger.read("session:t9")
        self.assertEqual(len(events), 2)
        self.assertLess(len(events[0].payload["blocks"][0]["text"]), INLINE_MAX)
        self.assertEqual(await hydrate(ledger, fold(events)), messages)

    async def test_a_long_answer_joins_the_conversation(self):
        from simorgh.orchestration.transcript import append_exchange, recent_lines

        ledger = make_ledger({"backend": "memory"})
        await ledger.start()
        await append_exchange(ledger, "conv:cli:saeed", user_text="tell me everything", answer="a" * 6000, who="Saeed")
        lines = await recent_lines(ledger, "conv:cli:saeed", 3)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("Sim: aaa"))
