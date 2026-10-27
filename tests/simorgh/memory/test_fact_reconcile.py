"""Stage 15 item 7: Mem0's update decision in consolidation's fact pass.

Today a fact supersedes another only when the normalised `(person_scope,
subject, predicate)` key matches exactly, so "Reza lives in Shiraz" and
then "Reza moved to Tehran" leave two live facts. With entities on, a new
fact is shown the most similar live facts with the same scope and the same
subject entity, and the model decides ADD | UPDATE | DELETE | NOOP for each.
UPDATE and DELETE are supersession events, never deletion; a floor or
unparseable reply is today's exact-key rule, never a guess; and a decision
about a fact the model was not shown is ignored.
"""

from __future__ import annotations

import json
import re
import unittest

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.ledger.factory import make_ledger
from simorgh.memory.config import Config
from simorgh.memory.consolidation import (EXTRACT_INSTRUCTION, RECONCILE_INSTRUCTION, RECONCILE_K, extract_facts,
                                          parse_decisions)
from simorgh.memory.facts import FACT_STREAM
from simorgh.memory.store import MemoryEngine
from tests.simorgh.helpers import FakeClock

WINDOW = "Saeed: Reza moved to Tehran last month."
TEHRAN = [{"subject": "Reza", "predicate": "lives in", "object": "Tehran", "person": "",
           "quote": "Reza moved to Tehran last month."}]


def _every(decision: str):
    """A model that gives `decision` for every fact it was shown."""
    def answer(prompt: str) -> str:
        return json.dumps([{"id": i, "decision": decision} for i in re.findall(r"\[([0-9a-f]{12})\]", prompt)])
    return answer


class _Pass(unittest.IsolatedAsyncioTestCase):
    entities = True

    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.engine = MemoryEngine(self.ledger, Config(entities=self.entities), clock=self.clock)
        self.engine.people = ()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        self.bus = make_client(backend, source="memory", clock=self.clock)
        await self.bus.start()
        self.asked: list[str] = []

    async def asyncTearDown(self):
        await self.bus.stop()

    async def _extract(self, decide, *, extracted=TEHRAN, floor: bool = False):
        """One fact pass: the extraction is answered by a real (fake)
        provider; the reconcile question by `decide`, from the floor when
        `floor`."""
        async def _think(message: Message) -> None:
            system, prompt = (m["content"] for m in message.payload["messages"])
            reconcile = system == RECONCILE_INSTRUCTION
            if reconcile:
                self.asked.append(prompt)
            text = (decide(prompt) if callable(decide) else decide) if reconcile else json.dumps(extracted)
            assert system in (EXTRACT_INSTRUCTION, RECONCILE_INSTRUCTION)
            await self.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload={
                "text": text, "tool_calls": [], "provider": "floor" if floor and reconcile else "fake",
                "cost_usd": 0.0, "tokens": 1, "floor": floor and reconcile, "non_answer": False})

        sub = await self.bus.subscribe(topics.COGNITION_THINK, _think)
        self.tally: dict = {}
        try:
            return await extract_facts(self.engine, bus=self.bus, source="memory", window=WINDOW,
                                       refs=["memory:episodic:1"], timeout=5.0, tally=self.tally)
        finally:
            await sub.unsubscribe()

    async def _live(self) -> list[tuple[str, str, str, str]]:
        index = await self.engine._facts_synced()  # noqa: SLF001
        return sorted((f.person_scope, f.subject, f.predicate, f.object)
                      for f in (index.by_id[i] for i in index.by_key.values()))

    async def _superseded(self) -> dict[str, str]:
        return {e.payload["id"]: e.payload["superseded_by"] for e in await self.ledger.read(FACT_STREAM)
                if e.type == "fact.superseded"}


