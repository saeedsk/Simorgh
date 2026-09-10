"""The wire between the alerting core (reflection/digest.py) and the
running system: an idle tick runs the due monitors, a raised alert
reaches the bus and the Ledger, and one that earned a person's
attention becomes a real `notify` call.

`digest.py`'s own tests cover *what* gets sent where. These cover the
part that is usually left unconnected -- a designed slot with one side
implemented and nobody writing to it, which is this project's dominant
bug shape. The assertions are all on messages that actually crossed the
bus."""

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
from simorgh.reflection.config import Config
from simorgh.reflection.digest import Alert
from simorgh.reflection.service import Service

from tests.simorgh.helpers import FakeClock


class _Logger:
    def __init__(self) -> None:
        self.warnings: list = []

    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def error(self, event, **f): pass

    def warning(self, event, **f):
        self.warnings.append((event, f))


class _Monitor:
    def __init__(self, name: str, alerts=None, *, interval_s: float = 0.0, raises=None) -> None:
        self.name = name
        self.interval_s = interval_s
        self.alerts = list(alerts or [])
        self.raises = raises
        self.checks = 0

    async def check(self, now: float):
        self.checks += 1
        if self.raises:
            raise self.raises
        return list(self.alerts)


class _AlertingTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="reflection", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.other = make_client(backend, source="other", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()
        self.logger = _Logger()
        self.seen: dict[str, list[Message]] = {}
        for topic in (topics.ACTION_PROPOSED, topics.REFLECT_ALERT_RAISED, topics.REFLECT_ALERT_CLEARED):
            await self._watch(topic)

    async def asyncTearDown(self):
        await self.service.stop()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()
        self._tmp.cleanup()

    async def _watch(self, topic: str) -> None:
        self.seen.setdefault(topic, [])

        async def _capture(message: Message) -> None:
            self.seen[topic].append(message)

        await self.other.subscribe(topic, _capture)

    async def _start(self, **config) -> Service:
        ctx = Context(
            name="reflection", instance_id="", run_id="test", mode="single",
            bus=self.bus, ledger=self.ledger, config={}, secrets={}, clock=self.clock,
            logger=self.logger, data_dir=Path(self._tmp.name) / "data",
        )
        self.service = Service(Config(**config))
        await self.service.start(ctx)
        return self.service

    async def _tick(self) -> None:
        await self.other.publish(Message.new(
            topics.SYSTEM_TICK_IDLE, source="other", payload={"idle_seconds": 300.0},
            clock=self.clock.now))
        for _ in range(20):
            await asyncio.sleep(0)

    def _proposals(self) -> list[dict]:
        return [m.payload for m in self.seen[topics.ACTION_PROPOSED]]


class MonitorTickTestCase(_AlertingTestCase):
    async def test_a_warning_becomes_a_notify_proposal(self):
        service = await self._start(quiet_hours="")
        service.register_monitor(_Monitor("sync", [Alert("sync", "warn", "imap:fastmail", "sync failed")]))
        await self._tick()

        proposals = self._proposals()
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["tool"], "notify")
        self.assertIn("sync failed", proposals[0]["args"]["body"])
        self.assertEqual(proposals[0]["reversibility"], "irreversible")

    async def test_the_notify_goes_through_guardian_rather_than_around_it(self):
        """An alerting path that reached for the tool directly would be
        the one irreversible thing in the system nobody was watching."""
        service = await self._start()
        service.register_monitor(_Monitor("m", [Alert("m", "critical", "k", "the boiler is off")]))
        await self._tick()
        self.assertEqual(len(self._proposals()), 1, "exactly one proposal, and it is a proposal")

    async def test_an_info_alert_is_held_for_the_digest_and_sends_nothing_now(self):
        service = await self._start()
        service.register_monitor(_Monitor("m", [Alert("m", "info", "k", "a small thing")]))
        await self._tick()
        self.assertEqual(self._proposals(), [])
        raised = self.seen[topics.REFLECT_ALERT_RAISED]
        self.assertEqual(raised[0].payload["channel"], "digest")

    async def test_a_raised_alert_reaches_the_bus_and_the_ledger(self):
        service = await self._start()
        service.register_monitor(_Monitor("certs", [Alert("certs", "warn", "cert:ha", "expires in 20 days",
                                                          entity="ha.local")]))
        await self._tick()

        raised = self.seen[topics.REFLECT_ALERT_RAISED]
        self.assertEqual(len(raised), 1)
        self.assertEqual(raised[0].payload["monitor"], "certs")
        self.assertEqual(raised[0].payload["entity"], "ha.local")
        self.assertTrue(raised[0].payload["reason"], "a delivery explains itself")

        events = await self.ledger.read(Service.ALERTS_STREAM)
        self.assertEqual([e.type for e in events], ["raised"])

    async def test_the_same_problem_on_the_next_tick_sends_nothing_more(self):
        alert = Alert("certs", "warn", "cert:ha", "expires in 20 days")
        service = await self._start()
        service.register_monitor(_Monitor("certs", [alert]))
        await self._tick()
        self.clock.advance(3600)
        await self._tick()
        self.assertEqual(len(self._proposals()), 1, "a certificate does not stop expiring")

    async def test_an_alert_that_stops_being_reported_is_published_as_cleared(self):
        monitor = _Monitor("certs", [Alert("certs", "warn", "cert:ha", "expires")])
        service = await self._start()
        service.register_monitor(monitor)
        await self._tick()
        monitor.alerts = []
        self.clock.advance(60)
        await self._tick()

        cleared = self.seen[topics.REFLECT_ALERT_CLEARED]
        self.assertEqual([m.payload["key"] for m in cleared], ["cert:ha"])
        events = await self.ledger.read(Service.ALERTS_STREAM)
        self.assertEqual([e.type for e in events], ["raised", "cleared"])

    async def test_a_regressed_alert_says_so_in_the_subject(self):
        monitor = _Monitor("certs", [Alert("certs", "warn", "k", "expired")])
        service = await self._start(alert_warn_window_s=0.0)
        service.register_monitor(monitor)
        await self._tick()
        monitor.alerts = []
        self.clock.advance(60)
        await self._tick()
        monitor.alerts = [Alert("certs", "warn", "k", "expired")]
        self.clock.advance(60)
        await self._tick()

        subjects = [p["args"]["subject"] for p in self._proposals()]
        self.assertEqual(len(subjects), 2)
        self.assertTrue(subjects[1].startswith("REGRESSED: "), subjects)

    async def test_a_monitor_that_raises_does_not_break_the_tick(self):
        service = await self._start()
        service.register_monitor(_Monitor("broken", raises=RuntimeError("boom")))
        service.register_monitor(_Monitor("fine", [Alert("fine", "warn", "k", "still here")]))
        await self._tick()
        self.assertEqual(len(self._proposals()), 1)

    async def test_monitors_can_be_switched_off_entirely(self):
        service = await self._start(monitors_enabled=False)
        monitor = _Monitor("m", [Alert("m", "critical", "k", "x")])
        service.register_monitor(monitor)
        await self._tick()
        self.assertEqual(monitor.checks, 0)
        self.assertEqual(self._proposals(), [])

    async def test_quiet_hours_hold_a_warning_but_not_a_critical(self):
        service = await self._start(quiet_hours="00:00-23:59")
        service.register_monitor(_Monitor("w", [Alert("w", "warn", "k", "a warning")]))
        service.register_monitor(_Monitor("c", [Alert("c", "critical", "k", "a critical")]))
        await self._tick()
        bodies = [p["args"]["body"] for p in self._proposals()]
        self.assertEqual(bodies, ["a critical"])

    async def test_a_malformed_quiet_hours_warns_and_does_not_become_no_quiet_hours(self):
        """Falling back to "" would send at 3am precisely because
        somebody tried to stop it -- so the fallback is logged, loudly."""
        await self._start(quiet_hours="late at night")
        self.assertIn("reflection.quiet_hours_invalid", [event for event, _ in self.logger.warnings])

    async def test_an_ad_hoc_alert_is_routed_like_any_other(self):
        service = await self._start()
        service.raise_alert(Alert("pim", "warn", "auth:google", "the token needs re-authorising"))
        await self._tick()
        self.assertIn("re-authorising", self._proposals()[0]["args"]["body"])

    async def test_an_ad_hoc_alert_does_not_resolve_the_others_from_that_source(self):
        service = await self._start(alert_warn_window_s=0.0)
        service.raise_alert(Alert("pim", "warn", "a", "first"))
        await self._tick()
        service.raise_alert(Alert("pim", "warn", "b", "second"))
        self.clock.advance(60)
        await self._tick()
        self.assertEqual(self.seen[topics.REFLECT_ALERT_CLEARED], [],
                         "a partial view must not clear what it did not mention")


