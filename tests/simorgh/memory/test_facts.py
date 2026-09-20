"""Stage 5 item 3: what holds, and what it replaced. The correction case
passes by construction -- a new fact for the same (person, subject,
predicate) supersedes the old one, so recall never has to judge which of
two records is later."""

import unittest

from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.consolidation import parse_facts
from simorgh.memory.facts import EVERYONE, FACT_STREAM
from simorgh.memory.store import MemoryEngine


class _Clock:
    def __init__(self):
        self.t = 1_790_000_000.0

    def now(self):
        self.t += 60.0
        return self.t


class TheFactStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ledger = make_ledger({"backend": "memory"})
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(), clock=_Clock())

    async def test_a_correction_wins_and_says_what_it_replaced(self):
        await self.engine.store_fact(subject="Saeed birthday", predicate="is", object="March 4th",
                                     person_scope="Saeed", source_refs=("memory:episodic:1",))
        await self.engine.store_fact(subject="saeed  Birthday", predicate="IS", object="March 6th",
                                     person_scope="Saeed", source_refs=("memory:episodic:9",))
        found = await self.engine.facts_for("when is my birthday", person="Saeed")
        self.assertEqual(len(found), 1, "one fact holds, not two")
        fact, was = found[0]
        self.assertEqual((fact.object, was.object), ("March 6th", "March 4th"))
        self.assertIsNotNone(was.valid_to, "the old one stopped being true when the new one started")
        self.assertEqual(fact.source_refs, ("memory:episodic:9",))
        self.assertEqual([e.type for e in await self.ledger.read(FACT_STREAM)],
                         ["fact.stored", "fact.stored", "fact.superseded"], "nothing is rewritten")

    async def test_a_fact_told_by_one_person_is_not_recalled_for_another(self):
        await self.engine.store_fact(subject="birthday", predicate="is", object="March 6th", person_scope="Saeed")
        await self.engine.store_fact(subject="school run", predicate="is at", object="half eight")
        self.assertEqual(await self.engine.facts_for("birthday", person="Iris"), [])
        household = await self.engine.facts_for("when is the school run", person="Iris")
        self.assertEqual(household[0][0].person_scope, EVERYONE)

    async def test_facts_survive_a_restart(self):
        await self.engine.store_fact(subject="wifi password", predicate="is on", object="the fridge magnet")
        again = MemoryEngine(self.ledger, Config(), clock=_Clock())
        found = await again.facts_for("where is the wifi password")
        self.assertEqual(found[0][0].object, "the fridge magnet")

    async def test_a_query_that_mentions_nothing_gets_nothing(self):
        await self.engine.store_fact(subject="wifi password", predicate="is on", object="the fridge magnet")
        self.assertEqual(await self.engine.facts_for("what is the weather"), [])
        self.assertEqual(await self.engine.facts_for(""), [])


class Extraction(unittest.TestCase):
    """A fact nobody said is worse than no fact: every triple carries the
    sentence it came from, and one whose quote is not in the transcript is
    dropped (the same rule as `untraceable`, per triple)."""

    WINDOW = "Saeed said his birthday is March 6th, not the 4th. Iris wants a telescope."

    def test_a_quoted_triple_is_kept_and_an_invented_one_is_not(self):
        kept, rejected = parse_facts(
            '[{"subject": "Saeed birthday", "predicate": "is", "object": "March 6th", "person": "Saeed",'
            '  "quote": "Saeed said his birthday is March 6th, not the 4th."},'
            ' {"subject": "Aran", "predicate": "plays", "object": "violin", "person": "",'
            '  "quote": "Aran plays the violin"}]', self.WINDOW)
        self.assertEqual([f["object"] for f in kept], ["March 6th"])
        self.assertEqual(rejected, ["Aran plays the violin"])

    def test_prose_or_broken_json_records_nothing(self):
        self.assertEqual(parse_facts("I could not find any facts.", self.WINDOW), ([], []))
        self.assertEqual(parse_facts("[{oh dear]", self.WINDOW), ([], []))
        self.assertEqual(parse_facts("[]", self.WINDOW), ([], []))

    def test_a_triple_missing_a_part_is_not_a_fact(self):
        kept, _ = parse_facts('[{"subject": "Iris", "predicate": "", "object": "telescope", "quote": "Iris wants a telescope."}]',
                              self.WINDOW)
        self.assertEqual(kept, [])


if __name__ == "__main__":
    unittest.main()


class ForgettingSparesWhatAFactCites(unittest.IsolatedAsyncioTestCase):
    """Stage 5 item 8: a fact whose source has been forgotten asserts
    something nothing can check. Pruning leaves those records alone."""

    async def test_a_cited_record_survives_a_prune(self):
        ledger = make_ledger({"backend": "memory"})
        await ledger.start()
        engine = MemoryEngine(ledger, Config(half_life_seconds=1.0), clock=_Clock())
        refs = []
        for i in range(5):
            refs.append(await engine.store(kind="episodic", content=f"e{i}", tags=[], source_ref="", confidence=1.0))
        await engine.store_fact(subject="wifi password", predicate="is on", object="the fridge",
                                source_refs=(refs[0],))
        pruned = await engine.prune(kind="episodic", keep=1)
        self.assertEqual(pruned, 3, "four would have gone; the cited one stays")
        self.assertIn(refs[0], engine._kept_back)  # noqa: SLF001
        found, _ = await engine.retrieve(query="", kinds=["episodic"], k=10, filters=None)
        self.assertIn(refs[0], [item.ref for item in found])
