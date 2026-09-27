"""A voice nobody placed is somebody, not everybody (memory/service.py).

An episodic turn with no `person:` tag reads as a typed turn, which recall
shares with every speaker (orchestration/context.py `_theirs`). An
unmatched voice's turns were stored that way, so a stranger's "I can't
start music for a voice I don't have enrolled" was recalled on Saeed's own
"Hey Sim, play music" -- and the model gave him the same refusal, naming
him in it (2026-09-27, the room satellite).
"""

from __future__ import annotations

import types
import unittest

from simorgh.memory.service import UNPLACED_VOICE_TAG, Service


class AnUnplacedVoiceIsTaggedAsItsOwn(unittest.IsolatedAsyncioTestCase):
    async def _stored_tags(self, payload: dict) -> list:
        stored: list = []

        async def _store(**kw):
            stored.append(kw)
            return "memory:episodic:1"

        async def _publish(*_a, **_k):
            return None

        service = object.__new__(Service)
        service.engine = types.SimpleNamespace(store=_store,
                                               working=types.SimpleNamespace(add=lambda *a, **k: None))
        service._ctx = types.SimpleNamespace(
            logger=types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
            source="memory", clock=types.SimpleNamespace(now=lambda: 0.0),
            bus=types.SimpleNamespace(publish=_publish))
        await service._on_turn_completed(types.SimpleNamespace(payload={
            "kind": "chat", "session_id": "s1", "task_id": "t1", **payload}))
        self.assertEqual(len(stored), 1)
        return list(stored[0]["tags"])

    async def test_a_voice_nobody_matched_is_tagged_unknown(self):
        tags = await self._stored_tags({"channel": "voice", "speaker": "",
                                        "user_text": "Hey Sim, play music.", "text": "Not for a voice I don't know."})
        self.assertIn(UNPLACED_VOICE_TAG, tags)

    async def test_a_named_voice_keeps_only_its_own_name(self):
        tags = await self._stored_tags({"channel": "voice", "speaker": "Saeed",
                                        "user_text": "Hey Sim, play music.", "text": "Playing."})
        self.assertIn("person:Saeed", tags)
        self.assertNotIn(UNPLACED_VOICE_TAG, tags)

    async def test_a_typed_turn_stays_shared(self):
        tags = await self._stored_tags({"channel": "cli", "speaker": "",
                                        "user_text": "what's on today?", "text": "Nothing booked."})
        self.assertFalse([t for t in tags if t.startswith("person:")], tags)


if __name__ == "__main__":
    unittest.main()
