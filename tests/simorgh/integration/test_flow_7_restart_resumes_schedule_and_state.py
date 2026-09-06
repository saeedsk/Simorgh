"""Flow 7 (docs/blueprint/02 section 5 / subsystems/03-kernel.md section
5.5): a v1 reminder was a `threading.Timer` a restart simply forgot; here
`system.schedule.add` is durable -- appended to the Ledger before
anything is armed -- so a second, independent `Kernel` process pointed at
the same on-disk data directory re-arms every outstanding schedule from
exactly where the first one left off, and boots to a clean `running`
state regardless of how the first one ended."""

import asyncio
import tempfile
import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING
from tests.simorgh.helpers import FakeClock


class _HangingClock(FakeClock):
    """Ticks/timers that `await sleep()` never come back -- guarantees
    kernel1 cannot possibly fire the schedule itself, so kernel2 firing it
    is unambiguous proof of resumption, not a race against a real timer."""

    async def sleep(self, seconds: float) -> None:
        await asyncio.Future()  # never resolves; cancelled cleanly by shutdown()


async def _pump(n: int = 50) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


def _make_kernel(tmp: str, clock) -> Kernel:
    config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)
    return Kernel(config, secrets=EnvSecretStore({}), clock=clock)


class TestRestartResumesScheduleAndState(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_added_before_a_crash_fires_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel1 = _make_kernel(tmp, _HangingClock())
            await kernel1.boot()
            await kernel1.bus.publish(Message.new(
                topics.SYSTEM_SCHEDULE_ADD, source="interface",
                payload={"schedule_id": "s1", "at": kernel1._clock.now() + 3600.0, "label": "resumed after restart"},  # noqa: SLF001
            ))
            # Wait (real, small, bounded) only until the durable append lands
            # -- never until it fires, since the hanging clock guarantees it can't.
            for _ in range(200):
                if any(e.type == "schedule.added" for e in await kernel1.ledger.read("schedule")):
                    break
                await asyncio.sleep(0.005)
            else:
                self.fail("schedule.added never landed in the ledger")
            fired_in_kernel1: list[Message] = []
            sub = await kernel1.bus.subscribe(topics.PERCEPT_TIME_SCHEDULED, lambda m: fired_in_kernel1.append(m) or asyncio.sleep(0))
            await _pump(50)
            self.assertEqual(fired_in_kernel1, [], "the hanging clock must prevent kernel1 from ever firing it")
            await sub.unsubscribe()
            await kernel1.shutdown()  # simulates a crash/restart: the armed timer is simply gone

            kernel2 = _make_kernel(tmp, FakeClock())
            fired_in_kernel2: list[Message] = []

            async def _collect(m: Message) -> None:
                fired_in_kernel2.append(m)

            await kernel2.boot()
            try:
                self.assertEqual(kernel2.state.state, RUNNING)  # a fresh, clean boot regardless of how kernel1 ended
                sub2 = await kernel2.bus.subscribe(topics.PERCEPT_TIME_SCHEDULED, _collect)
                try:
                    await _pump(50)
                    self.assertEqual(len(fired_in_kernel2), 1)
                    self.assertEqual(fired_in_kernel2[0].payload["schedule_id"], "s1")
                    self.assertEqual(fired_in_kernel2[0].payload["label"], "resumed after restart")
                finally:
                    await sub2.unsubscribe()
            finally:
                await kernel2.shutdown()

    async def test_a_cancelled_schedule_does_not_resurrect_on_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel1 = _make_kernel(tmp, _HangingClock())
            await kernel1.boot()
            await kernel1.bus.publish(Message.new(
                topics.SYSTEM_SCHEDULE_ADD, source="interface",
                payload={"schedule_id": "s2", "at": kernel1._clock.now() + 3600.0, "label": "cancel me"},  # noqa: SLF001
            ))
            for _ in range(200):
                if any(e.type == "schedule.added" for e in await kernel1.ledger.read("schedule")):
                    break
                await asyncio.sleep(0.005)
            else:
                self.fail("schedule.added never landed in the ledger")
            await kernel1.bus.publish(Message.new(
                topics.SYSTEM_SCHEDULE_CANCEL, source="interface", payload={"schedule_id": "s2"},
            ))
            for _ in range(200):
                if any(e.type == "schedule.cancelled" for e in await kernel1.ledger.read("schedule")):
                    break
                await asyncio.sleep(0.005)
            else:
                self.fail("schedule.cancelled never landed in the ledger")
            await kernel1.shutdown()

            kernel2 = _make_kernel(tmp, FakeClock())
            fired: list[Message] = []
            await kernel2.boot()
            try:
                sub = await kernel2.bus.subscribe(topics.PERCEPT_TIME_SCHEDULED, lambda m: fired.append(m) or asyncio.sleep(0))
                try:
                    await _pump(50)
                    self.assertEqual(fired, [])
                finally:
                    await sub.unsubscribe()
            finally:
                await kernel2.shutdown()


if __name__ == "__main__":
    unittest.main()
