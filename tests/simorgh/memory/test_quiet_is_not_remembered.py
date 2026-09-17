"""Silence is not a conversation (memory/service.py).

446 of the creator's 2,422 episodic records ended "Sim: QUIET" --
turns Sim judged were not for it, stayed silent on, and wrote down
anyway. A work meeting was among them: colleagues' names and business
talk, kept because the turn was not empty (2026-09-16).

`QUIET` is a protocol word. `orchestration/scaffolds.py` tells the model
to answer with it and nothing else; voice does not speak it; memory must
not remember it.
"""

from __future__ import annotations

import unittest

from simorgh.contracts.settings import QUIET_REPLY, is_quiet_reply


class WhatCountsAsSilence(unittest.TestCase):
    def test_the_protocol_word(self):
        self.assertEqual(QUIET_REPLY, "QUIET")
        for said in ("QUIET", "quiet", " QUIET ", "QUIET.", "quiet!", "**QUIET**"):
            self.assertTrue(is_quiet_reply(said), said)

    def test_a_sentence_that_merely_mentions_quiet_is_a_real_answer(self):
        for said in ("I will be quiet", "quietly closed the door",
                     "The house is quiet tonight", "QUIET is what I say when words are not for me"):
            self.assertFalse(is_quiet_reply(said), said)

    def test_nothing_at_all_is_not_the_protocol_word(self):
        self.assertFalse(is_quiet_reply(""))
        self.assertFalse(is_quiet_reply(None))


class TheEpisodicWriteSkipsIt(unittest.IsolatedAsyncioTestCase):
    async def test_a_quiet_turn_is_not_stored(self):
        import types

        from simorgh.memory.service import Service

        stored: list = []
        service = object.__new__(Service)
        service.engine = types.SimpleNamespace(
            store=lambda **kw: stored.append(kw) or "memory:episodic:1")
        service._ctx = types.SimpleNamespace(
            logger=types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
            source="memory", bus=types.SimpleNamespace(publish=lambda *a, **k: None))

        async def _run(payload):
            await service._on_turn_completed(types.SimpleNamespace(payload=payload))

        await _run({"user_text": "Three, you, Saeed, Sim, and me. Chachibuti.",
                    "text": "QUIET", "kind": "chat", "session_id": "s1", "task_id": "t1"})
        self.assertEqual(stored, [], "a turn Sim stayed silent on is not a memory")


if __name__ == "__main__":
    unittest.main()
