"""Consolidation must summarise the window, never answer it (observer
wave, 2026-09-10).

`run_consolidation` used to send Cognition exactly one message: the
episodic window pasted in as `role: "user"`, with nothing said about
what to do with it. `purpose="consolidate"` only picks a budget, so
nothing anywhere told the model this was a transcript rather than a
question. In a real 22-turn CLI session whose window happened to end on
home-lab talk, the model did the obvious thing and answered it. What
got stored as `memory:semantic:1`, tagged `consolidation`, was:

    "Good question -- and it's one of the most important decisions for a
     home lab, because remote access is the most common thing people get
     wrong. ... **1. Tailscale (easiest, and what I'd suggest first)**
     A mesh VPN based on WireGuard. ..."

The human had never mentioned remote access or Tailscale. Recall handed
that back as a memory and Sim reported it as history -- including, after
a restart and when asked to "be precise", "Yes -- precisely once ...
That's the only exchange we've had on the topic."

A fabrication written into durable memory is indistinguishable from a
real one forever after, which makes this the worst place in the system
for the honesty rule to fail. The module's own promise -- "never a
fabricated distillation" -- was only ever enforced against the *floor*
path; a real provider was free to invent whatever it liked because
nobody had asked it not to.
"""

from __future__ import annotations

import unittest

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.consolidation import DISTILL_INSTRUCTION, NOTHING, run_consolidation
from simorgh.memory.store import MemoryEngine
from tests.simorgh.helpers import FakeClock


class TestConsolidationAsksForASummary(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(half_life_seconds=1_000_000.0), clock=self.clock)
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", clock=self.clock)
        await self.bus.start()
        self.seen: list[list[dict]] = []

    async def asyncTearDown(self):
        await self.bus.stop()

    async def _consolidate(self, answer: str):
        async def _answer_think(message: Message) -> None:
            self.seen.append(list(message.payload["messages"]))
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": answer, "tool_calls": [], "provider": "fake", "cost_usd": 0.0,
                "tokens": 10, "floor": False, "non_answer": False,
            })

        sub = await self.bus.subscribe(topics.COGNITION_THINK, _answer_think)
        try:
            return await run_consolidation(
                self.engine, bus=self.bus, source="memory",
                keep_per_kind={"episodic": 100, "semantic": 100})
        finally:
            await sub.unsubscribe()

    async def test_the_window_is_not_the_only_thing_the_model_is_sent(self):
        """The bug in one assertion: the request used to be the bare
        transcript, so the model had nothing to distinguish it from a
        question."""
        await self.engine.store(kind="episodic", content="User: what about remote access?",
                                tags=[], source_ref="", confidence=1.0)
        await self._consolidate("a summary")

        self.assertEqual(len(self.seen), 1)
        messages = self.seen[0]
        self.assertGreater(len(messages), 1, "the window travelled alone -- nothing said not to answer it")
        instructions = " ".join(m["content"] for m in messages if m["role"] == "system")
        self.assertIn(DISTILL_INSTRUCTION, instructions)
        # And the framing survives even for a provider that drops system
        # messages: it is repeated on the user turn.
        window_turn = messages[-1]["content"]
        self.assertIn("do not answer", window_turn.lower())
        self.assertIn("what about remote access?", window_turn)

    async def test_a_model_with_nothing_to_record_is_not_stored(self):
        """`NOTHING` is a real answer. Storing it would be the same class
        of mistake as storing the essay: durable memory filled with
        something nobody said."""
        await self.engine.store(kind="episodic", content="User: hello", tags=[], source_ref="", confidence=1.0)
        report = await self._consolidate(NOTHING)

        self.assertFalse(report.distilled)
        items, _ = await self.engine.retrieve(query="", kinds=["semantic"], k=10, filters=None)
        self.assertEqual(items, [])

    async def test_an_empty_reply_is_not_stored(self):
        await self.engine.store(kind="episodic", content="User: hello", tags=[], source_ref="", confidence=1.0)
        report = await self._consolidate("   ")

        self.assertFalse(report.distilled)
        items, _ = await self.engine.retrieve(query="", kinds=["semantic"], k=10, filters=None)
        self.assertEqual(items, [])

    async def test_a_distillation_is_tagged_as_one(self):
        """Whatever else is true of the stored record, a reader must be
        able to tell a distillation from a thing that happened. It could
        not before: the fabricated Tailscale essay looked exactly like a
        remembered exchange."""
        await self.engine.store(kind="episodic", content="User: hello", tags=[], source_ref="", confidence=1.0)
        report = await self._consolidate("The human greeted Sim.")

        self.assertTrue(report.distilled)
        items, _ = await self.engine.retrieve(query="", kinds=["semantic"], k=10, filters=None)
        self.assertEqual(len(items), 1)
        self.assertIn("distilled", items[0].tags)
        self.assertIn("consolidation", items[0].tags)


if __name__ == "__main__":
    unittest.main()
