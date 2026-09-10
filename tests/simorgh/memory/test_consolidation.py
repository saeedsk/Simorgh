"""`run_consolidation` (docs/blueprint/subsystems/05-memory.md section
4): flag contradictions, prune each kind, and -- only if a real
Cognition answers -- distill the window's episodic activity. Degrades
honestly: unreachable or floor:true Cognition is never fabricated into a
distillation (principle 4.5)."""

from __future__ import annotations

import unittest

from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.consolidation import run_consolidation
from simorgh.memory.store import MemoryEngine
from tests.simorgh.helpers import FakeClock


class TestRunConsolidation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(half_life_seconds=1_000_000.0), clock=self.clock)
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", clock=self.clock)
        await self.bus.start()

    async def asyncTearDown(self):
        await self.bus.stop()

    async def test_no_episodic_activity_never_calls_cognition(self):
        report = await run_consolidation(self.engine, bus=self.bus, source="memory", keep_per_kind={"episodic": 100})
        self.assertFalse(report.distilled)
        self.assertEqual(report.contradictions, [])

    async def test_cognition_unreachable_is_a_skipped_cycle_never_a_crash(self):
        await self.engine.store(kind="episodic", content="something happened", tags=[], source_ref="", confidence=1.0)
        report = await run_consolidation(
            self.engine, bus=self.bus, source="memory", keep_per_kind={"episodic": 100, "semantic": 100},
            cognition_timeout=0.05,
        )
        self.assertFalse(report.distilled)

    async def test_a_real_cognition_reply_is_stored_as_a_semantic_distillation(self):
        await self.engine.store(kind="episodic", content="the user asked about the weather", tags=[], source_ref="", confidence=1.0)

        async def _answer_think(message: Message) -> None:
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": "distilled: the user is interested in weather", "tool_calls": [], "provider": "fake",
                "cost_usd": 0.0, "tokens": 10, "floor": False, "non_answer": False,
            })

        sub = await self.bus.subscribe(topics.COGNITION_THINK, _answer_think)
        try:
            report = await run_consolidation(
                self.engine, bus=self.bus, source="memory", keep_per_kind={"episodic": 100, "semantic": 100},
            )
        finally:
            await sub.unsubscribe()

        self.assertTrue(report.distilled)
        items, _ = await self.engine.retrieve(query="weather", kinds=["semantic"], k=5, filters=None)
        self.assertEqual(len(items), 1)
        self.assertIn("distilled", items[0].content)
        self.assertIn("consolidation", items[0].tags)

    async def test_a_floor_true_reply_is_never_fabricated_into_a_distillation(self):
        await self.engine.store(kind="episodic", content="something happened", tags=[], source_ref="", confidence=1.0)

        async def _answer_floor(message: Message) -> None:
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": "[floor] no real reviewer available", "tool_calls": [], "provider": "floor",
                "cost_usd": 0.0, "tokens": 0, "floor": True, "non_answer": False,
            })

        sub = await self.bus.subscribe(topics.COGNITION_THINK, _answer_floor)
        try:
            report = await run_consolidation(
                self.engine, bus=self.bus, source="memory", keep_per_kind={"episodic": 100, "semantic": 100},
            )
        finally:
            await sub.unsubscribe()

        self.assertFalse(report.distilled)
        items, _ = await self.engine.retrieve(query="", kinds=["semantic"], k=5, filters=None)
        self.assertEqual(items, [])

    async def test_contradictions_are_flagged_during_consolidation(self):
        await self.engine.store(kind="semantic", content="the sky is blue", tags=["sky"], source_ref="", confidence=1.0)
        self.clock.advance(1.0)
        await self.engine.store(kind="semantic", content="the sky is green", tags=["sky"], source_ref="", confidence=1.0)
        report = await run_consolidation(
            self.engine, bus=self.bus, source="memory", keep_per_kind={"episodic": 100, "semantic": 100},
        )
        self.assertEqual(len(report.contradictions), 1)

    async def test_pruning_reports_how_many_records_were_tombstoned_per_kind(self):
        for i in range(5):
            await self.engine.store(kind="episodic", content=f"e{i}", tags=[], source_ref="", confidence=1.0)
        report = await run_consolidation(
            self.engine, bus=self.bus, source="memory", keep_per_kind={"episodic": 2}, cognition_timeout=0.05,
        )
        self.assertEqual(report.pruned["episodic"], 3)

    async def test_a_second_pass_prunes_nothing_and_says_so(self):
        """Pruning has to be idempotent, and it was not.

        `prune` ranked EVERY record in the stream, tombstoned or not, so
        each pass re-tombstoned the same records: a fresh
        `memory:tombstones` event listing all of them, and a report
        claiming to have pruned records that were forgotten passes ago.
        Nobody noticed while consolidation only ran on a six-hourly
        sleep tick that no session lived to see; `consolidate_after_
        start_s` made it run at every boot, so the claim and the write
        both became routine (observer, 2026-09-10).
        """
        from simorgh.memory.store import TOMBSTONE_STREAM

        for i in range(5):
            await self.engine.store(kind="episodic", content=f"e{i}", tags=[], source_ref="", confidence=1.0)
        first = await run_consolidation(
            self.engine, bus=self.bus, source="memory", keep_per_kind={"episodic": 2}, cognition_timeout=0.05)
        second = await run_consolidation(
            self.engine, bus=self.bus, source="memory", keep_per_kind={"episodic": 2}, cognition_timeout=0.05)
        self.assertEqual(first.pruned["episodic"], 3)
        self.assertEqual(second.pruned["episodic"], 0, "nothing was left to forget")
        self.assertEqual(len(await self.ledger.read(TOMBSTONE_STREAM)), 1,
                         "a pass that forgot nothing must not write a tombstone")
        self.assertEqual((await self.engine.counts())["episodic"], 2)

    async def test_a_forgotten_record_does_not_hold_a_keep_slot(self):
        """`keep` counts what Sim still remembers. Counting tombstoned
        records towards it prunes live ones to make room for the dead."""
        for i in range(4):
            await self.engine.store(kind="episodic", content=f"e{i}", tags=[], source_ref="", confidence=1.0)
        refs = [f"memory:episodic:{seq}" for seq in (1, 2)]
        await self.engine.forget(refs, reason="by hand")
        pruned = await self.engine.prune(kind="episodic", keep=2)
        self.assertEqual(pruned, 0)
        self.assertEqual((await self.engine.counts())["episodic"], 2)

    async def test_since_scopes_which_episodic_records_feed_distillation(self):
        await self.engine.store(kind="episodic", content="old irrelevant event", tags=[], source_ref="", confidence=1.0)
        self.clock.advance(1000.0)
        await self.engine.store(kind="episodic", content="recent relevant event", tags=[], source_ref="", confidence=1.0)

        seen_messages = []

        async def _answer_think(message: Message) -> None:
            # `[-1]`, not `[0]`: the window is the LAST message now.
            # `run_consolidation` prepends a system instruction telling
            # the model this is a transcript to summarise rather than a
            # question to answer -- without it the model answered the
            # transcript and the answer was stored as a memory
            # (observer, 2026-09-10; see `DISTILL_INSTRUCTION`).
            seen_messages.append(message.payload["messages"][-1]["content"])
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": "ok", "tool_calls": [], "provider": "fake", "cost_usd": 0.0, "tokens": 1,
                "floor": False, "non_answer": False,
            })

        sub = await self.bus.subscribe(topics.COGNITION_THINK, _answer_think)
        try:
            await run_consolidation(
                self.engine, bus=self.bus, source="memory",
                keep_per_kind={"episodic": 100, "semantic": 100}, since=self.clock.now() - 1.0,
            )
        finally:
            await sub.unsubscribe()

        self.assertEqual(len(seen_messages), 1)
        self.assertIn("recent relevant event", seen_messages[0])
        self.assertNotIn("old irrelevant event", seen_messages[0])


if __name__ == "__main__":
    unittest.main()
