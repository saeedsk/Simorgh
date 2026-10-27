"""Core memory blocks (stage 15 item 8, `memory/core.py`).

Letta's core tier: one small block per person and one for the household,
always in a chat turn's context and kept current by the model itself
through `memory_core_edit`. Each edit is a `core.edited` event on
`memory:core` with the text it replaced and the turn it came from; a person
edits only their own block or `household`. Off by default, and off the
reply carries no `core`, so the prompt is what it was.
"""

from __future__ import annotations

import asyncio
import tempfile
import types
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.people import Person
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config as MemoryConfig
from simorgh.memory.core import CORE_STREAM, EDITED, apply_edit, block_for, requester_name
from simorgh.memory.service import Service
from tests.simorgh.helpers import FakeClock

PEOPLE = (Person("saeed", "Saeed", role="owner"), Person("soodeh", "Soodeh", role="adult"),
          Person("ira", "Ira", role="child"))


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class _CoreCase(unittest.IsolatedAsyncioTestCase):
    CONFIG = MemoryConfig(core_blocks=True, core_block_chars=120, consolidate_after_start_s=0)

    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", ledger=self.ledger, clock=self.clock)
        await self.bus.start()
        ctx = Context(name="memory", instance_id="", run_id="test", mode="single", bus=self.bus,
                      ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=_Logger(),
                      data_dir=Path(self._tmp.name) / "data")
        self.service = Service(config=self.CONFIG)
        await self.service.start(ctx)
        self.service.engine.people = PEOPLE

    async def asyncTearDown(self):
        await self.service.stop()
        await self.bus.stop()
        self._tmp.cleanup()

    async def recall(self, **extra) -> dict:
        reply = await self.bus.request(Message.new(topics.MEMORY_RETRIEVE, source="test", payload={
            "query": "", "kinds": ["episodic"], "k": 6, **extra}), timeout=5.0)
        return dict(reply.payload)

    async def edit(self, block: str, old: str, new: str, *, requester: str, turn: str = "turn-1",
                   channel: str = "") -> dict:
        """One `memory.core.edit`, its reply read back as `edit_core`'s
        `{ok, block, text, error}`."""
        reply = await self.bus.request(Message.new(topics.MEMORY_CORE_EDIT, source="execution", payload={
            "block": block, "old": old, "new": new, "requester": requester, "requester_channel": channel,
            "source_ref": turn, "action_id": "a-1"}), timeout=5.0)
        self.assertEqual(reply.type, topics.MEMORY_CORE_EDIT_REPLY)
        payload = reply.payload
        return {"ok": payload["edited"], "block": payload["block"], "text": payload["text"],
                "error": payload["reason"]}


class OffByDefaultTestCase(_CoreCase):
    CONFIG = MemoryConfig(consolidate_after_start_s=0)

    def test_the_default_is_off(self):
        self.assertFalse(MemoryConfig().core_blocks)
        self.assertEqual(MemoryConfig().core_block_chars, 600)

    async def test_off_a_recall_carries_no_core_and_an_edit_is_refused(self):
        self.assertNotIn("core", await self.recall(core_for="Saeed"))
        result = await self.edit("household", "", "bins go out Tuesday", requester="Saeed")
        self.assertFalse(result["ok"])
        self.assertIn("off", result["error"])
        self.assertEqual(await self.ledger.read(CORE_STREAM), [])


