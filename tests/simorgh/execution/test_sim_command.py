"""Sim pressing its own CLI commands (the creator, 2026-09-15: "it should
be able to restart itself or any other cli command I ask it to run")."""

from __future__ import annotations

import types
import unittest

from simorgh.contracts import topics
from simorgh.contracts.registry import error_reply_payload
from simorgh.execution.config import Config
from simorgh.execution.tools import SimCommandTool


class _Bus:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.sent: list = []

    async def request(self, message, timeout: float = 0.0):
        self.sent.append(message)
        return types.SimpleNamespace(payload=self.payload)


def _ctx(bus):
    return types.SimpleNamespace(bus=bus)


class SimCommand(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool = SimCommandTool(Config())

    async def test_it_runs_the_command_and_returns_what_the_interface_said(self):
        bus = _Bus({"text": "restarting -- Sim will come back up on the current source..."})
        result = await self.tool.run({"command": "restart"}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        self.assertIn("come back up", result.output)
        self.assertEqual(bus.sent[0].type, topics.UI_COMMAND_REQUEST)
        self.assertEqual(bus.sent[0].payload["line"], "restart")

    async def test_a_refusal_comes_back_as_a_failure(self):
        bus = _Bus(error_reply_payload("unknown_command", "'flibble' is not one of Sim's commands"))
        result = await self.tool.run({"command": "flibble"}, ctx=_ctx(bus))
        self.assertFalse(result.ok)
        self.assertIn("not one of Sim's commands", result.error)

    async def test_the_shell_escape_is_refused_without_asking(self):
        bus = _Bus({"text": "should never be reached"})
        result = await self.tool.run({"command": "!rm -rf /"}, ctx=_ctx(bus))
        self.assertFalse(result.ok)
        self.assertIn("run_shell", result.error)
        self.assertEqual(bus.sent, [])

    async def test_no_command_is_refused(self):
        result = await self.tool.run({"command": "  "}, ctx=_ctx(_Bus({})))
        self.assertFalse(result.ok)

    async def test_it_is_irreversible_so_guardian_sees_it(self):
        self.assertEqual(self.tool.reversibility, "irreversible")
        self.assertFalse(self.tool.read_only)


if __name__ == "__main__":
    unittest.main()
