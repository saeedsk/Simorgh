import asyncio
import unittest

from simorgh.bus.enforcement import ReservedTopologyPolicy
from simorgh.bus.factory import make_backend, make_client
from simorgh.bus.config import Config as BusConfig
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.ledger.backends.memory import InMemoryBackend
from simorgh.ledger.client import LedgerClient
from simorgh.kernel.scheduler import ActivityClock, Scheduler, parse_duration
from tests.simorgh.helpers import FakeClock


class TestParseDuration(unittest.TestCase):
    def test_bare_number_is_seconds(self):
        self.assertEqual(parse_duration("30"), 30.0)

    def test_minutes(self):
        self.assertEqual(parse_duration("1m"), 60.0)

    def test_hours_case_insensitive(self):
        self.assertEqual(parse_duration("2H"), 7200.0)

    def test_fractional(self):
        self.assertEqual(parse_duration("1.5m"), 90.0)

    def test_unparseable_returns_none(self):
        self.assertIsNone(parse_duration("whenever"))

    def test_non_positive_returns_none(self):
        self.assertIsNone(parse_duration("0"))
        self.assertIsNone(parse_duration("-5"))

    def test_over_max_returns_none(self):
        self.assertIsNone(parse_duration("999999", max_seconds=86400))


class TestActivityClock(unittest.TestCase):
    def test_starts_at_zero_idle(self):
        clock = FakeClock()
        activity = ActivityClock(clock)
        self.assertEqual(activity.idle_seconds(), 0.0)

    def test_idle_grows_with_the_clock(self):
        clock = FakeClock()
        activity = ActivityClock(clock)
        clock.advance(15)
        self.assertEqual(activity.idle_seconds(), 15.0)

    def test_touch_resets_idle(self):
        clock = FakeClock()
        activity = ActivityClock(clock)
        clock.advance(15)
        activity.touch()
        self.assertEqual(activity.idle_seconds(), 0.0)


class _NullLogger:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


async def _pump(n: int = 10) -> None:
    """Gives every pending task (tick loops, bus dispatch, `_fire_after`
    coroutines) a chance to run. `FakeClock.sleep` never blocks on real
    wall time -- it advances and yields once -- so pumping the loop is
    what actually lets those tasks make progress in a test."""
    for _ in range(n):
        await asyncio.sleep(0)


async def _make_bus_and_ledger(clock: FakeClock):
    ledger = LedgerClient(InMemoryBackend())
    await ledger.start()
    backend = make_backend(BusConfig(), clock=clock)
    await backend.start()
    policy = ReservedTopologyPolicy()
    bus = make_client(backend, source="kernel", ledger=ledger, clock=clock, policy=policy)
    return backend, bus, ledger


class TestSchedulerTicks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.backend, self.bus, self.ledger = await _make_bus_and_ledger(self.clock)
        self.received: list[Message] = []

        async def _collect(message: Message) -> None:
            self.received.append(message)

        self._sub = await self.bus.subscribe(topics.SYSTEM_TICK_IDLE, _collect)
        self.scheduler = Scheduler(
            bus=self.bus, ledger=self.ledger, clock=self.clock, logger=_NullLogger(),
            idle_threshold_s=10.0, idle_tick_cooldown_s=3.0, sleep_every_s=3600.0,
            max_schedule_duration_s=86400.0, is_running=lambda: True,
        )
        await self.scheduler.start()

    async def asyncTearDown(self):
        await self.scheduler.stop()
        await self._sub.unsubscribe()
        await self.backend.stop()
        await self.ledger.stop()

    async def test_idle_tick_fires_once_threshold_and_cooldown_elapse(self):
        # Every loop iteration self-advances the fake clock (`FakeClock.sleep`),
        # so simply pumping the event loop lets idle time accumulate past the
        # threshold without the test having to race real wall-clock time.
        await _pump(200)
        self.assertGreaterEqual(len(self.received), 1)
        self.assertGreaterEqual(self.received[0].payload["idle_seconds"], 10.0)


