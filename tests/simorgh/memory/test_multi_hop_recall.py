"""Stage 15 item 2: recall follows facts one or two hops.

"Number of whoever fixed the boiler" names no person, and the fact with
the number names no boiler. Neither the literal fact match nor a
similarity score joins them; following `boiler -> fixed by -> Reza` to
`Reza -> phone number -> ...` does. These pin that join over the bus, that
`graph_hops = 0` leaves the facts block byte for byte as it was, the cap
and its order, and that a hop never crosses `person_scope`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.facts import Fact
from simorgh.memory.recall import hop_facts
from simorgh.memory.service import Service
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class TheWalkTestCase(unittest.TestCase):
    """`recall.hop_facts` on its own: hop order, the cap, exclusion."""

    FACTS = [
        Fact(id="f1", subject="boiler", predicate="fixed by", object="Reza", valid_from=1.0),
        Fact(id="f2", subject="Reza", predicate="phone", object="0912", valid_from=2.0),
        Fact(id="f3", subject="Reza", predicate="works for", object="Pars Heating", valid_from=3.0),
        Fact(id="f4", subject="Pars Heating", predicate="address", object="Vali Asr 12", valid_from=4.0),
    ]
    ENDS = {"f1": ("boiler", "reza"), "f2": ("reza", ""), "f3": ("reza", "pars"), "f4": ("pars", "")}

    def walk(self, **kw):
        return [(f.id, hop) for f, hop in hop_facts(self.FACTS, start=["boiler"], ends=lambda f: self.ENDS[f.id], **kw)]

    def test_two_hops_and_no_third(self):
        self.assertEqual(self.walk(), [("f1", 1), ("f3", 2), ("f2", 2)])

    def test_one_hop(self):
        self.assertEqual(self.walk(hops=1), [("f1", 1)])

    def test_zero_hops_is_nothing(self):
        self.assertEqual(self.walk(hops=0), [])

    def test_the_cap_counts_every_fact_and_hop_1_comes_first(self):
        self.assertEqual(self.walk(limit=2), [("f1", 1), ("f3", 2)])

    def test_an_excluded_fact_is_not_returned_but_is_still_the_bridge(self):
        self.assertEqual(self.walk(exclude={"f1"}), [("f3", 2), ("f2", 2)])

    def test_via_names_the_entity_each_fact_was_reached_through(self):
        via: dict = {}
        self.walk(via=via)
        self.assertEqual(via, {"f1": "boiler", "f3": "reza", "f2": "reza"})


class _ServiceCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", ledger=self.ledger, clock=self.clock)
        await self.bus.start()
        self.service = None

    async def asyncTearDown(self):
        if self.service is not None:
            await self.service.stop()
        await self.bus.stop()
        self._tmp.cleanup()

    async def boot(self, config: Config) -> Service:
        if self.service is not None:
            await self.service.stop()
        ctx = Context(name="memory", instance_id="", run_id="test", mode="single", bus=self.bus, ledger=self.ledger,
                      config={}, secrets={}, clock=self.clock, logger=_Logger(),
                      data_dir=Path(self._tmp.name) / "data")
        self.service = Service(config=config)
        await self.service.start(ctx)
        return self.service

    async def ask(self, query: str, person: str = "") -> list[dict]:
        payload = {"query": query, "kinds": ["episodic"], "k": 5}
        if person:
            payload["filters"] = {"tags": [f"person:{person}"]}
        reply = await self.bus.request(Message.new(topics.MEMORY_RETRIEVE, source="test", payload=payload),
                                       timeout=5.0)
        return list(reply.payload.get("facts") or [])


class TheBoilerTestCase(_ServiceCase):
    async def test_the_number_of_whoever_fixed_the_boiler(self):
        service = await self.boot(Config(entities=True))
        await service.engine.store_fact(subject="the boiler", predicate="was fixed by", object="Reza")
        await service.engine.store_fact(subject="Reza", predicate="phone number", object="0912 345 6789")
        facts = await self.ask("what's the number of whoever fixed the boiler?")
        lines = {(f["subject"], f["object"]): f.get("hop") for f in facts}
        self.assertIn(("the boiler", "Reza"), lines)
        self.assertIn(("Reza", "0912 345 6789"), lines)
        self.assertEqual(lines[("Reza", "0912 345 6789")], 2)
        self.assertEqual([f.get("via") for f in facts if f["object"] == "0912 345 6789"], ["Reza"])
        self.assertIsNone(lines[("the boiler", "Reza")], "found by its words: not a hop, not marked")

    async def test_soo_is_found_by_a_question_about_soodeh_over_the_bus(self):
        service = await self.boot(Config(entities=True))
        await service.engine.entity_for("Soodeh")
        await service.engine.add_alias("person:soodeh", "Soo")
        await service.engine.store_fact(subject="Soo", predicate="likes", object="green tea")
        facts = await self.ask("what does Soodeh like to drink?")
        self.assertEqual([(f["subject"], f.get("hop")) for f in facts], [("Soo", 1)])

    async def test_without_the_walk_the_number_is_not_found(self):
        service = await self.boot(Config(entities=True, graph_hops=1))
        await service.engine.store_fact(subject="the boiler", predicate="was fixed by", object="Reza")
        await service.engine.store_fact(subject="Reza", predicate="phone number", object="0912 345 6789")
        facts = await self.ask("what's the number of whoever fixed the boiler?")
        self.assertNotIn("0912 345 6789", [f["object"] for f in facts])

    async def test_graph_max_facts_caps_what_the_walk_adds(self):
        service = await self.boot(Config(entities=True, graph_max_facts=2))
        await service.engine.store_fact(subject="the boiler", predicate="was fixed by", object="Reza")
        for i in range(5):
            await service.engine.store_fact(subject="Reza", predicate=f"note {i}", object=f"thing {chr(97 + i)}")
        facts = await self.ask("who fixed the boiler?")
        self.assertEqual(len([f for f in facts if "hop" in f]), 2)


class TheSummaryLineTestCase(_ServiceCase):
    """Stage 15 item 3's recall half: one line per entity the query names."""

    async def test_a_summary_rides_in_the_block_once(self):
        service = await self.boot(Config(entities=True))
        await service.engine.store_fact(subject="Reza", predicate="phone number", object="0912 345 6789")
        await service.engine._entity_event("entity.summary", {  # noqa: SLF001
            "id": "person:reza", "summary": "Reza is the plumber.", "person_scope": "*", "fact_ids": []}, "t")
        facts = await self.ask("ask Reza, Reza knows")
        lines = [f for f in facts if f.get("summary")]
        self.assertEqual([(f["entity"], f["object"]) for f in lines], [("person:reza", "Reza is the plumber.")])
        await self.boot(Config(entities=True, graph_hops=0))
        self.assertFalse([f for f in await self.ask("ask Reza") if f.get("summary")])


