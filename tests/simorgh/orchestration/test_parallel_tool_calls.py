"""Stage 2 items 5-6: a native reply's calls all run, reads together and
changes in order, and the transcript keeps typed turns."""

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .fakes import FakeCognition
from .harness import Harness, run


class _Guardian:
    """Approves and runs everything except `failing`, which fails."""

    def __init__(self, bus, failing=()):
        self._bus, self._failing, self.proposals, self._sub = bus, set(failing), [], None

    async def start(self):
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def stop(self):
        await self._sub.unsubscribe()

    async def _on(self, message):
        self.proposals.append(message.payload)
        tool = message.payload["tool"]
        ok = tool not in self._failing
        await self._bus.publish(message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": ok, "output_ref": "",
            "stdout_preview": f"ran {tool}", "duration_ms": 1, "side_effects": [],
            **({} if ok else {"error": "failed: boom"})}, source="execution"))


CALLS = [
    {"id": "c1", "tool": "read_file", "args": {"path": "a.py"}},
    {"id": "c2", "tool": "search_code", "args": {"query": "x"}},
    {"id": "c3", "tool": "replace_in_file", "args": {"path": "workspace/a.py", "code": "..."}},
    {"id": "c4", "tool": "apply_source_patch", "args": {"subject": "workspace/b.py", "code": "x = 1"}},
]


class NativeCallsRunTogether(unittest.TestCase):
    async def _run(self, failing=()):
        async with Harness() as h:
            cognition = FakeCognition(h.client("cognition"), script=[{"tool_calls": CALLS}, {"text": "done"}])
            guardian = _Guardian(h.client("guardian"), failing)
            await cognition.start()
            await guardian.start()
            # Chat: no verification or worktree in the way of what is tested here.
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
            session.budget.max_steps = 20
            await asyncio.wait_for(
                SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now).run(session, user_text="go"),
                timeout=30)
            await cognition.stop()
            await guardian.stop()
            return session, guardian

    @run
    async def test_every_call_runs_and_the_turn_is_typed(self):
        session, guardian = await self._run()
        self.assertEqual(sorted(p["tool"] for p in guardian.proposals),
                         sorted(c["tool"] for c in CALLS))
        assistant = next(m for m in session.messages if m.get("tool_calls"))
        self.assertEqual([c["id"] for c in assistant["tool_calls"]], ["c1", "c2", "c3", "c4"])
        tool_turns = [m for m in session.messages if m.get("role") == "tool"]
        self.assertEqual([m["tool_call_id"] for m in tool_turns], ["c1", "c2", "c3", "c4"])
        self.assertIn("ran read_file", tool_turns[0]["content"])

    @run
    async def test_a_failed_change_stops_the_later_changes(self):
        session, guardian = await self._run(failing=("replace_in_file",))
        self.assertNotIn("apply_source_patch", [p["tool"] for p in guardian.proposals])
        tool_turns = {m["tool_call_id"]: m["content"] for m in session.messages if m.get("role") == "tool"}
        self.assertIn("not run", tool_turns["c4"])
        self.assertIn("ran read_file", tool_turns["c1"])