class BlocksTestCase(_CoreCase):
    async def test_on_with_no_block_the_list_is_empty(self):
        """Empty says "on": the turn is offered the tool, and nothing is rendered."""
        self.assertEqual((await self.recall(core_for="Saeed"))["core"], [])

    async def test_a_recall_that_does_not_ask_gets_none(self):
        await self.edit("household", "", "bins go out Tuesday", requester="Saeed")
        self.assertNotIn("core", await self.recall())

    async def test_an_edit_is_an_event_with_its_source_turn_and_what_it_replaced(self):
        first = await self.edit("me", "", "prefers Farsi", requester="Soodeh", turn="turn-7")
        self.assertTrue(first["ok"], first)
        self.assertEqual(first["block"], "person:soodeh")
        second = await self.edit("me", "prefers Farsi", "prefers Farsi; tea, not coffee", requester="Soodeh",
                                 turn="turn-9")
        self.assertTrue(second["ok"], second)
        events = await self.ledger.read(CORE_STREAM)
        self.assertEqual([e.type for e in events], [EDITED, EDITED])
        last = events[-1].payload
        self.assertEqual(last["source_ref"], "turn-9")
        self.assertEqual(last["by"], "Soodeh")
        self.assertEqual(last["previous"], "prefers Farsi")
        self.assertEqual(last["text"], "prefers Farsi; tea, not coffee")

    async def test_a_turn_sees_the_household_block_and_its_own_only(self):
        await self.edit("household", "", "bins go out Tuesday", requester="Saeed")
        await self.edit("me", "", "prefers Farsi", requester="Soodeh")
        await self.edit("me", "", "has soccer on Saturdays", requester="Ira")
        core = (await self.recall(core_for="Soodeh"))["core"]
        self.assertEqual([(b["block"], b["text"]) for b in core],
                         [("household", "bins go out Tuesday"), ("person:soodeh", "prefers Farsi")])
        ira = (await self.recall(core_for="Ira"))["core"]
        self.assertNotIn("prefers Farsi", str(ira))

    async def test_the_console_is_the_owners(self):
        await self.edit("me", "", "works late on Thursdays", requester="")
        core = (await self.recall(core_for=""))["core"]
        self.assertEqual([b["block"] for b in core], ["person:saeed"])
        self.assertEqual(core[0]["label"], "Saeed")

    async def test_nobody_edits_somebody_elses_block(self):
        await self.edit("me", "", "prefers Farsi", requester="Soodeh")
        for block in ("Soodeh", "person:soodeh"):
            result = await self.edit(block, "prefers Farsi", "prefers English", requester="Ira")
            self.assertFalse(result["ok"])
            self.assertIn("not yours", result["error"])
        self.assertEqual((await self.recall(core_for="Soodeh"))["core"][0]["text"], "prefers Farsi")

    async def test_an_unplaced_voice_edits_nothing(self):
        result = await self.edit("household", "", "the door code is 1234", requester="unknown")
        self.assertFalse(result["ok"])
        self.assertEqual(await self.ledger.read(CORE_STREAM), [])

    async def test_a_person_edits_their_own_block_and_the_households(self):
        for requester in ("Soodeh", "Ira"):
            self.assertTrue((await self.edit("me", "", f"{requester} note", requester=requester, channel="voice"))["ok"])
            self.assertTrue((await self.edit(requester, f"{requester} note", f"{requester} notes",
                                             requester=requester, channel="voice"))["ok"])
            self.assertTrue((await self.edit("household", "", f"from {requester}", requester=requester,
                                             channel="voice"))["ok"])

    async def test_an_outside_channel_edits_nothing(self):
        """The A2A server acts for a device's person; core memory is not theirs to write."""
        for block in ("household", "me"):
            result = await self.edit(block, "", "the door code is 1234", requester="Saeed", channel="a2a")
            self.assertFalse(result["ok"])
            self.assertIn("outside", result["error"])
        self.assertEqual(await self.ledger.read(CORE_STREAM), [])

    async def test_nobody_named_off_the_console_edits_nothing(self):
        """"" is the owner's only on the console; on a voice it is a voice nobody placed."""
        for channel in ("voice", "initiative", "planning"):
            result = await self.edit("household", "", "x", requester="", channel=channel)
            self.assertFalse(result["ok"], channel)
        self.assertEqual(await self.ledger.read(CORE_STREAM), [])

    async def test_the_old_retrieve_key_edits_nothing(self):
        """Until 2026-10-27 the edit rode on `memory.retrieve` as `core_edit`.
        Nothing persisted that shape, so it is not read: a retrieve carrying
        it is an ordinary recall, and only Execution may publish the edit."""
        reply = await self.bus.request(Message.new(topics.MEMORY_RETRIEVE, source="test", payload={
            "query": "", "kinds": [], "k": 0,
            "core_edit": {"block": "household", "old": "", "new": "x", "requester": "Saeed"}}), timeout=5.0)
        self.assertNotIn("core_edit", reply.payload)
        self.assertEqual(await self.ledger.read(CORE_STREAM), [])
        self.assertFalse(topics.may_publish("orchestration", topics.MEMORY_CORE_EDIT))
        self.assertTrue(topics.may_publish("execution", topics.MEMORY_CORE_EDIT))

    async def test_a_block_over_the_limit_is_refused_whole(self):
        await self.edit("household", "", "bins go out Tuesday", requester="Saeed")
        result = await self.edit("household", "", "x" * 200, requester="Saeed")
        self.assertFalse(result["ok"])
        self.assertIn("limit is 120", result["error"])
        self.assertEqual(result["text"], "bins go out Tuesday")

    async def test_an_edit_is_undone_by_another(self):
        await self.edit("household", "", "bins go out Tuesday", requester="Saeed")
        await self.edit("household", "Tuesday", "Wednesday", requester="Saeed")
        await self.edit("household", "Wednesday", "Tuesday", requester="Saeed")
        self.assertEqual((await self.recall(core_for="Saeed"))["core"][0]["text"], "bins go out Tuesday")
        self.assertEqual(len(await self.ledger.read(CORE_STREAM)), 3)

    async def test_edits_at_once_each_start_from_the_last(self):
        """Two calls in one think run side by side; a ledger that yields
        (sqlite, jsonl) between the read and the append must not lose one."""
        await self.edit("household", "", "bins go out Tuesday", requester="Saeed")
        engine, ledger = self.service.engine, self.ledger
        read, append = ledger.read, ledger.append

        async def slow_read(*a, **kw):
            await asyncio.sleep(0.01)
            return await read(*a, **kw)

        async def slow_append(*a, **kw):
            await asyncio.sleep(0.01)
            return await append(*a, **kw)

        engine._ledger = types.SimpleNamespace(read=slow_read, append=slow_append)
        try:
            results = await asyncio.gather(*(engine.edit_core(block="household", old="", new=f"note {i}",
                                                              requester="Saeed") for i in range(4)))
        finally:
            engine._ledger = ledger
        self.assertTrue(all(r["ok"] for r in results), results)
        text = (await self.recall(core_for="Saeed"))["core"][0]["text"]
        for i in range(4):
            self.assertIn(f"note {i}", text)
        events = await ledger.read(CORE_STREAM)
        self.assertEqual([e.payload["previous"] for e in events[1:]], [e.payload["text"] for e in events[:-1]])

    async def test_the_blocks_survive_a_restart(self):
        await self.edit("household", "", "bins go out Tuesday", requester="Saeed")
        await self.service.stop()
        self.service = Service(config=self.CONFIG)
        await self.service.start(Context(name="memory", instance_id="", run_id="test", mode="single", bus=self.bus,
                                         ledger=self.ledger, config={}, secrets={}, clock=self.clock,
                                         logger=_Logger(), data_dir=Path(self._tmp.name) / "data"))
        self.service.engine.people = PEOPLE
        self.assertEqual((await self.recall(core_for="Saeed"))["core"][0]["text"], "bins go out Tuesday")


