"""`forget [kind] [minutes|Nd] [words]` (interface/dispatch.py).

Two reaches it did not have: a KIND other than episodic -- a wrong
consolidated FACT kept Sim answering English in Farsi on 2026-09-25, and
four `forget` sweeps over episodic turns could not touch it -- and DAYS,
past the one-day cap on minutes, for clearing old overheard talk."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from simorgh.interface import dispatch as d
from simorgh.interface.parser import parse


async def _asked(line: str) -> dict:
    seen = {}

    async def fake_run_tool(*, tool, raw, **_kw):
        seen["tool"], seen["args"] = tool, json.loads(raw)
        return d.Outcome("ok")
    with mock.patch.object(d, "_run_tool", fake_run_tool):
        class _Clock:
            def now(self):
                return 0.0
        await d.dispatch(parse(line), bus=None, clock=_Clock(), session_id="s", vitals=None, ledger=None)
    assert seen.get("tool") == "memory_forget", seen
    return seen["args"]


class TheForgetCommand(unittest.IsolatedAsyncioTestCase):
    async def test_bare_forget_is_the_last_two_minutes_of_everything_said(self):
        self.assertEqual(await _asked("forget"), {"containing": "", "minutes": 2.0})

    async def test_a_kind_is_named_first(self):
        args = await _asked("forget facts Farsi")
        self.assertEqual((args["kinds"], args["containing"]), (["facts"], "Farsi"))

    async def test_days_in_either_spelling(self):
        self.assertEqual((await _asked("forget 5d"))["days"], 5.0)
        self.assertEqual((await _asked("forget 3 days the TV"))["days"], 3.0)
        self.assertNotIn("minutes", await _asked("forget 5d"))

    async def test_plain_minutes_and_words(self):
        args = await _asked("forget 10 the dentist")
        self.assertEqual((args["minutes"], args["containing"]), (10.0, "the dentist"))


if __name__ == "__main__":
    unittest.main()
