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
    def __init__(self, requester: str | None) -> None:
        self.requester = requester

    async def read(self, stream, **_kw):
        if self.requester is None:
            return []
        return [types.SimpleNamespace(type="received", payload={"proposal": {"requester": self.requester}})]


class _Bus:
    def __init__(self, answer: dict | None) -> None:
        self.answer = answer
        self.sent: list = []

    async def request(self, message, *, timeout=None):
        self.sent.append(message)
        payload = {"items": [], "truncated": False}
        if self.answer is not None:
            payload["core_edit"] = self.answer
        return types.SimpleNamespace(payload=payload)


def _ctx(bus, requester):
    return types.SimpleNamespace(bus=bus, ledger=_Ledger(requester), action_id="a-1", task_id="turn-3")


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
        bus = _Bus({"ok": True, "block": "person:soodeh", "text": "prefers Farsi", "error": ""})
        result = await self.tool.run({"block": "me", "old": "", "new": "prefers Farsi", "requester": "Saeed"},
                                     ctx=_ctx(bus, "Soodeh"))
        self.assertTrue(result.ok, result)
        sent = bus.sent[-1]
        self.assertEqual(sent.type, topics.MEMORY_RETRIEVE)
        edit = sent.payload["core_edit"]
        self.assertEqual(edit["requester"], "Soodeh")
        self.assertEqual((edit["source_ref"], edit["action_id"]), ("turn-3", "a-1"))
        self.assertIn("prefers Farsi", result.output)

    async def test_no_record_of_who_asked_refuses_and_sends_nothing(self):
        bus = _Bus({"ok": True, "block": "household", "text": "x", "error": ""})
        result = await self.tool.run({"block": "household", "new": "x"}, ctx=_ctx(bus, None))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "refused")
        self.assertEqual(bus.sent, [])

    async def test_memorys_refusal_is_repeated(self):
        bus = _Bus({"ok": False, "block": "", "text": "", "error": "'Soodeh' is not yours to edit"})
        result = await self.tool.run({"block": "Soodeh", "old": "a", "new": "b"}, ctx=_ctx(bus, "Ira"))
        self.assertFalse(result.ok)
        self.assertIn("not yours", result.error)

    async def test_a_memory_without_core_blocks_is_unconfigured(self):
        result = await self.tool.run({"block": "household", "new": "x"}, ctx=_ctx(_Bus(None), ""))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "unconfigured")


if __name__ == "__main__":
    unittest.main()
