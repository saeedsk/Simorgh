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