class TestSchedulerTicksWhenNotRunning(unittest.IsolatedAsyncioTestCase):
    async def test_no_idle_tick_when_not_running(self):
        # Built with is_running=False from the start (rather than flipped
        # after start()) -- background tick tasks are queued the instant
        # start() creates them and can run before any later line in this
        # test gets a turn, so mutating after the fact races the loop.
        clock = FakeClock()
        backend, bus, ledger = await _make_bus_and_ledger(clock)
        received: list[Message] = []

        async def _collect(message: Message) -> None:
            received.append(message)

        sub = await bus.subscribe(topics.SYSTEM_TICK_IDLE, _collect)
        scheduler = Scheduler(
            bus=bus, ledger=ledger, clock=clock, logger=_NullLogger(),
            idle_threshold_s=10.0, idle_tick_cooldown_s=3.0, sleep_every_s=3600.0,
            max_schedule_duration_s=86400.0, is_running=lambda: False,
        )
        await scheduler.start()
        try:
            await _pump(200)
            self.assertEqual(received, [])
        finally:
            await scheduler.stop()
            await sub.unsubscribe()
            await backend.stop()
            await ledger.stop()


class TestSchedulerDurableSchedules(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.backend, self.bus, self.ledger = await _make_bus_and_ledger(self.clock)
        self.fired: list[Message] = []

        async def _collect(message: Message) -> None:
            self.fired.append(message)

        self._sub = await self.bus.subscribe(topics.PERCEPT_TIME_SCHEDULED, _collect)
        self.scheduler = Scheduler(
            bus=self.bus, ledger=self.ledger, clock=self.clock, logger=_NullLogger(),
            idle_threshold_s=999999.0, idle_tick_cooldown_s=3.0, sleep_every_s=999999.0,
            max_schedule_duration_s=86400.0, is_running=lambda: True,
        )
        await self.scheduler.start()

    async def asyncTearDown(self):
        await self.scheduler.stop()
        await self._sub.unsubscribe()
        await self.backend.stop()
        await self.ledger.stop()

    async def test_add_then_fire(self):
        await self.bus.publish(Message.new(
            topics.SYSTEM_SCHEDULE_ADD, source="interface",
            payload={"schedule_id": "s1", "at": self.clock.now() + 60.0, "label": "call the vet"},
        ))
        await _pump(50)
        self.assertEqual(len(self.fired), 1)
        self.assertEqual(self.fired[0].payload["label"], "call the vet")
        state = self.scheduler._view.state()  # noqa: SLF001
        self.assertIn("s1", state)

    async def test_cancel_marks_the_schedule_cancelled_and_drops_the_armed_task(self):
        await self.bus.publish(Message.new(
            topics.SYSTEM_SCHEDULE_ADD, source="interface",
            payload={"schedule_id": "s2", "at": self.clock.now() + 30.0, "label": "x"},
        ))
        await _pump(3)  # let schedule.add / _arm land, but not the full fire-after chain
        await self.bus.publish(Message.new(
            topics.SYSTEM_SCHEDULE_CANCEL, source="interface", payload={"schedule_id": "s2"},
        ))
        await _pump(5)
        state = self.scheduler._view.state()  # noqa: SLF001
        self.assertTrue(state["s2"]["cancelled"])
        self.assertNotIn("s2", self.scheduler._armed)  # noqa: SLF001

    async def test_recurring_schedule_re_arms_after_firing(self):
        await self.bus.publish(Message.new(
            topics.SYSTEM_SCHEDULE_ADD, source="interface",
            payload={"schedule_id": "s3", "every_seconds": 10.0, "label": "tick"},
        ))
        await _pump(50)
        self.assertGreaterEqual(len(self.fired), 2)
        state = self.scheduler._view.state()  # noqa: SLF001
        self.assertFalse(state["s3"]["cancelled"])
        self.assertIn("s3", self.scheduler._armed)  # noqa: SLF001 -- re-armed for the next occurrence

    async def test_restart_resumes_an_active_schedule_from_the_ledger(self):
        await self.bus.publish(Message.new(
            topics.SYSTEM_SCHEDULE_ADD, source="interface",
            payload={"schedule_id": "s4", "at": self.clock.now() + 3600.0, "label": "resumed"},
        ))
        await _pump(3)
        await self.scheduler.stop()

        restarted = Scheduler(
            bus=self.bus, ledger=self.ledger, clock=self.clock, logger=_NullLogger(),
            idle_threshold_s=999999.0, idle_tick_cooldown_s=3.0, sleep_every_s=999999.0,
            max_schedule_duration_s=86400.0, is_running=lambda: True,
        )
        await restarted.start()
        try:
            await _pump(50)
            self.assertGreaterEqual(len(self.fired), 1)
            self.assertEqual(self.fired[-1].payload["label"], "resumed")
        finally:
            await restarted.stop()


if __name__ == "__main__":
    unittest.main()