class ReplaceRulesTestCase(unittest.TestCase):
    def test_old_must_be_there_exactly_once(self):
        self.assertIn("not in the block", apply_edit("tea", "coffee", "milk", limit=600)[1])
        self.assertIn("2 times", apply_edit("tea\ntea", "tea", "milk", limit=600)[1])

    def test_empty_old_appends_a_line_and_empty_new_removes_one(self):
        self.assertEqual(apply_edit("tea", "", "Farsi", limit=600), ("tea\nFarsi", ""))
        self.assertEqual(apply_edit("tea\nFarsi", "tea", "", limit=600), ("Farsi", ""))

    def test_nothing_to_do_is_said(self):
        self.assertTrue(apply_edit("tea", "", "", limit=600)[1])
        self.assertIn("already", apply_edit("tea", "tea", "tea", limit=600)[1])

    def test_whose_block(self):
        self.assertEqual(block_for("me", "Soodeh"), "person:soodeh")
        self.assertEqual(block_for("Household", "Ira"), "household")
        self.assertEqual(block_for("Soodeh", "Ira"), "")
        self.assertEqual(requester_name("", PEOPLE), "Saeed")
        self.assertEqual(requester_name("unknown", PEOPLE), "")
        self.assertEqual(requester_name("", PEOPLE, channel="voice"), "")
        self.assertEqual(requester_name("Saeed", PEOPLE, channel="a2a"), "")


if __name__ == "__main__":
    unittest.main()
