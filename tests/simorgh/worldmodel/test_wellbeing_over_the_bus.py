"""Stage 10 item 2, over the bus: a consented adult's `turn.completed`
turns become trials, the query answers with a state and what it rests on,
a flip is announced as `world.wellbeing.changed` without a word of theirs,
a child's turns are never kept, and a revoke deletes what was."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.worldmodel.config import Config as WorldConfig
from simorgh.worldmodel.facets.wellbeing import BASELINE_MIN
from simorgh.worldmodel.service import Service

from tests.simorgh.helpers import FakeClock

USUAL = "Could you add milk and eggs to the list, and remind me about the dentist on Thursday afternoon?"
SHORT = "fine."


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class WellbeingOverTheBus(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / "repo"
        (root / "simorgh" / "memory").mkdir(parents=True)
        (root / "docs").mkdir()
        (root / "docs" / "SOUL.md").write_text("## Identity\n\nSimorgh is a test persona.\n")
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="worldmodel", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.data_dir = Path(self._tmp.name) / "data"
        self.ctx = Context(name="worldmodel", instance_id="", run_id="test", mode="single", bus=self.bus,
                           ledger=self.ledger, config={}, secrets={}, clock=self.clock, logger=_Logger(),
                           data_dir=self.data_dir)
        self.service = Service(WorldConfig(repo_root=root))
        await self.service.start(self.ctx)
        self.other = make_client(backend, source="orchestration", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()
        self.changes = []
        self._sub = await self.other.subscribe(topics.WORLD_WELLBEING_CHANGED, self._on_change)

    async def _on_change(self, message):
        self.changes.append(message.payload)

    async def asyncTearDown(self):
        await self._sub.unsubscribe()
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _grant(self, name, permission="wellbeing_checkins"):
        reply = await self.other.request(self.other.new(
            topics.WORLD_PEOPLE_UPDATE, {"action": "grant", "name": name, "permission": permission}), timeout=2)
        self.assertTrue(reply.payload["ok"], reply.payload)

    async def _turn(self, speaker, user_text, *, reply="[neutral] Done.", channel="cli"):
        await self.other.publish(self.other.new(topics.TURN_COMPLETED, {
            "session_id": "s", "task_id": "t", "text": reply, "floor": True, "tool_steps": 0,
            "user_text": user_text, "kind": "chat", "channel": channel, "speaker": speaker}))
        await asyncio.sleep(0)

    async def _state(self, person):
        reply = await self.other.request(self.other.new(
            topics.WORLD_ENV_QUERY, {"what": "wellbeing", "args": {"person": person}}), timeout=2)
        return reply.payload

    async def _drain(self):
        for _ in range(5):
            await asyncio.sleep(0)

    async def test_a_consented_adult_is_tracked_and_a_flip_is_announced_without_her_words(self):
        await self._grant("Soodeh")
        for _ in range(BASELINE_MIN):
            self.clock.advance(12 * 3600)
            await self._turn("Soodeh", USUAL)
        for _ in range(4):
            self.clock.advance(600)
            await self._turn("Soodeh", USUAL)
        await self._drain()
        self.assertEqual((await self._state("Soodeh"))["state"], "usual")
        for _ in range(5):
            self.clock.advance(600)
            await self._turn("Soodeh", SHORT, reply="[warm] I'm here.")
        await self._drain()
        state = await self._state("Soodeh")
        self.assertEqual(state["state"], "low", state)
        self.assertIn("quieter than usual", state["note"])
        states = [c["state"] for c in self.changes if c["person"] == "Soodeh"]
        self.assertEqual(states, ["usual", "low"], "flips only, in order")
        for change in self.changes:
            self.assertNotIn("fine", json.dumps(change), "never a word of theirs on the wire")
            self.assertNotIn("milk", json.dumps(change))

    async def test_a_child_or_an_ungranted_adult_leaves_no_record(self):
        for speaker in ("Ira", "Aran", "Saeed"):
            for _ in range(BASELINE_MIN + 5):
                self.clock.advance(600)
                await self._turn(speaker, SHORT)
        await self._drain()
        for speaker in ("Ira", "Aran", "Saeed"):
            with self.subTest(speaker=speaker):
                state = await self._state(speaker)
                self.assertFalse(state["tracked"])
                self.assertEqual(state["state"], "unknown")
        self.assertFalse((self.data_dir / "wellbeing.json").exists(), "nothing was ever written")
        self.assertEqual(self.changes, [])

    async def test_a_turn_with_no_speaker_is_nobodys(self):
        await self._grant("Soodeh")
        for _ in range(BASELINE_MIN + 5):
            self.clock.advance(600)
            await self._turn("", USUAL)
        await self._drain()
        self.assertEqual((await self._state("Soodeh"))["why"], "no turns yet")

    async def test_a_revoke_deletes_what_was_kept(self):
        await self._grant("Soodeh")
        for _ in range(BASELINE_MIN + 4):
            self.clock.advance(600)
            await self._turn("Soodeh", USUAL)
        await self._drain()
        self.assertEqual((await self._state("Soodeh"))["state"], "usual")
        reply = await self.other.request(self.other.new(
            topics.WORLD_PEOPLE_UPDATE, {"action": "revoke", "name": "Soodeh", "permission": "wellbeing_checkins"}),
            timeout=2)
        self.assertTrue(reply.payload["ok"])
        await self._drain()
        state = await self._state("Soodeh")
        self.assertFalse(state["tracked"])
        self.assertNotIn("Soodeh", json.loads((self.data_dir / "wellbeing.json").read_text())["people"])
        # And her next turn, without the grant, is not kept either.
        await self._turn("Soodeh", USUAL)
        await self._drain()
        self.assertNotIn("Soodeh", json.loads((self.data_dir / "wellbeing.json").read_text())["people"])

    async def test_a_spoken_turn_is_scored_with_how_fast_it_was_said(self):
        await self._grant("Soodeh")
        await self.other.publish(self.other.new(topics.VOICE_TRANSCRIPT, {
            "text": USUAL, "confidence": 0.9, "seconds": 6.0, "engine": "test", "device": "kitchen",
            "speaker": "Soodeh", "speaker_score": 0.8}))
        await asyncio.sleep(0)
        await self._turn("Soodeh", USUAL, channel="voice")
        await self._drain()
        record = json.loads((self.data_dir / "wellbeing.json").read_text())["people"]["Soodeh"]
        self.assertIn("rate", record["baseline"], "the transcript's seconds reached the turn's features")
        self.assertIn("soft", record["baseline"])


if __name__ == "__main__":
    unittest.main()
