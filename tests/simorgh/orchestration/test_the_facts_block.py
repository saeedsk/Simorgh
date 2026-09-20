"""Stage 5 item 4: what HOLDS goes in front of what was said. A corrected
fact reaches the prompt as the current value with the old one marked, so
the model cannot answer with what was superseded."""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import Assembler, FACTS_BLOCK_HEADER

from .harness import Harness, run

FACT = {"id": "f1", "subject": "birthday", "predicate": "is", "object": "March 6th",
        "person_scope": "Saeed", "confidence": 1.0, "valid_from": 100.0,
        "was": "March 4th", "was_until": 90.0, "source_refs": ["memory:episodic:9"]}


class TheFactsBlock(unittest.TestCase):
    @run
    async def test_the_current_value_and_what_it_replaced_reach_the_prompt(self):
        async with Harness() as h:
            memory_bus = h.client("memory")

            async def _responder(message):
                payload = {"items": [{"ref": "episodic:1", "content": "Saeed said March 4th", "kind": "episodic",
                                      "score": 0.9, "confidence": 1.0, "ts": 90.0}], "truncated": False}
                if message.payload.get("query"):
                    payload["facts"] = [FACT]
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload=payload)

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT,
                              user_text="when is my birthday", speaker="Saeed")
            messages = await assembler.assemble(session, "chat", user_text="when is my birthday")
            await sub.unsubscribe()

        block = next((m["content"] for m in messages if m["content"].startswith(FACTS_BLOCK_HEADER)), "")
        self.assertIn("Saeed: birthday is March 6th", block)
        self.assertIn("was March 4th", block)
        memory_block = next(m["content"] for m in messages if "Relevant memory" in m["content"])
        self.assertLess(messages.index(next(m for m in messages if m["content"] is block)),
                        messages.index(next(m for m in messages if m["content"] is memory_block)),
                        "facts come before the conversation lines they correct")

    @run
    async def test_no_facts_no_block(self):
        async with Harness() as h:
            memory_bus = h.client("memory")

            async def _responder(message):
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY,
                                       payload={"items": [], "truncated": False})

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT, user_text="hello")
            messages = await assembler.assemble(session, "chat", user_text="hello")
            await sub.unsubscribe()
        self.assertFalse([m for m in messages if m["content"].startswith(FACTS_BLOCK_HEADER)])


if __name__ == "__main__":
    unittest.main()
