"""The memory block a chat turn is given (observer wave, 2026-09-10).

A CLI chat turn carries no transcript of its own: `_handle_chat` mints a
fresh `session_id` per typed line and `run_percept_chat` builds a
throwaway `Session` from it, so `Assembler._memory_block` IS the
conversation's entire continuity. It used to be one similarity search
against the line just typed, which produced two symptoms in a real
22-turn session with a real model:

1. **A fact told earlier simply vanished.** "one mini PC called falcon
   ... a Raspberry Pi 4 called sparrow ... Please remember those two
   names" (turn 2) was answered three separate times -- turns 14 and 19,
   and again after a restart -- with "I don't have your two machines'
   names ... they never made it into my notes". The record was in the
   store throughout; it was simply not in the top 8 for "what are my two
   machines called and how much RAM does each have?", while an unrelated
   autonomous code-patch record was.

2. **A correction lost to the thing it corrected.** Turn 9 corrected a
   birthday from March 4th to March 6th and was acknowledged. Turns 10,
   12, 14 and 22 -- and turn 3 of the next run -- each volunteered "March
   4th" again, because for those queries only the superseded record came
   back. Asked head-on, the same session said "March 6th". The same
   question, two answers, two turns apart.

These two tests are the two halves of the fix: the recent-turns recall
that makes (1) impossible, and the chronological render plus header that
makes (2) answerable.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.context import (
    _MEMORY_RECENT_K,
    Assembler,
    MEMORY_BLOCK_HEADER,
)

from .harness import Harness, run


def _item(ref: str, content: str, ts: float, score: float = 1.0) -> dict:
    return {"ref": ref, "content": content, "kind": "episodic",
            "score": score, "confidence": 1.0, "ts": ts}


class _Memory:
    """A Memory double that answers the two recalls differently, the way
    the real one does: `query=""` is recency-ordered, anything else is
    ranked by similarity."""

    def __init__(self, *, matched: list[dict], recent: list[dict]) -> None:
        self.matched = matched
        self.recent = recent
        self.queries: list[str] = []

    async def respond(self, bus, message) -> None:
        query = message.payload.get("query", "")
        self.queries.append(query)
        items = self.recent if query == "" else self.matched
        k = int(message.payload.get("k", 8))
        await bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY,
                        payload={"items": items[:k], "truncated": False})


class TestRecentTurnsTravelWithEveryTurn(unittest.TestCase):
    @run
    async def test_a_fact_the_query_does_not_resemble_is_still_in_the_block(self):
        """The falcon/sparrow case, reduced: the fact is in the store,
        the similarity search does not find it, and the block must carry
        it anyway."""
        async with Harness() as h:
            memory_bus = h.client("memory")
            fact = _item("episodic:2", "User: my machines are called falcon and sparrow", ts=100.0)
            noise = [_item(f"episodic:{i}", f"an unrelated code patch, number {i}", ts=200.0 + i)
                     for i in range(8)]
            memory = _Memory(matched=noise, recent=[fact])

            async def _responder(message):
                await memory.respond(memory_bus, message)

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
            mem, why = await assembler._memory_block(  # noqa: SLF001
                "what are my two machines called and how much RAM does each have?", session)
            await sub.unsubscribe()

            self.assertEqual(why, "")
            self.assertIn("falcon and sparrow", mem)
            # And the recall that found it was a real, separate one --
            # not the similarity search under another name.
            self.assertIn("", memory.queries)
            self.assertEqual(len(memory.queries), 2)

    @run
    async def test_the_recent_recall_asks_for_recent_k_episodic_memories(self):
        async with Harness() as h:
            memory_bus = h.client("memory")
            seen: list[dict] = []

            async def _responder(message):
                seen.append(dict(message.payload))
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY,
                                       payload={"items": [], "truncated": False})

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t2", kind="chat", mode="execute", profile=profiles.CHAT)
            await assembler._memory_block("anything", session)  # noqa: SLF001
            await sub.unsubscribe()

            recent = [p for p in seen if p.get("query") == ""]
            self.assertEqual(len(recent), 1, seen)
            self.assertEqual(recent[0]["k"], _MEMORY_RECENT_K)
            self.assertEqual(recent[0]["kinds"], ["episodic"])


class TestACorrectionOutranksWhatItCorrects(unittest.TestCase):
    @run
    async def test_the_block_is_rendered_oldest_first(self):
        async with Harness() as h:
            memory_bus = h.client("memory")
            stale = _item("episodic:5", "User: Mina's birthday is March 4th", ts=100.0, score=0.9)
            fix = _item("episodic:13", "User: correction, Mina's birthday is March 6th", ts=900.0, score=0.4)
            # The store hands them back strongest-match first, which is
            # the stale one: the original came with a whole answer
            # restating it, the correction is one line.
            memory = _Memory(matched=[stale, fix], recent=[fix, stale])

            async def _responder(message):
                await memory.respond(memory_bus, message)

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t3", kind="chat", mode="execute", profile=profiles.CHAT)
            mem, _why = await assembler._memory_block("when is my sister's birthday?", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertIn("March 4th", mem)
            self.assertIn("March 6th", mem)
            self.assertLess(mem.index("March 4th"), mem.index("March 6th"),
                            "the correction must come after what it corrects")

    @run
    async def test_the_header_says_later_lines_win(self):
        """The order alone is not enough -- nothing told the model what
        the order meant, so the two arrived as peers."""
        async with Harness() as h:
            memory_bus = h.client("memory")
            item = _item("episodic:1", "something remembered", ts=1.0)
            memory = _Memory(matched=[item], recent=[item])

            async def _responder(message):
                await memory.respond(memory_bus, message)

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t4", kind="chat", mode="execute", profile=profiles.CHAT)
            blocks = await assembler.assemble(session, "chat", user_text="hello")
            await sub.unsubscribe()

            memory_blocks = [b for b in blocks
                             if b["role"] == "system" and "something remembered" in b["content"]]
            self.assertEqual(len(memory_blocks), 1, blocks)
            content = memory_blocks[0]["content"]
            self.assertTrue(content.startswith(MEMORY_BLOCK_HEADER), content[:200])
            self.assertIn("superseded", content)
            self.assertIn("oldest first", content)

    @run
    async def test_the_same_memory_is_not_listed_twice(self):
        """Both recalls legitimately return the same record; the block
        must not repeat it, or the newest turns get counted twice against
        the aggregate cap and read as emphasis."""
        async with Harness() as h:
            memory_bus = h.client("memory")
            item = _item("episodic:7", "User: the backup window is 02:00 to 04:00", ts=50.0)
            memory = _Memory(matched=[item], recent=[item])

            async def _responder(message):
                await memory.respond(memory_bus, message)

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t5", kind="chat", mode="execute", profile=profiles.CHAT)
            mem, _why = await assembler._memory_block("backup window?", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertEqual(mem.count("02:00 to 04:00"), 1, mem)


class TestOneRecallFailingDoesNotLoseTheOther(unittest.TestCase):
    @run
    async def test_a_block_is_still_built_when_only_the_recent_recall_answers(self):
        """The whole subsystem being unreachable must still produce the
        honest "could not look" note -- but ONE of two recalls failing
        must not throw away the other's items."""
        async with Harness() as h:
            memory_bus = h.client("memory")
            recent = _item("episodic:9", "User: my NAS is at /mnt/vault", ts=10.0)

            async def _responder(message):
                if message.payload.get("query") == "":
                    await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY,
                                           payload={"items": [recent], "truncated": False})
                    return
                await memory_bus.reply(message, type=topics.MEMORY_RETRIEVE_REPLY, payload={
                    "ok": False, "error": {"code": "unavailable", "detail": "store backend is down"}})

            sub = await memory_bus.subscribe(topics.MEMORY_RETRIEVE, _responder)
            assembler = Assembler(h.client("orchestration"))
            session = Session(task_id="t6", kind="chat", mode="execute", profile=profiles.CHAT)
            mem, why = await assembler._memory_block("where is the NAS?", session)  # noqa: SLF001
            await sub.unsubscribe()

            self.assertIn("/mnt/vault", mem)
            self.assertEqual(why, "")


if __name__ == "__main__":
    unittest.main()
