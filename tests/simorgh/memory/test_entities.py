"""Stage 15 item 1: entities and resolution.

Fact subjects and objects are the strings somebody said, so "Soo likes
tea" and a question about "Soodeh" never met. These pin each resolution
rule, that a merge leaves every old id resolvable, and the acceptance case
itself: a fact stored as "Soo" is found by a query about "Soodeh".
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.people import household_people
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.consolidation import run_consolidation
from simorgh.memory.entities import (ENTITY_STREAM, EntityIndex, edit_distance_at_most_one, kinship_word,
                                     name_like, normalise)
from simorgh.memory.facts import FACT_STREAM
from simorgh.memory.store import MemoryEngine
from tests.simorgh.helpers import FakeClock


@dataclass(frozen=True)
class _Person:
    """A People record: resolution reads `name`, `identities` and
    `relations` (`contracts.people.Person` has all three)."""

    name: str
    identities: tuple = ()
    relations: dict = field(default_factory=dict)


class TheWordsTestCase(unittest.TestCase):
    def test_normalise_strips_case_articles_and_possessives(self):
        self.assertEqual(normalise("The Boiler's"), "boiler")
        self.assertEqual(normalise("  Reza’s  "), "reza")
        self.assertEqual(normalise("an Old Car"), "old car")

    def test_kinship_words(self):
        self.assertEqual(kinship_word("my wife"), "wife")
        self.assertEqual(kinship_word("his son's"), "son")
        self.assertEqual(kinship_word("Reza"), "")

    def test_one_edit(self):
        self.assertTrue(edit_distance_at_most_one("soodeh", "sodeh"))
        self.assertTrue(edit_distance_at_most_one("soodeh", "soodex"))
        self.assertFalse(edit_distance_at_most_one("soodeh", "sodex"))

    def test_a_value_is_not_a_thing(self):
        self.assertTrue(name_like("Reza"))
        self.assertTrue(name_like("the boiler"))
        self.assertFalse(name_like("0912 345 6789"))
        self.assertFalse(name_like("March 6th"))


class _Event:
    def __init__(self, type_, payload):
        self.type, self.payload = type_, payload


class TheRulesTestCase(unittest.TestCase):
    def setUp(self):
        self.index = EntityIndex()
        self.index.apply(_Event("entity.created", {"id": "person:soodeh", "type": "person", "name": "Soodeh",
                                                   "aliases": ["Soodeh", "Soo"]}))
        self.index.apply(_Event("entity.created", {"id": "thing:boiler", "type": "thing", "name": "boiler",
                                                   "aliases": ["boiler"]}))

    def test_rule_1_an_exact_alias(self):
        self.assertEqual(self.index.resolve_how("soo"), ("alias", "person:soodeh"))
        self.assertEqual(self.index.resolve_how("The boiler"), ("alias", "thing:boiler"))

    def test_rule_2_the_people_registry(self):
        self.assertEqual(self.index.resolve_how("Aran", people=household_people()), ("people", "person:aran"))

    def test_rule_2_a_kinship_word_goes_through_the_speakers_record(self):
        people = (_Person("Saeed", relations={"wife": "Soodeh"}), _Person("Soodeh"))
        self.assertEqual(self.index.resolve("my wife", speaker="Saeed", people=people), "person:soodeh")
        # Somebody else's wife is not Soodeh, and an unexplained one is nobody.
        self.assertIsNone(self.index.resolve("my wife", speaker="Soodeh", people=people))
        self.assertEqual(self.index.resolve_how("my wife", speaker="Iris", people=people), ("kin", None))

    def test_only_the_speakers_own_kinship_word_uses_their_record(self):
        """Saeed's record says who his son is; "his son" and "her son" are
        somebody else's, and "your wife" is the listener's."""
        people = (_Person("Saeed", relations={"son": "Aran", "wife": "Soodeh"}), _Person("Aran"), _Person("Soodeh"))
        for mine in ("my son", "our son", "son"):
            self.assertEqual(self.index.resolve(mine, speaker="Saeed", people=people), "person:aran", mine)
        for theirs in ("his son", "her son's", "their son", "your wife"):
            self.assertEqual(self.index.resolve_how(theirs, speaker="Saeed", people=people), ("kin", None), theirs)

    def test_a_phrase_built_on_a_kinship_word_is_never_resolved(self):
        people = (_Person("Saeed", relations={"wife": "Soodeh"}), _Person("Soodeh"))
        self.assertEqual(self.index.resolve_how("my wife's sister", speaker="Saeed", people=people), ("kin", None))
        self.assertEqual(self.index.resolve_how("his son's teacher", speaker="Saeed", people=people), ("kin", None))

    def test_rule_3_one_edit_on_a_long_name(self):
        self.assertEqual(self.index.resolve_how("Sodeh"), ("fuzzy", "person:soodeh"))
        self.assertEqual(self.index.resolve_how("boilr"), ("fuzzy", "thing:boiler"))

    def test_rule_3_never_on_a_short_name(self):
        self.index.apply(_Event("entity.created", {"id": "person:ira", "type": "person", "name": "Ira"}))
        self.assertEqual(self.index.resolve_how("Iris"), ("", None))

    def test_rule_3_an_ambiguous_match_is_only_noted(self):
        self.index.apply(_Event("entity.created", {"id": "person:sodehx", "type": "person", "name": "Sodehx"}))
        self.assertEqual(self.index.resolve_how("Sodeh"), ("", None))
        self.assertIn(("sodeh", "person:soodeh"), self.index.uncertain)

    def test_rule_4_otherwise_nothing(self):
        self.assertEqual(self.index.resolve_how("the plumber"), ("", None))


class TheEngineTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(entities=True), clock=self.clock)

    async def test_a_fact_records_the_entities_beside_the_strings(self):
        fact = await self.engine.store_fact(subject="the boiler", predicate="was fixed by", object="Reza")
        self.assertEqual((fact.subject, fact.object), ("the boiler", "Reza"))
        self.assertEqual((fact.subject_id, fact.object_id), ("thing:boiler", "person:reza"))
        value = await self.engine.store_fact(subject="Reza", predicate="phone", object="0912 345 6789")
        self.assertEqual((value.subject_id, value.object_id), ("person:reza", ""), "a value is not an entity")

    async def test_a_registry_person_is_their_person_id(self):
        fact = await self.engine.store_fact(subject="Soodeh", predicate="likes", object="green tea")
        self.assertEqual(fact.subject_id, "person:soodeh")

    async def test_a_kinship_word_never_becomes_an_entity(self):
        fact = await self.engine.store_fact(subject="my wife", predicate="likes", object="tea", person_scope="Iris")
        self.assertEqual(fact.subject_id, "")
        index = await self.engine._entities_synced()  # noqa: SLF001
        self.assertNotIn("wife", index.alias)

    async def test_a_phrase_on_a_kinship_word_never_becomes_an_entity(self):
        fact = await self.engine.store_fact(subject="my wife's sister", predicate="lives in", object="Shiraz",
                                            person_scope="Saeed")
        self.assertEqual(fact.subject_id, "")
        index = await self.engine._entities_synced()  # noqa: SLF001
        self.assertFalse([e for e in index.by_id.values() if "wife" in e.name.casefold()])

    async def test_ira_and_iris_stay_two_people(self):
        ira = await self.engine.store_fact(subject="Ira", predicate="likes", object="drawing")
        iris = await self.engine.store_fact(subject="Iris", predicate="likes", object="piano")
        self.assertEqual((ira.subject_id, iris.subject_id), ("person:ira", "person:iris"))
        self.assertEqual([f.object for f, _ in await self.engine.entity_facts("what does Iris like")], ["piano"])

    async def test_his_son_in_a_question_is_not_the_askers_son(self):
        self.engine.people = (_Person("Saeed", relations={"son": "Aran"}), _Person("Aran"))
        await self.engine.store_fact(subject="Aran", predicate="likes", object="football")
        self.assertEqual(await self.engine.query_entities("what does my son like", speaker="Saeed"), ["person:aran"])
        self.assertEqual(await self.engine.query_entities("what does his son like", speaker="Saeed"), [])

    async def test_entities_off_writes_the_fact_it_always_wrote(self):
        plain = MemoryEngine(self.ledger, Config(), clock=self.clock)
        await plain.store_fact(subject="the boiler", predicate="was fixed by", object="Reza")
        payload = (await self.ledger.read(FACT_STREAM))[-1].payload
        self.assertNotIn("subject_id", payload)
        self.assertEqual(await self.ledger.read(ENTITY_STREAM), [])

    async def test_soo_is_found_by_a_query_about_soodeh(self):
        # Stored before anybody said Soo was Soodeh: Soo is its own entity.
        await self.engine.store_fact(subject="Soo", predicate="likes", object="green tea")
        self.assertEqual(await self.engine.entity_facts("what does Soodeh like?"), [])
        await self.engine.store_fact(subject="Soodeh", predicate="works at", object="the clinic")
        await self.engine.merge_entities("person:soo", "person:soodeh")
        found = [fact.subject for fact, _was in await self.engine.entity_facts("what does Soodeh like?")]
        self.assertIn("Soo", found)

    async def test_an_alias_added_later_finds_an_unlinked_fact(self):
        """An old fact with no ids (written with entities off) is resolved
        from its strings at recall, and linked for good on the sleep tick."""
        plain = MemoryEngine(self.ledger, Config(), clock=self.clock)
        await plain.store_fact(subject="Soo", predicate="likes", object="green tea")
        await self.engine.entity_for("Soodeh")
        await self.engine.add_alias("person:soodeh", "Soo")
        found = await self.engine.entity_facts("does Soodeh like tea")
        self.assertEqual([f.subject for f, _ in found], ["Soo"])
        self.assertEqual(await self.engine.link_facts(), 1)
        self.assertEqual(await self.engine.link_facts(), 0, "the backfill is one-off")
        index = await self.engine._facts_synced()  # noqa: SLF001
        self.assertEqual(next(iter(index.by_id.values())).subject_id, "person:soodeh")

    async def test_the_backfill_counts_a_fact_once_when_its_subject_is_nobody(self):
        """"my wife" resolves to nothing without a record, so the fact is
        linked by its object alone -- once, not again on every tick."""
        plain = MemoryEngine(self.ledger, Config(), clock=self.clock)
        await plain.store_fact(subject="my wife", predicate="fixed", object="the boiler", person_scope="Iris")
        self.assertEqual(await self.engine.link_facts(), 1)
        self.assertEqual(await self.engine.link_facts(), 0)
        self.assertEqual([e.type for e in await self.ledger.read(FACT_STREAM)].count("fact.linked"), 1)

    async def test_a_merge_leaves_old_ids_resolvable(self):
        old = await self.engine.store_fact(subject="Sudi", predicate="drives", object="the blue car")
        self.assertEqual(old.subject_id, "person:sudi")
        await self.engine.entity_for("Soodeh")
        await self.engine.merge_entities("person:sudi", "person:soodeh")
        index = await self.engine._entities_synced()  # noqa: SLF001
        self.assertEqual(index.canonical("person:sudi"), "person:soodeh")
        self.assertEqual(index.resolve("Sudi"), "person:soodeh")
        self.assertEqual(index.get("person:sudi").id, "person:soodeh")
        # The fact kept its id, and is found under the survivor.
        found = await self.engine.entity_facts("where is Soodeh's car")
        self.assertEqual([f.id for f, _ in found], [old.id])
        # A restart folds the same stream to the same answer.
        again = MemoryEngine(self.ledger, Config(entities=True), clock=self.clock)
        self.assertEqual((await again._entities_synced()).canonical("person:sudi"), "person:soodeh")  # noqa: SLF001

    async def test_a_fuzzy_match_is_learnt_as_an_alias(self):
        await self.engine.entity_for("Soodeh")
        self.assertEqual(await self.engine.entity_for("Sodeh"), "person:soodeh")
        types = [e.type for e in await self.ledger.read(ENTITY_STREAM)]
        self.assertEqual(types, ["entity.created", "entity.alias_added"])

    async def test_privacy_holds_through_an_alias(self):
        await self.engine.store_fact(subject="Soodeh", predicate="birthday", object="May 2nd", person_scope="Soodeh")
        await self.engine.add_alias("person:soodeh", "Soo")
        self.assertEqual(await self.engine.entity_facts("when is Soo's birthday", person="Iris"), [])
        self.assertEqual(len(await self.engine.entity_facts("when is Soo's birthday", person="Soodeh")), 1)


class TheSleepTickTestCase(unittest.IsolatedAsyncioTestCase):
    """The backfill runs on every pass, and a close pair goes to the model
    only on the sleep tick -- merged on a plain YES from a real provider."""

    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(entities=True), clock=self.clock)
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", clock=self.clock)
        await self.bus.start()

    async def asyncTearDown(self):
        await self.bus.stop()

    async def _pass(self, answer: str, *, floor: bool):
        async def _think(message: Message) -> None:
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": answer, "tool_calls": [], "provider": "floor" if floor else "fake", "cost_usd": 0.0,
                "tokens": 1, "floor": floor, "non_answer": False})

        sub = await self.bus.subscribe(topics.COGNITION_THINK, _think)
        try:
            return await run_consolidation(self.engine, bus=self.bus, source="memory",
                                           keep_per_kind={"episodic": 100}, cognition_timeout=5.0)
        finally:
            await sub.unsubscribe()

    async def _close_pair(self):
        await self.engine.entity_for("Soodeh")
        await self.engine.entity_for("Sodehx")
        self.assertEqual(await self.engine.entity_for("Sodeh"), "person:sodeh")   # ambiguous: its own entity

    async def test_a_yes_merges_the_close_pair(self):
        await self._close_pair()
        report = await self._pass("YES", floor=False)
        self.assertTrue(report.merged)
        index = await self.engine._entities_synced()  # noqa: SLF001
        self.assertIn(index.canonical("person:sodeh"), ("person:soodeh", "person:sodehx"))

    async def test_the_floor_merges_nothing(self):
        await self._close_pair()
        report = await self._pass("YES", floor=True)
        self.assertEqual(report.merged, [])
        self.assertNotIn("entity.merged", [e.type for e in await self.ledger.read(ENTITY_STREAM)])


if __name__ == "__main__":
    unittest.main()