class ReconcileTestCase(_Pass):
    async def test_shiraz_to_tehran_leaves_one_live_and_one_superseded(self):
        shiraz = await self.engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz")
        await self.engine.store_fact(subject="Reza", predicate="phone", object="0912 345 6789")
        moved = [{**TEHRAN[0], "predicate": "moved to"}]

        def decide(prompt):
            ids = re.findall(r"\[([0-9a-f]{12})\] Reza (\w+)", prompt)
            return json.dumps([{"id": i, "decision": "UPDATE" if what == "lives" else "ADD"} for i, what in ids])

        stored = await self._extract(decide, extracted=moved)
        self.assertEqual([f.object for f in stored], ["Tehran"])
        self.assertEqual(await self._live(), [("*", "Reza", "moved to", "Tehran"), ("*", "Reza", "phone", "0912 345 6789")])
        self.assertEqual(await self._superseded(), {shiraz.id: stored[0].id}, "superseded, never deleted")
        events = [e for e in await self.ledger.read(FACT_STREAM) if e.payload.get("id") == shiraz.id]
        self.assertEqual([e.type for e in events], ["fact.stored", "fact.superseded"])
        self.assertIsNotNone(events[-1].payload["valid_to"])
        self.assertEqual(self.tally, {"asked": 1, "superseded": 1})

    async def test_a_different_reza_is_left_alone(self):
        other = await self.engine.store_fact(subject="Reza Karimi", predicate="lives in", object="Isfahan")
        shiraz = await self.engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz")
        self.assertNotEqual(other.subject_id, shiraz.subject_id)
        await self._extract(_every("UPDATE"), extracted=[{**TEHRAN[0], "predicate": "moved to"}])
        self.assertNotIn(other.id, self.asked[0], "another entity's fact is not a candidate")
        self.assertIn(("*", "Reza Karimi", "lives in", "Isfahan"), await self._live())
        self.assertEqual(set(await self._superseded()), {shiraz.id})

    async def test_private_facts_are_never_compared_across_scope(self):
        mine = await self.engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz", person_scope="Saeed")
        theirs = await self.engine.store_fact(subject="Reza", predicate="owes", object="a ladder", person_scope="Soodeh")
        # A household fact, then a private one of somebody else's: neither sees the other's.
        await self._extract(_every("DELETE"), extracted=[{**TEHRAN[0], "predicate": "moved to"}])
        await self._extract(_every("DELETE"), extracted=[{**TEHRAN[0], "predicate": "moved to", "person": "Soodeh"}])
        self.assertEqual(len(self.asked), 1, "only Soodeh's own fact was ever a candidate, for her own new fact")
        self.assertIn(theirs.id, self.asked[0])
        self.assertNotIn(mine.id, self.asked[0])
        self.assertNotIn(mine.id, await self._superseded())
        self.assertIn(("saeed", "Reza", "lives in", "Shiraz"), [(s.lower(), *r) for s, *r in await self._live()])

    async def test_the_floor_falls_back_to_the_exact_key(self):
        shiraz = await self.engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz")
        await self.engine.store_fact(subject="Reza", predicate="works in", object="Shiraz")
        stored = await self._extract(_every("UPDATE"), floor=True)
        # Exact key: "Reza lives in" is replaced; "works in" is not touched.
        self.assertEqual(await self._superseded(), {shiraz.id: stored[0].id})
        self.assertEqual(await self._live(), [("*", "Reza", "lives in", "Tehran"), ("*", "Reza", "works in", "Shiraz")])
        self.assertEqual(self.tally, {"asked": 1, "fallback": 1})

    async def test_an_unparseable_reply_falls_back_to_the_exact_key(self):
        await self.engine.store_fact(subject="Reza", predicate="works in", object="Shiraz")
        await self._extract("Sure! Reza moved, so the old one should go.", extracted=[{**TEHRAN[0], "predicate": "moved to"}])
        self.assertEqual(await self._superseded(), {})
        self.assertEqual(len(await self._live()), 2)
        self.assertEqual(self.tally["fallback"], 1)

    async def test_a_decision_about_a_fact_it_was_not_shown_is_ignored(self):
        other = await self.engine.store_fact(subject="Reza Karimi", predicate="lives in", object="Isfahan")
        private = await self.engine.store_fact(subject="Reza", predicate="owes", object="a ladder", person_scope="Saeed")
        await self.engine.store_fact(subject="Reza", predicate="works in", object="Shiraz")

        def decide(prompt):
            return json.dumps([{"id": other.id, "decision": "DELETE"}, {"id": private.id, "decision": "UPDATE"},
                               {"id": "000000000000", "decision": "DELETE"}])

        await self._extract(decide, extracted=[{**TEHRAN[0], "predicate": "moved to"}])
        self.assertEqual(await self._superseded(), {})
        self.assertEqual(len(await self._live()), 4)
        self.assertEqual(self.tally, {"asked": 1, "ignored": 3, "fallback": 1})

    async def test_noop_skips_a_fact_already_held(self):
        await self.engine.store_fact(subject="Reza", predicate="lives in", object="Tehran")
        self.assertEqual(await self._extract(_every("NOOP")), [])
        self.assertEqual(await self._superseded(), {})
        self.assertEqual(self.tally, {"asked": 1, "noop": 1})

    async def test_noop_never_undoes_an_exact_key_correction(self):
        shiraz = await self.engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz")
        stored = await self._extract(_every("NOOP"))
        self.assertEqual(await self._superseded(), {shiraz.id: stored[0].id})

    async def test_at_most_k_candidates_are_shown(self):
        for n in range(RECONCILE_K + 3):
            await self.engine.store_fact(subject="Reza", predicate=f"likes thing {n}", object="tea")
        await self._extract(_every("ADD"))
        self.assertEqual(len(re.findall(r"\[[0-9a-f]{12}\]", self.asked[0])), RECONCILE_K)

    async def test_a_subject_with_no_facts_asks_nothing(self):
        await self._extract(_every("DELETE"))
        self.assertEqual(self.asked, [])
        self.assertEqual(await self._live(), [("*", "Reza", "lives in", "Tehran")])


