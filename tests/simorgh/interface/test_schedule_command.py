"""`schedule`: the door to a subsystem that had none.

The Kernel has had a complete scheduler since the beginning. It
subscribes to `system.schedule.add`, arms a timer, survives a restart by
replaying its own ledger stream, and fires `percept.time.scheduled`.
Every part of it works and is tested.

Nothing in the entire system ever published `system.schedule.add`, so
none of it could be reached -- a finished subsystem with no door. This
is the dominant bug shape in this codebase: a designed slot with one
side implemented and nobody writing to it.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.interface.dispatch import (
    SCHEDULE_STREAM,
    _schedule_command,
    _schedule_list,
    parse_delay,
)
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock


class _Bus:
    def __init__(self):
        self.published = []

    def new(self, topic, payload):
        return type("M", (), {"topic": topic, "payload": payload})()

    async def publish(self, message):
        self.published.append(message)


class _Clock:
    def now(self):
        return 1000.0


class DelayParsingTestCase(unittest.TestCase):
    def test_each_unit(self):
        self.assertEqual(parse_delay("30s"), 30.0)
        self.assertEqual(parse_delay("15m"), 900.0)
        self.assertEqual(parse_delay("2h"), 7200.0)
        self.assertEqual(parse_delay("1d"), 86400.0)

    def test_a_bare_number_is_refused(self):
        # "schedule 15 ..." is genuinely ambiguous; the unit is required
        # rather than guessed at.
        self.assertIsNone(parse_delay("15"))

    def test_nonsense_is_refused(self):
        for text in ("", "soon", "x", "-5m", "15y"):
            with self.subTest(text=text):
                self.assertIsNone(parse_delay(text))


class SchedulingTestCase(unittest.IsolatedAsyncioTestCase):
    async def _run(self, args, bus=None, ledger=None):
        bus = bus or _Bus()
        if ledger is None:
            ledger = make_ledger({"backend": "memory"}, clock=FakeClock())
            await ledger.start()
        outcome = await _schedule_command(args, bus=bus, ledger=ledger, clock=_Clock())
        return outcome, bus

    async def test_a_one_shot_publishes_an_absolute_time(self):
        outcome, bus = await self._run("15m water the plants")
        self.assertEqual(len(bus.published), 1)
        payload = bus.published[0].payload
        self.assertEqual(bus.published[0].topic, topics.SYSTEM_SCHEDULE_ADD)
        self.assertEqual(payload["at"], 1000.0 + 900.0)
        self.assertIsNone(payload["every_seconds"])
        self.assertEqual(payload["label"], "water the plants")
        self.assertIn("water the plants", outcome.text)

    async def test_a_recurring_one_publishes_an_interval(self):
        _outcome, bus = await self._run("every 1h check the build")
        payload = bus.published[0].payload
        self.assertIsNone(payload["at"])
        self.assertEqual(payload["every_seconds"], 3600.0)
        self.assertEqual(payload["label"], "check the build")

    async def test_exactly_one_of_at_and_every_is_set(self):
        # The Kernel rejects a payload with both or neither, silently
        # (a log line), so getting this wrong would look like nothing
        # happening at all.
        for args in ("15m a", "every 15m a"):
            with self.subTest(args=args):
                _outcome, bus = await self._run(args)
                payload = bus.published[0].payload
                self.assertNotEqual(payload["at"] is None, payload["every_seconds"] is None)

    async def test_a_missing_unit_explains_itself_and_publishes_nothing(self):
        outcome, bus = await self._run("15 water the plants")
        self.assertEqual(bus.published, [])
        self.assertIn("delay with a unit", outcome.text)

    async def test_a_missing_label_publishes_nothing(self):
        outcome, bus = await self._run("15m")
        self.assertEqual(bus.published, [])
        self.assertIn("something to say", outcome.text)

    async def test_every_schedule_gets_its_own_id(self):
        _o, bus = await self._run("15m a")
        _o2, bus2 = await self._run("15m a")
        self.assertNotEqual(bus.published[0].payload["schedule_id"],
                            bus2.published[0].payload["schedule_id"])


class ListingTestCase(unittest.IsolatedAsyncioTestCase):
    async def _ledger(self, events=()):
        ledger = make_ledger({"backend": "memory"}, clock=FakeClock())
        await ledger.start()
        for event in events:
            await ledger.append(SCHEDULE_STREAM, event)
        return ledger

    def _event(self, kind, schedule_id, **payload):
        return Event(
            stream=SCHEDULE_STREAM, type=kind, ts=0.0, trace_id="", causation_id=None,
            idempotency_key=f"{kind}-{schedule_id}",
            payload={"schedule_id": schedule_id, **payload},
        )

    async def test_nothing_scheduled_says_how_to_schedule_something(self):
        text = (await _schedule_list(await self._ledger())).text
        self.assertIn("nothing scheduled", text)
        self.assertIn("schedule 15m", text)

    async def test_it_lists_what_is_live(self):
        ledger = await self._ledger([
            self._event("schedule.added", "a1", fire_at=50.0, label="water the plants"),
        ])
        text = (await _schedule_list(ledger)).text
        self.assertIn("1 scheduled", text)
        self.assertIn("water the plants", text)

    async def test_a_cancelled_schedule_is_gone(self):
        ledger = await self._ledger([
            self._event("schedule.added", "a1", fire_at=50.0, label="gone"),
            self._event("schedule.cancelled", "a1"),
        ])
        self.assertIn("nothing scheduled", (await _schedule_list(ledger)).text)

    async def test_a_recurring_one_shows_its_interval(self):
        ledger = await self._ledger([
            self._event("schedule.added", "a1", fire_at=50.0, label="build",
                        recurrence={"every_s": 3600}),
        ])
        self.assertIn("every 3600s", (await _schedule_list(ledger)).text)

    async def test_an_unreadable_ledger_is_a_message_not_a_crash(self):
        class _Broken:
            async def read(self, _stream):
                raise OSError("gone")

        self.assertIn("could not read", (await _schedule_list(_Broken())).text)

    def test_the_stream_name_agrees_with_the_kernel(self):
        from simorgh.kernel.scheduler import SCHEDULE_STREAM as theirs

        self.assertEqual(SCHEDULE_STREAM, theirs)

    def test_it_is_a_recognised_command(self):
        from simorgh.interface.parser import COMMAND_NAMES

        self.assertIn("schedule", COMMAND_NAMES)


class ItReallyFiresTestCase(unittest.IsolatedAsyncioTestCase):
    """The point of the whole change. A unit test of the command proves
    a message was published; only a real Kernel proves the scheduler
    receives it, arms a timer, and fires."""

    async def test_a_scheduled_reminder_reaches_percept_time_scheduled(self):
        import asyncio
        import tempfile
        import time

        from simorgh.kernel.config import LoadedConfig
        from simorgh.kernel.secrets import EnvSecretStore
        from simorgh.kernel.service import Kernel

        class _RealClock:
            def now(self):
                return time.time()

        with tempfile.TemporaryDirectory() as tmp:
            kernel = Kernel(LoadedConfig({"runtime": {"data_dir": tmp}}, None),
                            secrets=EnvSecretStore({}))
            await kernel.boot()
            try:
                fired = []

                async def _on_fire(message):
                    fired.append(message)

                await kernel.bus.subscribe(topics.PERCEPT_TIME_SCHEDULED, _on_fire)
                await _schedule_command("1s water the plants", bus=kernel.bus,
                                        ledger=kernel.ledger, clock=_RealClock())
                for _ in range(40):
                    await asyncio.sleep(0.1)
                    if fired:
                        break
                self.assertTrue(fired, "the schedule never fired against a real Kernel")
                self.assertEqual(fired[0].payload.get("label"), "water the plants")
            finally:
                await kernel.shutdown()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
