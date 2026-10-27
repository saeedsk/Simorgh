"""Stage 15 follow-up: "my son" resolves through the speaker's People
record (`contracts.people.Person.relations`).

Memory may not import World Model, so it asks for the People store over
the bus (`world.env.query{what: "people"}`, `Service.learn_people`). These
pin the whole path with a stand-in World Model answering the real
`Person.to_dict` shape: "my son" said by Saeed is Aran's entity and finds
what is known about Aran, marked as reached through him; said by somebody
whose record names no son, it is nobody; and a failed ask keeps what
Memory already knew.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.people import Person
from simorgh.contracts.protocols import Context
from simorgh.contracts.registry import error_reply_payload
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.service import Service
from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


PEOPLE = (
    Person(person_id="saeed", name="Saeed", role="owner", identities=("voice:saeed",),
           relations={"son": "Aran", "wife": "Soodeh"}),
    Person(person_id="soodeh", name="Soodeh", role="adult", identities=("voice:soodeh",)),
    Person(person_id="aran", name="Aran", role="child", identities=("voice:aran",)),
)


class KinOverTheBusTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", ledger=self.ledger, clock=self.clock)
        await self.bus.start()
        # World Model, as far as Memory can tell: the `people` query.
        self.world = make_client(backend, source="worldmodel", ledger=self.ledger, clock=self.clock)
        await self.world.start()
        self.answer: dict = {"ok": True, "facet": "people", "as_of": 0.0,
                             "people": [p.to_dict() for p in PEOPLE]}
        self.asked = 0

        async def _people(message):
            if (message.payload or {}).get("what") != "people":
                return
            self.asked += 1
            await self.world.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload=self.answer)

        await self.world.subscribe(topics.WORLD_ENV_QUERY, _people)
        ctx = Context(name="memory", instance_id="", run_id="test", mode="single", bus=self.bus, ledger=self.ledger,
                      config={}, secrets={}, clock=self.clock, logger=_Logger(),
                      data_dir=Path(self._tmp.name) / "data")
        self.service = Service(config=Config(entities=True, people_refresh_s=0))
        await self.service.start(ctx)

    async def asyncTearDown(self):
        await self.service.stop()
        await self.world.stop()
        await self.bus.stop()
        self._tmp.cleanup()

    async def ask(self, query: str, person: str) -> list[dict]:
        reply = await self.bus.request(Message.new(topics.MEMORY_RETRIEVE, source="test", payload={
            "query": query, "kinds": ["episodic"], "k": 5, "filters": {"tags": [f"person:{person}"]}}), timeout=5.0)
        return list(reply.payload.get("facts") or [])

    async def test_my_son_from_saeed_is_aran(self):
        self.assertTrue(await self.service.learn_people())
        engine = self.service.engine
        self.assertEqual(await engine.entity_for("Aran"), "person:aran")
        self.assertEqual(await engine.query_entities("what does my son like", speaker="Saeed"), ["person:aran"])
        await engine.store_fact(subject="Aran", predicate="likes", object="Lego robotics")
        facts = await self.ask("what does my son like?", "Saeed")
        found = [f for f in facts if f["object"] == "Lego robotics"]
        self.assertEqual(len(found), 1, facts)
        self.assertEqual((found[0].get("hop"), found[0].get("via")), (1, "Aran"))

    async def test_my_son_from_somebody_with_no_son_on_record_is_nobody(self):
        self.assertTrue(await self.service.learn_people())
        engine = self.service.engine
        await engine.store_fact(subject="Aran", predicate="likes", object="Lego robotics")
        self.assertEqual(await engine.query_entities("what does my son like", speaker="Soodeh"), [])
        facts = await self.ask("what does my son like?", "Soodeh")
        self.assertNotIn("Lego robotics", [f["object"] for f in facts])
        # ...and "his son", even from Saeed, is somebody else's.
        self.assertEqual(await engine.query_entities("what does his son like", speaker="Saeed"), [])

    async def test_before_world_model_answers_nobody_has_kin(self):
        # The roster in `contracts` knows the names and not one relation:
        # the creator asked that they be learnt, not assumed.
        self.assertEqual(await self.service.engine.query_entities("my son", speaker="Saeed"), [])

    async def test_a_failed_ask_keeps_what_memory_knew(self):
        self.assertTrue(await self.service.learn_people())
        self.answer = error_reply_payload("unavailable", "people store unreadable")
        self.assertFalse(await self.service.learn_people())
        self.answer = {"ok": True, "facet": "people", "as_of": 0.0, "people": []}
        self.assertFalse(await self.service.learn_people())
        await self.service.engine.entity_for("Aran")
        self.assertEqual(await self.service.engine.query_entities("my son", speaker="Saeed"), ["person:aran"])

    async def test_it_asks_at_start_and_on_its_beat(self):
        await self.service.stop()
        ctx = self.service._ctx  # noqa: SLF001
        self.service = Service(config=Config(entities=True, people_refresh_s=2))
        await self.service.start(ctx)
        await self.service._people_task  # noqa: SLF001
        self.assertEqual(self.asked, 1, "once at start")
        for _ in range(2):
            await self.service._on_tick(Message.new(topics.SYSTEM_TICK_SECOND, source="test", payload={}))  # noqa: SLF001
        await self.service._people_task  # noqa: SLF001
        self.assertEqual(self.asked, 2, "and again on the beat")
        self.assertEqual(self.service.engine.people[0].relation("son"), "Aran")

    async def test_with_entities_off_it_never_asks(self):
        await self.service.stop()
        ctx = self.service._ctx  # noqa: SLF001
        self.service = Service(config=Config(entities=False, people_refresh_s=1))
        await self.service.start(ctx)
        await self.service._on_tick(Message.new(topics.SYSTEM_TICK_SECOND, source="test", payload={}))  # noqa: SLF001
        self.assertIsNone(self.service._people_task)  # noqa: SLF001
        self.assertEqual(self.asked, 0)
