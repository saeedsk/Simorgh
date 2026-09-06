"""Persona Service over a real (memory-backend) Bus/Ledger and Context --
same composition shape the Kernel uses (see
tests/simorgh/worldmodel/test_service.py for the pattern rationale)."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.persona.config import Config as PersonaConfig
from simorgh.persona.service import Service

from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


class PersonaTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmp.name) / "repo"
        (self.repo_root / "docs").mkdir(parents=True)
        (self.repo_root / "docs" / "SOUL.md").write_text("## Identity\n\nSimorgh is a test persona.\n")

        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="persona", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()

        self.ctx = Context(
            name="persona", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.service = Service(PersonaConfig(repo_root=self.repo_root, decay_interval_s=5.0))
        await self.service.start(self.ctx)

        self.requester = make_client(backend, source="test", ledger=self.ledger, clock=self.clock.now)
        await self.requester.start()

    async def asyncTearDown(self):
        await self.service.stop()
        await self.requester.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _pump(self, n: int = 10) -> None:
        for _ in range(n):
            await asyncio.sleep(0)

    async def test_positive_percept_lifts_mood(self):
        seen = []
        sub = await self.requester.subscribe(topics.PERSONA_STATE_CHANGED, lambda m: seen.append(m) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.PERCEPT_TEXT_RECEIVED, {
            "channel": "cli", "text": "This is great, thank you!", "session_id": "s1",
        }))
        await self._pump()
        await sub.unsubscribe()
        self.assertTrue(seen)
        self.assertGreater(seen[0].payload["valence"], seen[0].payload["previous"]["valence"])

    async def test_call_me_extracts_a_user_facet(self):
        seen = []
        sub = await self.requester.subscribe(topics.PERSONA_USER_MODEL_UPDATED, lambda m: seen.append(m) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.PERCEPT_TEXT_RECEIVED, {
            "channel": "cli", "text": "Please call me Ash", "session_id": "s1",
        }))
        await self._pump()
        await sub.unsubscribe()
        self.assertTrue(seen)
        self.assertEqual(seen[0].payload["facet"], "preferred_name")
        self.assertEqual(seen[0].payload["value"], "Ash")

    async def test_task_failed_lowers_valence(self):
        before = self.service._mood.current().valence
        await self.bus.publish(self.bus.new(topics.TASK_FAILED, {
            "task_id": "t1", "reason": "boom", "terminal": True, "attempts": 1,
        }))
        await self._pump()
        self.assertLess(self.service._mood.current().valence, before)

    async def test_critical_health_finding_resets_mood(self):
        await self.service._apply_and_announce(valence=0.5, arousal=0.5, source="test-setup")
        self.assertNotEqual(self.service._mood.current().valence, 0.0)
        await self.bus.publish(self.bus.new(topics.REFLECT_HEALTH_FINDING, {
            "severity": "critical", "detail": "loop detected", "action_taken": "request_reset",
        }))
        await self._pump()
        self.assertEqual(self.service._mood.current().valence, 0.0)
        self.assertEqual(self.service._mood.current().arousal, 0.0)

    async def test_voice_request_returns_style_and_mood_phrase(self):
        reply = await self.requester.request(
            self.requester.new(topics.PERSONA_VOICE, {"context": "chat"}), timeout=2,
        )
        self.assertIn("Simorgh is a test persona", reply.payload["style_block"])
        self.assertTrue(reply.payload["mood_phrase"])

    async def test_decay_moves_mood_toward_baseline_over_ticks(self):
        await self.service._apply_and_announce(valence=0.5, arousal=0.0, source="test-setup")
        self.clock.advance(600)
        await self.bus.publish(self.bus.new(topics.SYSTEM_TICK_SECOND, {"n": 1}))
        await self._pump()
        self.assertLess(self.service._mood.current().valence, 0.5)
        self.assertGreater(self.service._mood.current().valence, 0.0)

    async def test_share_proposal_is_paced_by_recent_user_activity(self):
        seen = []
        sub = await self.requester.subscribe(topics.UI_NOTICE, lambda m: seen.append(m) or asyncio.sleep(0))
        await self.bus.publish(self.bus.new(topics.PERCEPT_TEXT_RECEIVED, {
            "channel": "cli", "text": "hi", "session_id": "s1",
        }))
        await self._pump()
        await self.bus.publish(self.bus.new(topics.CURIOSITY_SHARE_PROPOSED, {
            "kind": "growth", "content_ref": "blob:abc",
        }))
        await self._pump()
        self.assertFalse(seen)  # quiet period after user activity -- suppressed, not shared

        self.clock.advance(60)
        await self.bus.publish(self.bus.new(topics.CURIOSITY_SHARE_PROPOSED, {
            "kind": "growth", "content_ref": "blob:abc",
        }))
        await self._pump()
        await sub.unsubscribe()
        self.assertTrue(seen)

    async def test_state_changed_suspends_sharing(self):
        await self.bus.publish(self.bus.new(topics.SYSTEM_STATE_CHANGED, {"state": "paused"}))
        await self._pump()
        self.assertTrue(self.service._share_policy._suspended)

    async def test_health_ok(self):
        health = await self.service.health()
        self.assertEqual(health.status, "ok")


if __name__ == "__main__":
    unittest.main()
