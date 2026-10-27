"""Stage 15 item 3: entity summaries, written on the sleep tick.

A summary is durable and recall hands it back as what Sim knows, so it is
held to its facts the way a distillation is held to its transcript: one
naming a specific its facts never did is dropped whole. The floor provider
writes none and the pass says it skipped. A private fact is never folded
into a summary, because a summary is one line anybody's recall may carry.
"""

from __future__ import annotations

import unittest

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.consolidation import run_consolidation
from simorgh.memory.entities import ENTITY_STREAM
from simorgh.memory.store import MemoryEngine
from tests.simorgh.helpers import FakeClock


class SummariesTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(entities=True), clock=self.clock)
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", clock=self.clock)
        await self.bus.start()
        self.asked: list[str] = []
        await self.engine.store_fact(subject="the boiler", predicate="was fixed by", object="Reza")
        await self.engine.store_fact(subject="Reza", predicate="phone number", object="0912 345 6789")

    async def asyncTearDown(self):
        await self.bus.stop()

    async def _pass(self, answer, *, floor: bool = False):
        async def _think(message: Message) -> None:
            self.asked.append(message.payload["messages"][-1]["content"])
            text = answer(message.payload["messages"][-1]["content"]) if callable(answer) else answer
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": text, "tool_calls": [], "provider": "floor" if floor else "fake", "cost_usd": 0.0,
                "tokens": 1, "floor": floor, "non_answer": False})

        sub = await self.bus.subscribe(topics.COGNITION_THINK, _think)
        try:
            return await run_consolidation(self.engine, bus=self.bus, source="memory",
                                           keep_per_kind={"episodic": 100}, cognition_timeout=5.0)
        finally:
            await sub.unsubscribe()

    async def _summaries(self) -> dict:
        return {e.payload["id"]: e.payload["summary"] for e in await self.ledger.read(ENTITY_STREAM)
                if e.type == "entity.summary"}

    @staticmethod
    def _honest(prompt: str) -> str:
        return ("Reza fixed the boiler; his phone number is 0912 345 6789." if "About: Reza" in prompt
                else "The boiler was fixed by Reza.")

    async def test_a_summary_is_written_and_recalled(self):
        report = await self._pass(self._honest)
        self.assertEqual(sorted(report.summaries.written), ["person:reza", "thing:boiler"])
        self.assertIn("0912", (await self._summaries())["person:reza"])
        found = await self.engine.entity_summaries("can you call Reza?")
        self.assertEqual([(e.id, s) for e, s in found],
                         [("person:reza", "Reza fixed the boiler; his phone number is 0912 345 6789.")])

    async def test_an_untraceable_summary_is_dropped(self):
        report = await self._pass(lambda prompt: "Reza (see `fix_log.py`, commit abc1234) is on 0912 999 0000.")
        self.assertEqual(report.summaries.written, [])
        self.assertIn("fix_log.py", report.summaries.refused["person:reza"])
        self.assertIn("999", report.summaries.refused["person:reza"], "an invented number is a specific too")
        self.assertEqual(await self._summaries(), {})

    async def test_the_floor_writes_none_and_reports_skipped(self):
        report = await self._pass("Reza is the plumber.", floor=True)
        self.assertEqual(report.summaries.written, [])
        self.assertEqual(report.summaries.skipped, 2)
        self.assertEqual(await self._summaries(), {})

    async def test_nothing_new_is_not_summarised_again(self):
        await self._pass(self._honest)
        self.asked.clear()
        report = await self._pass(self._honest)
        self.assertEqual((report.summaries.written, self.asked), ([], []))
        await self.engine.store_fact(subject="Reza", predicate="works for", object="Pars Heating")
        report = await self._pass(self._honest)
        self.assertIn("person:reza", report.summaries.written)

    async def test_a_private_fact_never_reaches_a_summary(self):
        await self.engine.store_fact(subject="Reza", predicate="owes", object="Saeed a favour", person_scope="Saeed")
        await self._pass(self._honest)
        self.assertFalse(any("favour" in prompt for prompt in self.asked), self.asked)

    async def test_entities_off_asks_for_no_summary(self):
        self.engine._config = Config()  # noqa: SLF001
        report = await self._pass(self._honest)
        self.assertEqual((report.summaries.written, report.summaries.skipped, self.asked), ([], 0, []))


if __name__ == "__main__":
    unittest.main()
