"""Asking what was overheard, and forgetting it (execution/tools.py).

This is the half that was missing twice. A store nobody can query is
not a feature: `voice/overheard.py` recorded every line and summarize,
replay and wipe appear nowhere in the voice command path, so its
`since()` and `lines()` were dead ends. `voice/overhear.py` had all the
queries and was imported by nothing at all.

So these tests are mostly about REACHABILITY -- that the asking works,
that an empty answer says so rather than inventing, and that the labels
Guardian trusts are the true ones.
"""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import overheard as store
from simorgh.execution.config import Config
from simorgh.execution.tools import OverheardNoteTool, OverheardTool


class _ToolTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        # The tools fall back to the REAL store when config names none.
        patch = mock.patch.object(store, "DEFAULT_DIR", self.folder)
        patch.start()
        self.addCleanup(patch.stop)
        self.ask = OverheardTool(Config())
        self.note = OverheardNoteTool(Config())
        self.ctx = types.SimpleNamespace(bus=None)

    def _heard(self, text, *, speaker="Ira", kind="overheard", at=None):
        import time

        store.record(text, speaker=speaker, kind=kind,
                     at=at if at is not None else time.time(), folder=self.folder)


class AskingTestCase(_ToolTestCase):
    async def test_an_empty_store_says_so_and_refuses_to_invent(self):
        """The failure this whole session kept finding: no ground truth
        is exactly where fabrication comes from."""
        result = await self.ask.run({"request": ""}, ctx=self.ctx)
        self.assertTrue(result.ok)
        self.assertIn("nothing", result.output)
        self.assertIn("do NOT describe", result.output)

    async def test_it_gives_back_what_was_said(self):
        self._heard("it isn't fair you get pizza")
        result = await self.ask.run({"request": ""}, ctx=self.ctx)
        self.assertIn("Ira: it isn't fair you get pizza", result.output)
        self.assertEqual(result.metadata["lines"], 1)

    async def test_it_can_be_asked_about_one_person(self):
        self._heard("hers", speaker="Ira")
        self._heard("his", speaker="Aran")
        result = await self.ask.run({"request": "from Aran"}, ctx=self.ctx)
        self.assertIn("his", result.output)
        self.assertNotIn("hers", result.output)

    async def test_a_number_is_read_as_hours(self):
        import time

        now = time.time()
        self._heard("ages ago", at=now - 5 * 3600)
        self._heard("just now", at=now - 60)
        result = await self.ask.run({"request": "2 hours"}, ctx=self.ctx)
        self.assertIn("just now", result.output)
        self.assertNotIn("ages ago", result.output)

    async def test_memos_can_be_asked_for_alone(self):
        self._heard("ordinary chatter")
        self._heard("the gate code is 4417", kind="memo")
        result = await self.ask.run({"request": "memos"}, ctx=self.ctx)
        self.assertIn("4417", result.output)
        self.assertNotIn("ordinary chatter", result.output)

    async def test_asking_is_genuinely_read_only(self):
        """Guardian believes this label."""
        self.assertTrue(OverheardTool.read_only)
        self.assertEqual(OverheardTool.reversibility, "read_only")


class KeepingAndForgettingTestCase(_ToolTestCase):
    async def test_a_memo_is_kept(self):
        result = await self.note.run({"request": "memo the gate code is 4417"}, ctx=self.ctx)
        self.assertTrue(result.ok)
        kept = store.recall(kind="memo", folder=self.folder)
        self.assertEqual([k["text"] for k in kept], ["the gate code is 4417"])

    async def test_an_empty_memo_is_refused(self):
        result = await self.note.run({"request": "memo"}, ctx=self.ctx)
        self.assertFalse(result.ok)

    async def test_wipe_forgets_everything_and_says_how_many(self):
        self._heard("a")
        self._heard("b", speaker="Aran")
        result = await self.note.run({"request": "wipe"}, ctx=self.ctx)
        self.assertEqual(result.metadata["forgotten"], 2)
        self.assertEqual(store.recall(folder=self.folder), [])

    async def test_wipe_can_name_one_person(self):
        self._heard("hers", speaker="Ira")
        self._heard("his", speaker="Aran")
        await self.note.run({"request": "wipe Ira"}, ctx=self.ctx)
        left = store.recall(folder=self.folder)
        self.assertEqual([x["speaker"] for x in left], ["Aran"])

    async def test_the_count_is_the_real_one(self):
        """"I'll wipe it from the record" with nothing behind it is the
        failure this project has paid for before."""
        result = await self.note.run({"request": "wipe"}, ctx=self.ctx)
        self.assertEqual(result.metadata["forgotten"], 0)
        self.assertIn("0", result.output)

    async def test_anything_else_is_refused_rather_than_guessed(self):
        result = await self.note.run({"request": "do something clever"}, ctx=self.ctx)
        self.assertFalse(result.ok)

    async def test_the_label_matches_the_worst_thing_it_can_do(self):
        """It can delete, so it is irreversible -- not "reversible"
        because keeping a memo happens to be harmless."""
        self.assertEqual(OverheardNoteTool.reversibility, "irreversible")
        self.assertFalse(OverheardNoteTool.read_only)


if __name__ == "__main__":
    unittest.main()
