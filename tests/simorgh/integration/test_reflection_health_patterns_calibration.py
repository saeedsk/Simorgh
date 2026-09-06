"""Reflection Service, over a real (memory-backend) Bus/Ledger and a real
Context -- same composition shape as the worldmodel package's own
`test_service.py`, plus the three scenarios named in this subsystem's
build directive:

1. persona.state.changed pinned at an extreme -> reflect.health.finding
   (severity=critical, action_taken=request_reset).
2. several task.failed for the same task kind -> reflect.patterns.found,
   with the terminal-task critique path (a `patch` kind) exercising real
   graceful degradation: no Cognition subsystem is running, so the
   `cognition.think` request times out and a floor critique is used --
   never a fabricated one.
3. a task.completed(confidence=0.9) whose task_type later turns out to
   have failed (a following learn.outcome.recorded(succeeded=false,
   confidence=0.9) for the same task_type) shows up as a miscalibration
   in a later reflect.calibration.updated (stated 0.9, empirical lower).

No Cognition or Learning subsystem is started at all in this test --
only Reflection, over a real Bus/Ledger -- proving it operates standalone
and degrades honestly rather than hanging or fabricating.
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context
from simorgh.ledger.factory import make_ledger
from simorgh.reflection.config import Config as ReflectionConfig
from simorgh.reflection.service import Service

from tests.simorgh.helpers import FakeClock


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


async def _pump(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class ReflectionIntegrationTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()

        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="reflection", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()

        self.ctx = Context(
            name="reflection", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=_Logger(), data_dir=Path(self._tmp.name) / "data",
        )
        self.config = ReflectionConfig(
            pattern_min_samples=3, pattern_min_rate=0.5,
            calibration_min_samples=2,
            review_timeout_s=0.2,
        )
        self.service = Service(self.config)
        await self.service.start(self.ctx)

        self.driver = make_client(backend, source="test", ledger=self.ledger, clock=self.clock.now)
        await self.driver.start()

    async def asyncTearDown(self):
        await self.service.stop()
        await self.driver.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    def _collect(self) -> tuple:
        seen: list = []

        async def _handler(message):
            seen.append(message.payload)
        return seen, _handler

    async def _create_task(self, task_id: str, kind: str) -> None:
        await self.driver.publish(self.driver.new(topics.TASK_CREATED, {
            "task_id": task_id, "kind": kind, "description": f"test task {task_id}",
            "depends_on": [], "mode": "execute", "origin": "human", "risk": "low",
        }))

    # -- 1. health -----------------------------------------------------------------------

    async def test_persona_pinned_at_extreme_triggers_critical_health_finding(self):
        seen, handler = self._collect()
        await self.driver.subscribe(topics.REFLECT_HEALTH_FINDING, handler)
        await _pump()

        for i in range(self.config.health_pinned_n):
            await self.driver.publish(self.driver.new(topics.PERSONA_STATE_CHANGED, {
                "valence": -0.95, "arousal": 0.0, "cognitive_load": 0.1, "source": "logic",
                "previous": {"valence": 0.0, "arousal": 0.0, "cognitive_load": 0.1},
            }))
        await _pump()

        # findings are emitted only on a severity *change* (service.py's
        # loop guard), so a warn finding lands first at 3 pinned
        # transitions and a critical one at the configured pinned_n --
        # the final finding is what matters here.
        self.assertGreaterEqual(len(seen), 1)
        self.assertEqual(seen[-1]["severity"], "critical")
        self.assertEqual(seen[-1]["action_taken"], "request_reset")

    # -- 2. patterns (+ graceful critique degradation) ------------------------------------

    async def test_repeated_task_failures_trigger_patterns_found_with_graceful_critique(self):
        seen, handler = self._collect()
        await self.driver.subscribe(topics.REFLECT_PATTERNS_FOUND, handler)
        mem_seen, mem_handler = self._collect()
        await self.driver.subscribe(topics.MEMORY_STORE, mem_handler)
        await _pump()

        for i in range(3):
            task_id = f"patch-{i}"
            await self._create_task(task_id, "patch")
            await self.driver.publish(self.driver.new(topics.TASK_FAILED, {
                "task_id": task_id, "reason": "tests still failing", "terminal": True, "attempts": 1,
            }))
        # each patch-kind failure runs the critique path against a
        # nonexistent Cognition -- request_or_error must time out
        # (bounded by review_timeout_s) rather than hang, and fall back
        # to a floor critique rather than fabricate one.
        await asyncio.wait_for(self._wait_for(mem_seen, 3), timeout=5)

        await self.driver.publish(self.driver.new(topics.SYSTEM_TICK_SLEEP, {"window_seconds": 86400.0}))
        await _pump()

        self.assertEqual(len(seen), 1)
        patterns = seen[0]["patterns"]
        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["kind"], "failure_rate")
        self.assertAlmostEqual(patterns[0]["rate"], 1.0)

        # floor critiques really were used (no fabricated confidence),
        # recorded to the critique ledger stream for each failed task.
        for i in range(3):
            events = await self.ledger.read(f"reflect:critique:patch-{i}", from_seq=0)
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0].payload["floor"])
            self.assertIsNone(events[0].payload["confidence"])

    async def _wait_for(self, seen: list, n: int) -> None:
        while len(seen) < n:
            await asyncio.sleep(0.01)

    # -- 3. calibration --------------------------------------------------------------------

    async def test_confident_completion_later_revealed_as_failure_shows_miscalibration(self):
        seen, handler = self._collect()
        await self.driver.subscribe(topics.REFLECT_CALIBRATION_UPDATED, handler)
        await _pump()

        task_id = "cal-1"
        await self._create_task(task_id, "chat")
        await self.driver.publish(self.driver.new(topics.TASK_COMPLETED, {
            "task_id": task_id, "result_summary": "looked done", "artifacts": [],
            "verification_ref": None, "confidence": 0.9,
        }))
        await _pump()

        # a second, differently-confident chat completion so the
        # calibration table's min_samples (2) is reached without relying
        # on the contradicting sample alone.
        task_id_2 = "cal-2"
        await self._create_task(task_id_2, "chat")
        await self.driver.publish(self.driver.new(topics.TASK_COMPLETED, {
            "task_id": task_id_2, "result_summary": "looked done too", "artifacts": [],
            "verification_ref": None, "confidence": 0.9,
        }))
        await _pump()

        # the same task later turns out to have actually failed --
        # learning's own outcome-recording disagrees with the stated
        # confidence at completion time.
        await self.driver.publish(self.driver.new(topics.LEARN_OUTCOME_RECORDED, {
            "task_id": task_id, "task_type": "chat", "succeeded": False, "verdict": "fail",
            "cost_usd": 0.0, "duration_s": 1.0, "confidence": 0.9,
        }))
        await _pump()

        await self.driver.publish(self.driver.new(topics.SYSTEM_TICK_SLEEP, {"window_seconds": 86400.0}))
        await _pump()

        chat_updates = [p for p in seen if p["task_type"] == "chat"]
        self.assertEqual(len(chat_updates), 1)
        update = chat_updates[0]
        self.assertAlmostEqual(update["stated_confidence"], 0.9)
        # stated 0.9 confidence but only 2/3 of the recorded outcomes
        # actually succeeded -- a real, honestly-computed miscalibration.
        self.assertLess(update["empirical_accuracy"], update["stated_confidence"])

    async def test_health_ok(self):
        health = await self.service.health()
        self.assertEqual(health.status, "ok")


if __name__ == "__main__":
    unittest.main()
