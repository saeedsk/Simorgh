"""Stage 15 follow-up: the facts block shows what Memory reached through
the entity graph -- each hop fact marked with what it was reached through,
each entity summary on a line of its own -- under `[orchestration]
memory_graph_lines`, while a reply with no hop or summary facts renders
exactly as it did before (the first 8 facts, nothing else)."""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.config import Config
from simorgh.orchestration.context import Assembler, FACTS_BLOCK_HEADER, _fact_lines

from .harness import Harness, run


def _fact(i: int, **extra) -> dict:
    return {"id": f"f{i}", "subject": f"thing {i}", "predicate": "is", "object": f"value {i}",
            "person_scope": "*", "confidence": 1.0, "valid_from": float(i), **extra}


def _before(facts: list[dict]) -> str:
    """`_fact_lines` as it was before stage 15, verbatim, to compare with."""
    lines = []
    for fact in facts[:8]:
        line = " ".join(str(fact.get(part) or "") for part in ("subject", "predicate", "object")).strip()
        if not line:
            continue
        who = str(fact.get("person_scope") or "*")
        if who and who != "*":
            line = f"{who}: {line}"
        if fact.get("was"):
            line += f" (was {fact['was']}, until you were told otherwise)"
        lines.append(f"- {line}")
    return "\n".join(lines)


class TheLines(unittest.TestCase):
    def test_a_reply_without_graph_facts_is_byte_identical(self):
        cases = [
            [],
            [_fact(1)],
            [_fact(i, person_scope="Saeed" if i % 2 else "*", was="old" if i % 3 == 0 else "") for i in range(12)],
            [{"id": "e", "subject": "", "predicate": "", "object": ""}, *[_fact(i) for i in range(9)]],
        ]
        for facts in cases:
            self.assertEqual(_fact_lines(facts), _before(facts))

    def test_hop_facts_are_marked_and_come_after_the_plain_ones(self):
        facts = [_fact(1), _fact(2, subject="Aran", predicate="likes", object="Lego", hop=1, via="Aran"),
                 _fact(3, subject="Reza", predicate="phone", object="0912", hop=2)]
        self.assertEqual(_fact_lines(facts).splitlines(), [
            "- thing 1 is value 1",
            "- Aran likes Lego (via Aran)",
            "- Reza phone 0912 (linked)",
        ])

    def test_a_summary_is_its_own_line_and_leads_the_graph_lines(self):
        facts = [_fact(1, subject="Reza", predicate="fixed", object="the boiler", hop=1, via="boiler"),
                 {"id": "person:reza#summary", "subject": "Reza", "predicate": "in short:",
                  "object": "Reza is the  plumber.", "person_scope": "*", "confidence": 1.0,
                  "summary": True, "entity": "person:reza"}]
        self.assertEqual(_fact_lines(facts).splitlines(), [
            "- About Reza: Reza is the plumber.",
            "- Reza fixed the boiler (via boiler)",
        ])

    def test_graph_facts_do_not_take_the_plain_facts_room(self):
        plain = [_fact(i) for i in range(10)]
        hops = [_fact(100 + i, hop=2, via="Reza") for i in range(10)]
        lines = _fact_lines(plain + hops).splitlines()
        self.assertEqual(len([line for line in lines if "(via" not in line]), 8, "the plain cap is today's 8")
        self.assertEqual(len([line for line in lines if "(via Reza)" in line]), 8, "the graph cap is its own")
        self.assertEqual(_fact_lines(plain + hops, max_graph=0), _before(plain), "0 hides the graph lines")
        self.assertEqual(len(_fact_lines(plain + hops, max_facts=3, max_graph=2).splitlines()), 5)

    def test_the_caps_come_from_the_orchestration_section(self):
        config = Config.from_mapping({"memory_fact_lines": 5, "memory_graph_lines": "3"})
        self.assertEqual((config.memory_fact_lines, config.memory_graph_lines), (5, 3))
        self.assertEqual((Config().memory_fact_lines, Config().memory_graph_lines), (8, 8))
        bad = Config.from_mapping({"memory_graph_lines": "lots"})
        self.assertEqual(bad.memory_graph_lines, 8)
        self.assertTrue(bad.problems)


class TheBlock(unittest.TestCase):
    @run
    async def test_my_son_reaches_the_prompt_as_aran(self):
        async with Harness() as h:
            memory_bus = h.client("memory")

            async def _responder(message):
                payload = {"items": [], "truncated": False}
                if message.payload.get("query"):
                    payload["facts"] = [_fact(1, subject="Aran", predicate="likes", object="Lego robotics",
                                              hop=1, via="Aran")]
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload=payload)

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"), fact_lines=(8, 1))
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT,
                              user_text="what does my son like", speaker="Saeed")
            messages = await assembler.assemble(session, "chat", user_text="what does my son like")
            await sub.unsubscribe()
        block = next((m["content"] for m in messages if m["content"].startswith(FACTS_BLOCK_HEADER)), "")
        self.assertIn("- Aran likes Lego robotics (via Aran)", block)


if __name__ == "__main__":
    unittest.main()
