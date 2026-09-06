"""Flow 5, Kernel side (docs/blueprint/02 section 5 / subsystems/03-kernel.md
section 5.2/5.5): `test_flow_5_pause_preempts_backlog.py` proves the bus
delivers `system.pause` ahead of a backlog; this proves the *consequence*
once it lands on a real Kernel -- the state machine flips to `paused`,
the Scheduler's idle/sleep ticks (which read `is_running` from that very
state) actually stop firing, `resume` un-suspends them, and `stop` drains
the whole thing to `stopped` without leaving a wedged tick loop running
past its owner."""

import asyncio
import tempfile
import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import PAUSED, RUNNING, STOPPED
from tests.simorgh.helpers import FakeClock


async def _pump(n: int = 60) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


def _make_kernel(tmp: str, *, idle_threshold_s: float = 5.0) -> Kernel:
    config = LoadedConfig({"runtime": {"data_dir": tmp, "idle_threshold_s": idle_threshold_s,
                                       "idle_tick_cooldown_s": 1.0, "sleep_every_s": 999999.0}}, None)
    return Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())


class TestPauseResumeStopFlow(unittest.IsolatedAsyncioTestCase):
    async def test_pause_suspends_idle_ticks_resume_restores_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            ticks: list[Message] = []
            sub = await kernel.bus.subscribe(topics.SYSTEM_TICK_IDLE, lambda m: ticks.append(m) or asyncio.sleep(0))
            try:
                # Running: idle ticks accumulate as the clock self-advances
                # inside the Scheduler's own tick loops.
                await _pump(200)
                self.assertGreater(len(ticks), 0, "expected at least one idle tick while running")

                await kernel.bus.publish(Message.new(
                    topics.SYSTEM_PAUSE, source="interface",
                    payload={"reason": "human", "requested_by": "interface"}, priority=9,
                ))
                await _pump()
                self.assertEqual(kernel.state.state, PAUSED)

                ticks.clear()
                await _pump(200)
                self.assertEqual(ticks, [], "no idle ticks should fire while paused")

                await kernel.bus.publish(Message.new(
                    topics.SYSTEM_RESUME, source="interface",
                    payload={"reason": "human", "requested_by": "interface"}, priority=9,
                ))
                await _pump()
                self.assertEqual(kernel.state.state, RUNNING)

                ticks.clear()
                await _pump(200)
                self.assertGreater(len(ticks), 0, "idle ticks should resume once running again")
            finally:
                await sub.unsubscribe()
                await kernel.shutdown()

    async def test_stop_drains_to_stopped_and_the_scheduler_stops_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            try:
                await kernel.bus.publish(Message.new(
                    topics.SYSTEM_STOP, source="interface",
                    payload={"reason": "shutdown", "requested_by": "interface"}, priority=9,
                ))
                await asyncio.wait_for(kernel.wait_for_stop(), timeout=1.0)
            finally:
                await kernel.shutdown()
            self.assertEqual(kernel.state.state, STOPPED)
            # the scheduler's own tasks were cancelled by shutdown(), not left running
            self.assertEqual(kernel._scheduler._tasks, [])  # noqa: SLF001

    async def test_stop_from_paused_proceeds_directly_to_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = _make_kernel(tmp)
            await kernel.boot()
            await kernel.bus.publish(Message.new(
                topics.SYSTEM_PAUSE, source="interface",
                payload={"reason": "human", "requested_by": "interface"}, priority=9,
            ))
            await _pump()
            self.assertEqual(kernel.state.state, PAUSED)
            await kernel.bus.publish(Message.new(
                topics.SYSTEM_STOP, source="interface",
                payload={"reason": "shutdown", "requested_by": "interface"}, priority=9,
            ))
            await asyncio.wait_for(kernel.wait_for_stop(), timeout=1.0)
            await kernel.shutdown()
            self.assertEqual(kernel.state.state, STOPPED)


if __name__ == "__main__":
    unittest.main()
