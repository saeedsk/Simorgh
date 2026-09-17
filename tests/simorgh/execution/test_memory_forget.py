"""How far back `memory_forget` reaches (execution/tools.py).

`minutes` is capped at a day, and that cap is not a limitation waiting
to be raised -- it is what stands between "forget the last minute, that
was the TV" and a wiped memory. So reaching further back is a different
argument, said on purpose.

What made it necessary: 447 episodic records of overheard talk piled up
between 2026-09-11 and 2026-09-16 -- family asides, TV dialogue, and one
verbatim line from the creator's work call. Five days is out of reach of
a one-day cap, so there was no way to clear them at all.

Nothing here was covered before; the only test naming this tool was the
list of tool names.
"""

from __future__ import annotations

import types
import unittest

from simorgh.execution.config import Config
from simorgh.execution.tools import _FORGET_MAX_DAYS, MemoryForgetTool


class _Bus:
    def __init__(self, forgotten: int = 3) -> None:
        self.sent: list[dict] = []
        self._forgotten = forgotten

    async def request(self, message, *, timeout=None):
        self.sent.append(dict(message.payload))
        return types.SimpleNamespace(payload={"forgotten": self._forgotten})


class MemoryForgetReachTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bus = _Bus()
        self.tool = MemoryForgetTool(Config())
        self.ctx = types.SimpleNamespace(bus=self.bus)

    async def _minutes(self, **args) -> float:
        await self.tool.run(args, ctx=self.ctx)
        return float(self.bus.sent[-1]["minutes"])

    async def test_the_default_is_the_last_couple_of_minutes(self):
        self.assertEqual(await self._minutes(), 2.0)

    async def test_minutes_is_still_capped_at_a_day(self):
        """The cap is the safety rail, not an oversight."""
        self.assertEqual(await self._minutes(minutes=10_000), 24 * 60.0)

    async def test_days_reaches_past_the_day_cap(self):
        """Five days of overheard asides could not be cleared at all."""
        self.assertEqual(await self._minutes(days=5), 5 * 24 * 60.0)

    async def test_days_has_a_cap_of_its_own(self):
        self.assertEqual(await self._minutes(days=9_999), _FORGET_MAX_DAYS * 24 * 60.0)

    async def test_days_wins_when_both_are_given(self):
        self.assertEqual(await self._minutes(days=2, minutes=5), 2 * 24 * 60.0)

    async def test_what_it_is_about_is_passed_through(self):
        await self.tool.run({"days": 5, "containing": "ABC team"}, ctx=self.ctx)
        self.assertEqual(self.bus.sent[-1]["containing"], "ABC team")
        self.assertEqual(self.bus.sent[-1]["kinds"], ["episodic"])

    async def test_a_word_where_a_number_belongs_is_refused(self):
        result = await self.tool.run({"days": "last tuesday"}, ctx=self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("numbers", result.error)
        self.assertEqual(self.bus.sent, [], "nothing was asked of memory")

    async def test_it_reports_the_count_it_was_given_and_no_more(self):
        """"I'll wipe it from the record" with nothing behind the words
        is the failure this tool was built for; inventing a count would
        be the same failure wearing a number."""
        self.tool = MemoryForgetTool(Config())
        self.bus = _Bus(forgotten=0)
        self.ctx = types.SimpleNamespace(bus=self.bus)
        result = await self.tool.run({"days": 5}, ctx=self.ctx)
        self.assertTrue(result.ok)
        self.assertIn("nothing", result.output)
        self.assertEqual(result.metadata["forgotten"], 0)

    async def test_without_a_bus_it_says_so_rather_than_claiming_success(self):
        result = await self.tool.run({"days": 5}, ctx=types.SimpleNamespace(bus=None))
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
