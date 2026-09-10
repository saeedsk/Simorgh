"""Reflection's pass has to run in a session shorter than six hours.

Until 2026-09-10 it did not. Pattern mining, calibration emission and
the `self.observation{kind:limitation}` that feeds `SELF.md`'s "What I
know I'm bad at" all hung off `system.tick.sleep` alone, and the
Kernel's sleep loop (`kernel/scheduler.py::_sleep_loop`) waits a full
`sleep_every_s` -- 21,600 seconds, six hours -- before its FIRST tick.
So Sim noticed things and told nobody, in essentially every session
anyone has ever run.

Proved on a real Kernel boot by observer bulk5-02: twelve
`learn.outcome.recorded(task_type=patch, succeeded=false,
confidence=0.9)` produced

    reflect.calibration.updated : 0
    reflect.patterns.found      : 0
    self.observation{limitation}: 0

after three seconds of a fully booted system, and all three the instant
a `system.tick.sleep` was published by hand. The pipeline downstream
was fine -- Planning queued a real `patch` task off the hand-fired tick
-- the trigger was simply unreachable.

The Ledger hit this exact shape on 2026-09-07 (`compact_after_start_s`,
190,865 expired streams still on disk) and Memory on 2026-09-10
(`consolidate_after_start_s`). This is the same fix for the subsystem
whose entire job is telling someone something.

This test never publishes a sleep tick.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.ledger.factory import make_ledger
from simorgh.reflection.config import Config as ReflectionConfig
from simorgh.reflection.service import Service

from tests.simorgh.helpers import FakeClock


class _Logger:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict]] = []

    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): self.warnings.append((event, f))
    def error(self, event, **f): pass


class ReflectionPassWithoutASleepTickTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="reflection", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.logger = _Logger()

        from simorgh.contracts.protocols import Context
        self.ctx = Context(
            name="reflection", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=self.logger, data_dir=Path(self._tmp.name) / "data",
        )
        self.driver = make_client(self.backend, source="test", ledger=self.ledger, clock=self.clock.now)
        await self.driver.start()
        self.seen: dict[str, list] = {"patterns": [], "calibration": [], "limitation": []}
        self._subs = [
            await self.driver.subscribe(topics.REFLECT_PATTERNS_FOUND,
                                        lambda m: self._see("patterns", m)),
            await self.driver.subscribe(topics.REFLECT_CALIBRATION_UPDATED,
                                        lambda m: self._see("calibration", m)),
            await self.driver.subscribe(topics.SELF_OBSERVATION, self._see_self),
        ]
        self.service: Service | None = None

    async def _see(self, bucket: str, message: Message) -> None:
        self.seen[bucket].append(message.payload)

    async def _see_self(self, message: Message) -> None:
        if message.payload.get("kind") == "limitation":
            self.seen["limitation"].append(message.payload)

    async def asyncTearDown(self) -> None:
        if self.service is not None:
            await self.service.stop()
        for sub in self._subs:
            await sub.unsubscribe()
        await self.driver.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _start(self, **overrides) -> Service:
        config = ReflectionConfig(
            pattern_min_samples=3, pattern_min_rate=0.5, calibration_min_samples=3,
            review_timeout_s=0.1, **overrides,
        )
        self.service = Service(config)
        await self.service.start(self.ctx)
        return self.service

    async def _record_three_failures(self) -> None:
        for i in range(3):
            await self.driver.publish(Message.new(
                topics.LEARN_OUTCOME_RECORDED, source="test", clock=self.clock.now,
                payload={"task_id": f"t{i}", "task_type": "patch", "succeeded": False,
                         "verdict": "fail", "cost_usd": 0.0, "duration_s": 1.0, "confidence": 0.9},
            ))
        for _ in range(20):
            await asyncio.sleep(0)

    async def test_the_pass_runs_without_any_sleep_tick(self) -> None:
        await self._start(reflect_after_start_s=0.05, reflect_every_s=0.0)
        await self._record_three_failures()
        # No "nothing yet" assertion here on purpose: under a loaded
        # `-n auto` run the 50ms first pass can legitimately land while
        # the driver is still pumping, and the claim under test is that
        # the pass happens at all without a sleep tick, not when.
        await asyncio.sleep(0.35)

        self.assertEqual(len(self.seen["patterns"]), 1, "no reflect.patterns.found without a sleep tick")
        self.assertEqual(self.seen["patterns"][0]["patterns"][0]["task_type"], "patch")
        self.assertEqual(len(self.seen["calibration"]), 1, "no reflect.calibration.updated without a sleep tick")
        self.assertEqual(self.seen["calibration"][0]["empirical_accuracy"], 0.0)
        self.assertEqual(self.seen["calibration"][0]["stated_confidence"], 0.9)
        self.assertEqual(len(self.seen["limitation"]), 1,
                         "SELF.md's 'what I'm bad at' gets nothing without a sleep tick")

    async def test_the_pass_repeats_on_its_own_cadence(self) -> None:
        await self._start(reflect_after_start_s=0.05, reflect_every_s=0.05)
        await self._record_three_failures()
        await asyncio.sleep(0.35)
        self.assertGreater(len(self.seen["patterns"]), 1,
                           "reflect_every_s must schedule further passes, not just the first")

    async def test_zero_disables_the_loop_entirely(self) -> None:
        await self._start(reflect_after_start_s=0.0)
        await self._record_three_failures()
        await asyncio.sleep(0.3)
        self.assertEqual(self.seen["patterns"], [],
                         "reflect_after_start_s=0 must leave only the six-hourly sleep tick")
        self.assertIsNone(self.service._reflect_loop)  # noqa: SLF001

    async def test_a_paused_system_does_not_reflect(self) -> None:
        # A deliberately long first delay: the pause has to be in
        # force BEFORE the first pass would fire, or the test is a race
        # rather than a check.
        service = await self._start(reflect_after_start_s=0.3, reflect_every_s=0.05)
        await self._record_three_failures()
        await self.driver.publish(Message.new(
            topics.SYSTEM_STATE_CHANGED, source="test", clock=self.clock.now,
            payload={"state": "paused", "reason": "test"},
        ))
        for _ in range(20):
            await asyncio.sleep(0)
        self.assertTrue(service._paused)  # noqa: SLF001
        await asyncio.sleep(0.6)
        self.assertEqual(self.seen["patterns"], [], "a paused system must not publish from the loop")

    async def test_a_confidence_that_is_not_a_probability_is_named_not_swallowed(self) -> None:
        """The other half of the same bug: a NaN or negative confidence
        used to raise inside the pass, aborting it mid-loop so every
        remaining task type silently never published. It must now be
        refused, said out loud, and not stop the good samples."""
        await self._start(reflect_after_start_s=0.05, reflect_every_s=0.0)
        await self.driver.publish(Message.new(
            topics.VERIFY_RESULT, source="test", clock=self.clock.now,
            payload={"verification_id": "v1", "task_id": "t-v1", "verdict": "fail", "checklist": [],
                     "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0},
                     "mechanical": {}, "confidence": -3.0},
        ))
        await self._record_three_failures()
        await asyncio.sleep(0.35)

        self.assertIn("reflection.calibration_sample_unusable",
                      [event for event, _ in self.logger.warnings])
        self.assertEqual(len(self.seen["calibration"]), 1,
                         "the good task type still publishes after a bad sample")
        self.assertEqual(self.seen["calibration"][0]["task_type"], "patch")


if __name__ == "__main__":
    unittest.main()
