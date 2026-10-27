"""`memory_core_edit`: the model keeping a core memory block (stage 15
item 8, execution/tools.py).

Whose block an edit may touch is decided by who asked, and who asked comes
from Guardian's own record of the proposal -- never from the arguments the
model wrote. The tool says what the block now reads, or Memory's reason it
did not take the edit.
"""

from __future__ import annotations

import types
import unittest

from simorgh.contracts import topics
from simorgh.execution.config import Config
from simorgh.execution.tools import MemoryCoreEditTool, builtin_tools, memory_tools


class _Ledger:
    def __init__(self, requester: str | None, channel: str = "") -> None:
        self.requester, self.channel = requester, channel

    async def read(self, stream, **_kw):
        if self.requester is None:
            return []
        return [types.SimpleNamespace(type="received", payload={"proposal": {
            "requester": self.requester, "requester_channel": self.channel}})]


class _Bus:
    def __init__(self, answer: dict | None) -> None:
        self.answer = answer
        self.sent: list = []

    async def request(self, message, *, timeout=None):
        self.sent.append(message)
        # None: the reply's error shape, Memory failed to answer.
        payload = self.answer if self.answer is not None else {
            "ok": False, "error": {"code": "handler_error", "detail": "boom", "retryable": True}}
        return types.SimpleNamespace(payload=payload)


def _ctx(bus, requester, channel=""):
    return types.SimpleNamespace(bus=bus, ledger=_Ledger(requester, channel), action_id="a-1", task_id="turn-3")


class MemoryCoreEditTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = MemoryCoreEditTool(Config())

    def test_registered_reversible_with_a_schema(self):
        self.assertIn("memory_core_edit", {t.name for t in memory_tools(Config())})
        # Not in `builtin_tools`: no agent file names it (a chat session adds it).
        self.assertNotIn("memory_core_edit", {t.name for t in builtin_tools(Config())})
        self.assertEqual(self.tool.reversibility, "reversible")
        self.assertFalse(self.tool.read_only)
        self.assertEqual(set(self.tool.args_schema["properties"]), {"block", "old", "new"})

    async def test_the_requester_comes_from_guardians_record_not_the_arguments(self):
        bus = _Bus({"edited": True, "block": "person:soodeh", "text": "prefers Farsi", "reason": ""})
        result = await self.tool.run({"block": "me", "old": "", "new": "prefers Farsi", "requester": "Saeed"},
                                     ctx=_ctx(bus, "Soodeh", "voice"))
        self.assertTrue(result.ok, result)
        sent = bus.sent[-1]
        self.assertEqual(sent.type, topics.MEMORY_CORE_EDIT)
        edit = sent.payload
        self.assertNotIn("core_edit", edit)
        self.assertEqual((edit["requester"], edit["requester_channel"]), ("Soodeh", "voice"))
        self.assertEqual((edit["source_ref"], edit["action_id"]), ("turn-3", "a-1"))
        self.assertIn("prefers Farsi", result.output)

    async def test_no_record_of_who_asked_refuses_and_sends_nothing(self):
        bus = _Bus({"edited": True, "block": "household", "text": "x", "reason": ""})
        result = await self.tool.run({"block": "household", "new": "x"}, ctx=_ctx(bus, None))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "refused")
        self.assertEqual(bus.sent, [])

    async def test_memorys_refusal_is_repeated(self):
        bus = _Bus({"edited": False, "block": "", "text": "", "reason": "core memory blocks are off"})
        result = await self.tool.run({"block": "household", "new": "b"}, ctx=_ctx(bus, "Ira", "voice"))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("off", result.error)

    async def test_a_memory_that_failed_to_answer_is_transient(self):
        result = await self.tool.run({"block": "household", "new": "x"}, ctx=_ctx(_Bus(None), ""))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "transient")


class DefenceInDepthTestCase(unittest.IsolatedAsyncioTestCase):
    """The tool's own check, behind Guardian's `CoreMemoryRule`: a call the
    gate should have denied is refused here and nothing reaches Memory."""

    def setUp(self):
        self.tool = MemoryCoreEditTool(Config())
        self.bus = _Bus({"edited": True, "block": "x", "text": "x", "reason": ""})

    async def run_as(self, block, requester, channel):
        return await self.tool.run({"block": block, "new": "x"}, ctx=_ctx(self.bus, requester, channel))

    async def test_same_person_and_household_are_sent(self):
        for block in ("me", "Soodeh", "household"):
            self.assertTrue((await self.run_as(block, "Soodeh", "voice")).ok, block)
        self.assertEqual(len(self.bus.sent), 3)

    async def test_another_persons_block_is_refused(self):
        result = await self.run_as("Soodeh", "Ira", "voice")
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("not yours", result.error)
        self.assertEqual(self.bus.sent, [])

    async def test_an_unknown_speaker_is_refused(self):
        for requester, channel in (("unknown", "voice"), ("", "voice"), ("", "initiative")):
            result = await self.run_as("household", requester, channel)
            self.assertEqual(result.error_kind, "refused", (requester, channel))
        self.assertEqual(self.bus.sent, [])

    async def test_an_outside_channel_is_refused(self):
        result = await self.run_as("household", "Saeed", "a2a")
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("outside", result.error)
        self.assertEqual(self.bus.sent, [])

    async def test_the_console_is_left_to_memory(self):
        self.assertTrue((await self.run_as("me", "", "cli")).ok)
        self.assertEqual(self.bus.sent[-1].payload["requester"], "")


if __name__ == "__main__":
    unittest.main()
