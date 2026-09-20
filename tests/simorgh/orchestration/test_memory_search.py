"""Stage 5 item 6: the model can ask memory in the middle of a turn. It is
effect-free, so it never reaches Guardian, and a spoken turn searches with
the speaker's own tag."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner

from .harness import Harness, run


class MemorySearch(unittest.TestCase):
    @run
    async def test_it_answers_from_memory_and_never_proposes_an_action(self):
        async with Harness() as h:
            memory_bus, asked, proposed = h.client("memory"), [], []

            async def _memory(message):
                asked.append(message.payload)
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
                    "items": [{"ref": "episodic:3", "content": "Iris asked for a telescope", "kind": "episodic",
                               "score": 0.8, "confidence": 1.0, "ts": 5.0}],
                    "facts": [{"id": "f1", "subject": "Iris birthday", "predicate": "is", "object": "June 2nd",
                               "person_scope": "Iris", "confidence": 1.0, "was": "June 3rd"}],
                    "truncated": False})

            async def _guardian(message):
                proposed.append(message.payload)

            subs = [await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _memory),
                    await h.client("guardian").subscribe(topics.ACTION_PROPOSED, _guardian)]
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.VOICE_CHAT,
                              speaker="Iris", channel="voice")
            ok, summary, detail = await asyncio.wait_for(
                runner._run_one(session, {"tool": "memory_search", "args": {"argument": "telescope"}}, 1), timeout=5)
            for sub in subs:
                await sub.unsubscribe()

        self.assertTrue(ok)
        self.assertIn("Iris birthday is June 2nd", summary)
        self.assertIn("was June 3rd", summary)
        self.assertIn("telescope", summary)
        self.assertEqual(asked[0]["filters"], {"tags": ["person:Iris"]}, "a person searches their own memory")
        self.assertEqual(proposed, [], "effect-free: Guardian never sees it")
        self.assertIn("searched memory", detail)

    @run
    async def test_nothing_remembered_says_so_and_an_empty_query_is_refused(self):
        async with Harness() as h:
            memory_bus = h.client("memory")

            async def _memory(message):
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY,
                                       payload={"items": [], "truncated": False})

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _memory)
            runner = SessionRunner(h.client("orchestration"), h.ledger, clock=h.clock.now)
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
            ok, summary, _ = await runner._run_one(session, {"tool": "memory_search", "args": {"argument": "x"}}, 1)
            self.assertTrue(ok)
            self.assertIn("nothing remembered", summary)
            bad_ok, bad, _ = await runner._run_one(session, {"tool": "memory_search", "args": {}}, 2)
            self.assertFalse(bad_ok)
            self.assertIn("needs something", bad)
            await sub.unsubscribe()


if __name__ == "__main__":
    unittest.main()