class StoreFactGuardTestCase(_Pass):
    """`store_fact(supersedes=)` re-checks what `fact_candidates` chose by,
    so no caller can end a fact across a scope or about another entity."""

    async def test_supersedes_never_crosses_a_scope_or_an_entity(self):
        private = await self.engine.store_fact(subject="Reza", predicate="owes", object="a ladder", person_scope="Saeed")
        other = await self.engine.store_fact(subject="Reza Karimi", predicate="lives in", object="Isfahan")
        shiraz = await self.engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz")
        new = await self.engine.store_fact(subject="Reza", predicate="moved to", object="Tehran",
                                           supersedes=(private.id, other.id, shiraz.id))
        self.assertEqual(await self._superseded(), {shiraz.id: new.id})

    async def test_supersedes_ends_nothing_with_entities_off(self):
        self.engine._config = Config(entities=False)  # noqa: SLF001
        shiraz = await self.engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz")
        await self.engine.store_fact(subject="Reza", predicate="moved to", object="Tehran", supersedes=(shiraz.id,))
        self.assertEqual(await self._superseded(), {})

    async def test_no_supersession_loop(self):
        # Shiraz -> Tehran, then the old value heard again: each step ends
        # only a live fact and names a newer one, so the chain never closes.
        shiraz = await self.engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz")
        tehran = (await self._extract(_every("UPDATE"), extracted=[{**TEHRAN[0], "predicate": "moved to"}]))[0]
        back = (await self._extract(_every("UPDATE"),
                                    extracted=[{**TEHRAN[0], "predicate": "lives in", "object": "Shiraz"}]))[0]
        # An already-ended fact named again ends nothing.
        await self.engine.store_fact(subject="Reza", predicate="likes", object="tea", supersedes=(shiraz.id, tehran.id))
        self.assertEqual(await self._superseded(), {shiraz.id: tehran.id, tehran.id: back.id})
        self.assertEqual(await self._live(), [("*", "Reza", "likes", "tea"), ("*", "Reza", "lives in", "Shiraz")])
        self.assertEqual(self.tally, {"asked": 1, "superseded": 1})


class EntitiesOffTestCase(_Pass):
    entities = False

    async def test_entities_off_asks_nothing_and_keeps_the_exact_key(self):
        await self.engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz")
        await self._extract(_every("UPDATE"), extracted=[{**TEHRAN[0], "predicate": "moved to"}])
        self.assertEqual(self.asked, [])
        self.assertEqual(self.tally, {})
        self.assertEqual(len(await self._live()), 2, "today's rule: two keys, two live facts")
        self.assertEqual(await self.engine.fact_candidates(subject="Reza", predicate="x", object="y"), [])


class _Places:
    """A stand-in dense model: cities are one concept, drinks another."""

    def encode(self, text):
        if isinstance(text, list):
            return [self.encode(t) for t in text]
        words = text.lower().split()
        return [float(sum(w in ("shiraz", "tehran", "isfahan", "lives", "moved") for w in words)),
                float(sum(w in ("tea", "coffee", "likes") for w in words)), 0.05]


class DenseRankingTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_the_dense_path_ranks_by_the_fused_score(self):
        from simorgh.memory.embedders import Embedder

        clock = FakeClock()
        ledger = make_ledger({"backend": "memory"}, clock=clock)
        await ledger.start()
        engine = MemoryEngine(ledger, Config(entities=True, embedder="local"), clock=clock,
                              embedder=Embedder("local", local_check=lambda: True, encoder=_Places()))
        engine.people = ()
        for n in range(RECONCILE_K):
            await engine.store_fact(subject="Reza", predicate=f"likes drink {n}", object="tea")
        await engine.store_fact(subject="Reza", predicate="lives in", object="Shiraz")
        found = await engine.fact_candidates(subject="Reza", predicate="moved to", object="Tehran", k=2)
        self.assertEqual(found[0].object, "Shiraz")


class ParseDecisionsTestCase(unittest.TestCase):
    def test_only_shown_ids_and_known_decisions_count(self):
        decided, ignored = parse_decisions(
            'ok: [{"id": "a", "decision": "update"}, {"id": "b", "decision": "MAYBE"}, {"id": "z", "decision": "DELETE"}]',
            ["a", "b"])
        self.assertEqual((decided, ignored), ({"a": "UPDATE"}, 1))

    def test_no_array_or_no_usable_decision_is_none(self):
        self.assertEqual(parse_decisions("UPDATE", ["a"]), (None, 0))
        self.assertEqual(parse_decisions("[not json]", ["a"]), (None, 0))
        self.assertEqual(parse_decisions('[{"id": "q", "decision": "DELETE"}]', ["a"]), (None, 1))


if __name__ == "__main__":
    unittest.main()
