"""`tool_more` (stage 17 items 3 and 6): tool routing's escape hatch is a
real registered tool, so Guardian gates it and the ledger records it like
any call, and it changes nothing in the world. Orchestration does the
widening (tests/simorgh/orchestration/test_tool_routing.py)."""

from __future__ import annotations

import unittest

from simorgh.execution.config import Config
from simorgh.execution.tools import ToolMoreTool, builtin_tools, meta_tools

from .test_service import _ExecutionServiceTestCase


class TheTool(unittest.IsolatedAsyncioTestCase):
    async def test_it_reads_only_and_names_the_group(self):
        tool = ToolMoreTool(Config())
        self.assertTrue(tool.read_only)
        self.assertEqual(tool.reversibility, "read_only")
        result = await tool.run({"group": "home"}, ctx=None)
        self.assertTrue(result.ok)
        self.assertIn("home", result.output)
        self.assertFalse(result.side_effects)

    async def test_no_group_is_an_error_not_a_success(self):
        result = await ToolMoreTool(Config()).run({}, ctx=None)
        self.assertFalse(result.ok)

    def test_its_schema_is_flat_and_needs_the_group(self):
        schema = ToolMoreTool.args_schema
        self.assertEqual(schema["required"], ["group"])
        self.assertTrue(all(p.get("type") != "object" for p in schema["properties"].values()))

    def test_it_is_a_meta_tool_not_a_builtin(self):
        """Kept out of `builtin_tools`, whose every entry has a narration
        verb in the Interface (tests/simorgh/interface/test_live_status.py)."""
        self.assertIn("tool_more", {t.name for t in meta_tools(Config())})
        self.assertNotIn("tool_more", {t.name for t in builtin_tools(Config())})


class ItsDescription(unittest.TestCase):
    def test_it_names_every_group_the_model_may_ask_for(self):
        """The description is the only list of groups the model sees
        before it asks; a group added to `agents/groups.toml` and not named
        here is one the model never knows to ask for."""
        import tomllib
        from pathlib import Path

        path = Path(__file__).resolve().parents[3] / "agents" / "groups.toml"
        groups = tomllib.loads(path.read_text(encoding="utf-8"))["groups"]
        askable = {n for n, g in groups.items() if g.get("tools") and not g.get("core")}
        named = set(ToolMoreTool.description.split("(", 1)[1].split(")", 1)[0].replace(" ", "").split(","))
        self.assertEqual(named, askable)


class ItIsRegistered(_ExecutionServiceTestCase):
    async def test_the_service_registers_it(self):
        await self._start()
        tool = self.service._registry.get("tool_more")  # noqa: SLF001 -- the live registry
        self.assertIsNotNone(tool)
        self.assertTrue(tool.read_only)


if __name__ == "__main__":
    unittest.main()