class DigestTickTestCase(_AlertingTestCase):
    """The digest is anchored to the real local clock (it is a *daily*
    digest, and Reflection builds it with `time.localtime`), so these
    pick the next whole hour and step the fake clock over it. Hardcoding
    an hour would pass or fail depending on what time the suite ran."""

    def _next_hour(self) -> int:
        import time as _time

        return (_time.localtime(self.clock.now()).tm_hour + 1) % 24

    async def _start_and_cross_the_hour(self, **config):
        service = await self._start(digest_hour=self._next_hour(), **config)
        return service

    def _digests(self) -> list[dict]:
        return [p for p in self._proposals() if p["args"]["subject"] == "Simorgh daily digest"]

    async def test_the_digest_goes_out_once_and_carries_the_held_alerts(self):
        service = await self._start_and_cross_the_hour()
        service.register_monitor(_Monitor("m", [Alert("m", "info", "k", "a quiet thing")]))
        await self._tick()
        self.assertEqual(self._digests(), [], "not yet its hour")

        self.clock.advance(3600)
        await self._tick()
        self.assertEqual(len(self._digests()), 1)
        self.assertIn("a quiet thing", self._digests()[0]["args"]["body"])

        self.clock.advance(60)
        await self._tick()
        self.assertEqual(len(self._digests()), 1, "once a day, not once a tick")

    async def test_a_day_with_nothing_to_report_sends_no_digest(self):
        await self._start_and_cross_the_hour()
        self.clock.advance(3600)
        await self._tick()
        self.assertEqual(self._proposals(), [])

    async def test_the_digest_can_be_switched_off_without_switching_off_alerts(self):
        service = await self._start_and_cross_the_hour(digest_enabled=False)
        service.register_monitor(_Monitor("i", [Alert("i", "info", "k", "quiet")]))
        service.register_monitor(_Monitor("w", [Alert("w", "warn", "k", "loud")]))
        self.clock.advance(3600)
        await self._tick()
        self.assertEqual([p["args"]["body"] for p in self._proposals()], ["loud"])

    async def test_a_broken_monitor_is_named_in_the_digest(self):
        service = await self._start_and_cross_the_hour()
        service.register_monitor(_Monitor("broken", raises=RuntimeError("boom")))
        service.register_monitor(_Monitor("m", [Alert("m", "info", "k", "something")]))
        await self._tick()
        self.clock.advance(3600)
        await self._tick()
        body = self._digests()[0]["args"]["body"]
        self.assertIn("Monitors that failed to run", body)
        self.assertIn("broken", body)

    async def test_starting_after_the_hour_does_not_send_a_digest_at_boot(self):
        import time as _time

        past_hour = (_time.localtime(self.clock.now()).tm_hour - 1) % 24
        service = await self._start(digest_hour=past_hour)
        service.register_monitor(_Monitor("m", [Alert("m", "info", "k", "something")]))
        await self._tick()
        self.assertEqual(self._digests(), [])
