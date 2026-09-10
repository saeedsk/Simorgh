"""`[reflection] stall_idle_seconds` finally does something.

12-reflection.md section 3.5 has said since the subsystem was designed:
"In-progress task with no step for this long -> `behavior` drift
`note`". Nothing read the field. `kernel/configcheck.py` listed it in
`KNOWN_DEAD_FIELDS`, which is honest about a knob being dead but does
not make a stalled task visible to anyone -- and a stall is precisely
the failure a person cannot see for themselves, because its symptom is
that nothing happens.

`system.tick.idle` is the right tick for it: the Kernel emits it only
when nothing is going on, which is the condition being looked for.
`reflect.drift.detected` already has a real consumer (Planning's
`_on_drift_detected`), so this reaches work rather than a log line.

Observer bulk5-02, 2026-09-10.
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


class StallDetectionTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
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
        # `reflect_after_start_s=0`: the periodic pass is a different
        # test's subject and would only add noise here.
        self.service = Service(ReflectionConfig(stall_idle_seconds=300.0, reflect_after_start_s=0.0))
        await self.service.start(self.ctx)
        self.driver = make_client(backend, source="test", ledger=self.ledger, clock=self.clock.now)
        await self.driver.start()
        self.drift: list[dict] = []
        self._sub = await self.driver.subscribe(topics.REFLECT_DRIFT_DETECTED, self._see)

    async def _see(self, message: Message) -> None:
        self.drift.append(message.payload)

    async def asyncTearDown(self) -> None:
        await self._sub.unsubscribe()
        await self.service.stop()
        await self.driver.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _pump(self, n: int = 20) -> None:
        for _ in range(n):
            await asyncio.sleep(0)

    async def _create_task(self, task_id: str = "t1") -> None:
        await self.driver.publish(Message.new(
            topics.TASK_CREATED, source="test", clock=self.clock.now,
            payload={"task_id": task_id, "kind": "patch", "description": "fix the widget",
                     "depends_on": [], "mode": "execute", "origin": "human", "risk": "low"},
        ))
        await self._pump()

    async def _step(self, task_id: str = "t1", step_no: int = 1) -> None:
        await self.driver.publish(Message.new(
            topics.TASK_STEP, source="test", clock=self.clock.now,
            payload={"task_id": task_id, "step_no": step_no, "phase": "act",
                     "summary": "did a thing", "tool": "read_source"},
        ))
        await self._pump()

    async def _idle_tick(self) -> None:
        await self.driver.publish(Message.new(
            topics.SYSTEM_TICK_IDLE, source="test", clock=self.clock.now,
            payload={"idle_seconds": 3.0},
        ))
        await self._pump()

    async def test_a_task_that_goes_quiet_is_reported(self) -> None:
        await self._create_task()
        await self._step()
        self.clock.advance(400.0)
        await self._idle_tick()

        self.assertEqual(len(self.drift), 1, "a stalled task must reach reflect.drift.detected")
        finding = self.drift[0]
        self.assertEqual(finding["kind"], "behavior")
        self.assertEqual(finding["recommendation"], "note")
        self.assertEqual(finding["task_id"], "t1")
        self.assertIn("no step for 400s", finding["evidence"])

    async def test_a_task_still_working_is_not_reported(self) -> None:
        await self._create_task()
        await self._step()
        self.clock.advance(100.0)
        await self._idle_tick()
        self.assertEqual(self.drift, [])

    async def test_a_stall_is_reported_once_not_every_tick(self) -> None:
        await self._create_task()
        await self._step()
        self.clock.advance(400.0)
        await self._idle_tick()
        self.clock.advance(400.0)
        await self._idle_tick()
        self.assertEqual(len(self.drift), 1, "an idle tick every ~3s must not become a flood")

    async def test_recovering_and_stalling_again_is_a_second_report(self) -> None:
        await self._create_task()
        await self._step()
        self.clock.advance(400.0)
        await self._idle_tick()
        await self._step(step_no=2)
        self.clock.advance(400.0)
        await self._idle_tick()
        self.assertEqual(len(self.drift), 2)

    async def test_a_finished_task_cannot_stall(self) -> None:
        await self._create_task()
        await self._step()
        await self.driver.publish(Message.new(
            topics.TASK_COMPLETED, source="test", clock=self.clock.now,
            payload={"task_id": "t1", "result_summary": "done", "steps": 1,
                     "cost_usd": 0.0, "duration_s": 1.0, "artifacts": [],
                     "verification_ref": "verify:t1"},
        ))
        await self._pump()
        self.drift.clear()
        self.clock.advance(400.0)
        await self._idle_tick()
        self.assertEqual(self.drift, [], "a task that ended is not a task that stalled")

    async def test_zero_disables_the_check(self) -> None:
        await self.service.stop()
        self.service = Service(ReflectionConfig(stall_idle_seconds=0.0, reflect_after_start_s=0.0))
        await self.service.start(self.ctx)
        await self._create_task()
        await self._step()
        self.clock.advance(100_000.0)
        await self._idle_tick()
        self.assertEqual(self.drift, [])

    async def test_the_check_runs_even_with_monitors_off(self) -> None:
        await self.service.stop()
        self.service = Service(ReflectionConfig(
            stall_idle_seconds=300.0, reflect_after_start_s=0.0, monitors_enabled=False))
        await self.service.start(self.ctx)
        await self._create_task("t2")
        await self._step("t2")
        self.clock.advance(400.0)
        await self._idle_tick()
        self.assertEqual(len(self.drift), 1, "the stall check is not a monitor")


if __name__ == "__main__":
    unittest.main()