class ZeroHopsIsTodaysBlockTestCase(_ServiceCase):
    QUERIES = [("what's the number of whoever fixed the boiler?", ""), ("when is my birthday", "Saeed"),
               ("what does Soodeh like?", "Soodeh"), ("who fixed the boiler", "Iris"), ("", "")]

    async def _replies(self):
        return [json.dumps(await self.ask(q, p), sort_keys=True) for q, p in self.QUERIES]

    async def test_graph_hops_0_reproduces_the_block_byte_for_byte(self):
        service = await self.boot(Config(entities=True))
        await service.engine.store_fact(subject="the boiler", predicate="was fixed by", object="Reza")
        await service.engine.store_fact(subject="Reza", predicate="phone number", object="0912 345 6789")
        await service.engine.store_fact(subject="Saeed birthday", predicate="is", object="March 6th",
                                        person_scope="Saeed")
        await service.engine.store_fact(subject="Soodeh", predicate="likes", object="green tea",
                                        person_scope="Soodeh")
        await self.boot(Config(entities=True, graph_hops=0))
        zero = await self._replies()
        await self.boot(Config())
        today = await self._replies()
        self.assertEqual(zero, today)
        await self.boot(Config(entities=True))
        self.assertNotEqual(await self._replies(), today, "the walk is on by default with entities")


class HopsNeverCrossPersonScopeTestCase(_ServiceCase):
    async def test_a_private_fact_is_never_reached_at_the_second_hop(self):
        service = await self.boot(Config(entities=True))
        await service.engine.store_fact(subject="the boiler", predicate="was fixed by", object="Reza")
        await service.engine.store_fact(subject="Reza", predicate="phone number", object="0912 345 6789",
                                        person_scope="Saeed")
        iris = await self.ask("what's the number of whoever fixed the boiler?", person="Iris")
        self.assertNotIn("0912 345 6789", [f["object"] for f in iris])
        saeed = await self.ask("what's the number of whoever fixed the boiler?", person="Saeed")
        self.assertIn("0912 345 6789", [f["object"] for f in saeed])

    async def test_a_private_fact_is_never_the_bridge(self):
        """Soodeh's doctor is hers to tell. The doctor's number is household
        knowledge, but reaching it from "Soodeh" would say who her doctor is."""
        service = await self.boot(Config(entities=True))
        await service.engine.store_fact(subject="Soodeh", predicate="sees doctor", object="Dr Amini",
                                        person_scope="Soodeh")
        await service.engine.store_fact(subject="Dr Amini", predicate="clinic phone", object="021 555 0101")
        for asker in ("Iris", "Saeed", ""):
            facts = await self.ask("anything about Soodeh's health?", person=asker)
            self.assertEqual([f for f in facts if f["object"] in ("Dr Amini", "021 555 0101")], [], asker)
        hers = await self.ask("anything about Soodeh's health?", person="Soodeh")
        self.assertIn("021 555 0101", [f["object"] for f in hers])


if __name__ == "__main__":
    unittest.main()
