"""`home_blink`: a light switched off and on at a rate, then put back.

Live, 2026-09-27: asked to blink a light at 1-5 Hz for a minute, the
model wrote a shell loop with a token the shell did not have, said
"started", and nothing blinked."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from simorgh.contracts.home.fakes import FakeHomeAssistant
from simorgh.contracts.protocols import ToolContext
from simorgh.domains.home import tools as home
from simorgh.execution.config import Config


def _ctx() -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=Path("."), clock=None, logger=None, ledger=None)


class HomeBlink(unittest.IsolatedAsyncioTestCase):
    def _tool(self, house):
        return home.HomeBlinkTool(Config(), client=house, env={})

    async def test_blinks_then_puts_the_light_back(self):
        house = FakeHomeAssistant()
        got = await self._tool(house).run({"target": "living room lamp", "hz": 4, "seconds": 1}, ctx=_ctx())
        self.assertTrue(got.ok, got.error)
        self.assertIn("first switch was confirmed", got.output)
        await asyncio.gather(*set(home._BLINKING.values()))       # noqa: SLF001
        switched = [c for c in house.calls if c[1] == ("light.living_room",)]
        self.assertGreaterEqual(len(switched), 8, "a toggle to check, eight switches, and the put-back")
        self.assertEqual((await house.state("light.living_room")).state, "on", "back as it was")

    async def test_a_light_that_does_not_move_is_not_said_to_blink(self):
        house = FakeHomeAssistant(unavailable=("light.living_room",))
        got = await self._tool(house).run({"target": "living room lamp", "hz": 1, "seconds": 5}, ctx=_ctx())
        self.assertFalse(got.ok)
        self.assertIn("Nothing is blinking", got.error)
        self.assertFalse(home._BLINKING)                           # noqa: SLF001

    async def test_too_fast_is_slowed_and_said(self):
        house = FakeHomeAssistant()
        got = await self._tool(house).run({"target": "living room lamp", "hz": 20, "seconds": 0.5}, ctx=_ctx())
        self.assertTrue(got.ok, got.error)
        self.assertEqual(got.metadata["hz"], home.HomeBlinkTool.MAX_HZ)
        self.assertIn("Limited", got.output)
        await asyncio.gather(*set(home._BLINKING.values()))       # noqa: SLF001

    def test_it_is_registered_where_home_call_is(self):
        from simorgh.contracts.toolargs import MARKER_JSON_REST
        from simorgh.interface.httpapi import ACTION_TOOLS
        from simorgh.orchestration import tools as orch

        self.assertIn("home_blink", [t.name for t in home.home_tools(Config(), env={})])
        self.assertIn("home_blink", MARKER_JSON_REST)
        self.assertIn("home_blink", ACTION_TOOLS)
        for p in ("agents/voice_chat.md", "agents/chat.md"):
            self.assertIn('"home_blink"', Path(p).read_text(encoding="utf-8"), p)
        self.assertIn("home_blink", str(orch.__dict__))


if __name__ == "__main__":
    unittest.main()
