"""Monitors, alert routing, and the daily digest
(simorgh/reflection/digest.py; platform-connectors-design.md section 6).

Five designs had each specified their own copy of this. The interesting
half is not "notice a problem" -- it is deciding what is worth waking a
person for, which is exactly the half that is hard to test against a
running system and easy to test here, where the clock is a lambda."""

from __future__ import annotations

import time
import unittest

from simorgh.reflection.digest import (
    Alert,
    AlertRouter,
    Digest,
    Monitor,
    MonitorRegistry,
    in_quiet_hours,
    parse_quiet_hours,
)


class _Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _Calendar:
    """A `localtime` stand-in whose hour and day are derived from the
    timestamp, so advancing the clock actually moves the wall clock.

    A version of this pinned to a fixed hour hid a real bug for one
    round: with the wall clock frozen, a digest could never become due
    by the passage of time, only by construction.
    """

    def __init__(self, start_hour: int, epoch: float = 1_000_000.0) -> None:
        self.start_hour = start_hour
        self.epoch = epoch

    def __call__(self, ts: float) -> time.struct_time:
        total_hours = self.start_hour + (ts - self.epoch) / 3600.0
        day_offset = int(total_hours // 24)
        hour = int(total_hours % 24)
        return time.struct_time((2026, 9, 9 + day_offset, hour, 0, 0, 2, 252 + day_offset, 0))


def _at_hour(hour: int):
    return _Calendar(hour)


class _FakeMonitor:
    def __init__(self, name: str, alerts=None, *, interval_s: float = 60.0, raises=None) -> None:
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


class AlertShapeTestCase(unittest.TestCase):
    def test_an_alert_needs_a_key_because_the_key_is_what_dedupes_it(self):
        with self.assertRaises(ValueError):
            Alert("m", "warn", "", "no key")

    def test_an_unknown_severity_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            Alert("m", "urgent", "k", "msg")

    def test_identity_is_the_monitor_and_the_key(self):
        self.assertEqual(Alert("m", "info", "k", "x").ident, ("m", "k"))


class QuietHoursTestCase(unittest.TestCase):
    def test_a_window_parses_to_hours(self):
        self.assertEqual(parse_quiet_hours("22:00-07:00"), (22, 7))

    def test_an_empty_spec_means_no_quiet_hours(self):
        self.assertIsNone(parse_quiet_hours(""))

    def test_a_malformed_spec_is_refused_rather_than_silently_ignored(self):
        with self.assertRaises(ValueError):
            parse_quiet_hours("late at night")

    def test_an_hour_out_of_range_is_refused(self):
        with self.assertRaises(ValueError):
            parse_quiet_hours("25:00-07:00")

    def test_a_window_that_wraps_midnight(self):
        window = (22, 7)
        self.assertTrue(in_quiet_hours(23, window))
        self.assertTrue(in_quiet_hours(3, window))
        self.assertFalse(in_quiet_hours(12, window))
        self.assertFalse(in_quiet_hours(7, window), "the end hour is exclusive")

    def test_a_window_inside_one_day(self):
        window = (9, 17)
        self.assertTrue(in_quiet_hours(12, window))
        self.assertFalse(in_quiet_hours(20, window))

    def test_no_window_is_never_quiet(self):
        self.assertFalse(in_quiet_hours(3, None))


class IdempotenceTestCase(unittest.TestCase):
    """A monitor reports everything it sees, every time. Only the
    transition is news -- a certificate does not stop expiring because
    it has been mentioned."""

    def setUp(self):
        self.clock = _Clock()
        self.router = AlertRouter(clock=self.clock, localtime=_at_hour(12))

    def test_the_first_sighting_is_delivered(self):
        sent, resolved = self.router.observe("certs", [Alert("certs", "warn", "cert:ha", "expires in 20 days")])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].channel, "notify")
        self.assertEqual(resolved, [])

    def test_the_same_problem_seen_again_says_nothing(self):
        alert = Alert("certs", "warn", "cert:ha", "expires in 20 days")
        self.router.observe("certs", [alert])
        self.clock.advance(86400)
        sent, _ = self.router.observe("certs", [alert])
        self.assertEqual(sent, [])

    def test_a_changed_message_for_the_same_key_still_says_nothing(self):
        self.router.observe("certs", [Alert("certs", "warn", "cert:ha", "expires in 20 days")])
        sent, _ = self.router.observe("certs", [Alert("certs", "warn", "cert:ha", "expires in 19 days")])
        self.assertEqual(sent, [])
        self.assertEqual(self.router.open_alerts[0].message, "expires in 19 days",
                         "the newest wording is kept even though nothing is sent")

    def test_an_alert_the_monitor_stops_reporting_is_resolved(self):
        self.router.observe("certs", [Alert("certs", "warn", "cert:ha", "x")])
        sent, resolved = self.router.observe("certs", [])
        self.assertEqual(sent, [])
        self.assertEqual([a.key for a in resolved], ["cert:ha"])
        self.assertEqual(self.router.open_alerts, [])

    def test_a_problem_that_comes_back_is_reported_as_a_reopening(self):
        alert = Alert("certs", "critical", "cert:ha", "expired")
        self.router.observe("certs", [alert])
        self.router.observe("certs", [])
        sent, _ = self.router.observe("certs", [alert])
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].reopened, 1, "regressed, not new")

    def test_one_monitor_cannot_resolve_another_monitors_alerts(self):
        self.router.observe("certs", [Alert("certs", "warn", "k", "x")])
        sent, resolved = self.router.observe("ports", [])
        self.assertEqual((sent, resolved), ([], []))
        self.assertEqual(len(self.router.open_alerts), 1)

    def test_an_alert_attributed_to_another_monitor_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            self.router.observe("certs", [Alert("ports", "warn", "k", "x")])

    def test_clearing_by_hand_resolves_it(self):
        self.router.observe("certs", [Alert("certs", "warn", "k", "x")])
        self.assertIsNotNone(self.router.clear("certs", "k"))
        self.assertEqual(self.router.open_alerts, [])

    def test_open_alerts_can_be_read_per_monitor(self):
        self.router.observe("a", [Alert("a", "info", "1", "x")])
        self.router.observe("b", [Alert("b", "info", "2", "y")])
        self.assertEqual([a.key for a in self.router.open_for("a")], ["1"])


class RoutingTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()

    def _router(self, **kwargs):
        kwargs.setdefault("localtime", _at_hour(12))
        return AlertRouter(clock=self.clock, **kwargs)

    def test_info_goes_to_the_digest(self):
        router = self._router()
        sent, _ = router.observe("m", [Alert("m", "info", "k", "x")])
        self.assertEqual(sent[0].channel, "digest")

    def test_warn_notifies_a_person(self):
        router = self._router()
        sent, _ = router.observe("m", [Alert("m", "warn", "k", "x")])
        self.assertEqual(sent[0].channel, "notify")

    def test_critical_notifies_immediately(self):
        router = self._router()
        sent, _ = router.observe("m", [Alert("m", "critical", "k", "x")])
        self.assertEqual(sent[0].channel, "notify")

    def test_critical_speaks_aloud_when_the_house_can(self):
        router = self._router(announce_enabled=True)
        sent, _ = router.observe("m", [Alert("m", "critical", "k", "x")])
        self.assertEqual(sent[0].channel, "announce")

    def test_a_second_warning_from_the_same_monitor_is_held(self):
        router = self._router(warn_window_s=3600.0)
        router.observe("m", [Alert("m", "warn", "a", "one")])
        self.clock.advance(60)
        sent, _ = router.observe("m", [Alert("m", "warn", "a", "one"), Alert("m", "warn", "b", "two")])
        self.assertEqual([d.channel for d in sent], ["digest"])
        self.assertIn("already sent a warning", sent[0].reason)

    def test_the_held_warning_says_when_the_next_one_may_go(self):
        router = self._router(warn_window_s=3600.0)
        router.observe("m", [Alert("m", "warn", "a", "one")])
        self.clock.advance(600)
        sent, _ = router.observe("m", [Alert("m", "warn", "b", "two")])
        self.assertIn("next warning allowed in 3000s", sent[0].reason)

    def test_the_rate_limit_is_per_monitor_not_global(self):
        router = self._router()
        router.observe("a", [Alert("a", "warn", "1", "x")])
        sent, _ = router.observe("b", [Alert("b", "warn", "2", "y")])
        self.assertEqual(sent[0].channel, "notify")

    def test_the_window_reopens(self):
        router = self._router(warn_window_s=3600.0)
        router.observe("m", [Alert("m", "warn", "a", "one")])
        self.clock.advance(3601)
        sent, _ = router.observe("m", [Alert("m", "warn", "b", "two")])
        self.assertEqual(sent[0].channel, "notify")

    def test_held_warnings_are_counted_so_the_digest_can_say_so(self):
        router = self._router()
        router.observe("m", [Alert("m", "warn", "a", "1")])
        router.observe("m", [Alert("m", "warn", "a", "1"), Alert("m", "warn", "b", "2")])
        router.observe("m", [Alert("m", "warn", "a", "1"), Alert("m", "warn", "b", "2"),
                             Alert("m", "warn", "c", "3")])
        self.assertEqual(router.suppressed_warnings, {"m": 2})
        self.assertEqual(router.take_suppressed(), {"m": 2})
        self.assertEqual(router.suppressed_warnings, {}, "taking them resets the count")

    def test_quiet_hours_hold_a_warning_for_the_digest(self):
        router = self._router(quiet_hours="22:00-07:00", localtime=_at_hour(23))
        sent, _ = router.observe("m", [Alert("m", "warn", "k", "x")])
        self.assertEqual(sent[0].channel, "digest")
        self.assertIn("quiet hours", sent[0].reason)

    def test_quiet_hours_never_hold_a_critical_alert(self):
        """A quiet-hours rule that can swallow a critical alert is a bug
        with a config key in front of it."""
        router = self._router(quiet_hours="22:00-07:00", localtime=_at_hour(3))
        sent, _ = router.observe("m", [Alert("m", "critical", "k", "the house is on fire")])
        self.assertEqual(sent[0].channel, "notify")

    def test_a_critical_alert_ignores_the_warn_rate_limit_too(self):
        router = self._router()
        router.observe("m", [Alert("m", "warn", "a", "x")])
        sent, _ = router.observe("m", [Alert("m", "warn", "a", "x"), Alert("m", "critical", "b", "y")])
        channels = {d.alert.key: d.channel for d in sent}
        self.assertEqual(channels["b"], "notify")

    def test_every_delivery_explains_itself(self):
        router = self._router()
        sent, _ = router.observe("m", [Alert("m", "info", "k", "x")])
        self.assertTrue(sent[0].reason, "a person asking why they didn't hear deserves an answer")


class MonitorRegistryTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = _Clock()
        self.registry = MonitorRegistry(clock=self.clock)
        self.router = AlertRouter(clock=self.clock, localtime=_at_hour(12))

    def test_a_monitor_satisfies_the_protocol(self):
        self.assertIsInstance(_FakeMonitor("m"), Monitor)

    def test_registering_the_same_name_twice_is_refused(self):
        self.registry.register(_FakeMonitor("m"))
        with self.assertRaises(ValueError):
            self.registry.register(_FakeMonitor("m"))

    async def test_a_monitor_runs_when_due_and_not_before(self):
        monitor = _FakeMonitor("m", interval_s=300.0)
        self.registry.register(monitor)
        await self.registry.run_due(self.router)
        self.assertEqual(monitor.checks, 1)
        self.clock.advance(299)
        await self.registry.run_due(self.router)
        self.assertEqual(monitor.checks, 1, "not due yet")
        self.clock.advance(2)
        await self.registry.run_due(self.router)
        self.assertEqual(monitor.checks, 2)

    async def test_findings_are_routed(self):
        self.registry.register(_FakeMonitor("m", [Alert("m", "warn", "k", "x")]))
        deliveries, resolved = await self.registry.run_due(self.router)
        self.assertEqual([d.channel for d in deliveries], ["notify"])

    async def test_a_monitor_that_raises_does_not_stop_the_others(self):
        self.registry.register(_FakeMonitor("broken", raises=RuntimeError("boom")))
        self.registry.register(_FakeMonitor("fine", [Alert("fine", "warn", "k", "x")]))
        deliveries, _ = await self.registry.run_due(self.router)
        self.assertEqual([d.alert.monitor for d in deliveries], ["fine"])
        self.assertIn("broken", self.registry.failures)
        self.assertIn("boom", self.registry.failures["broken"])

    async def test_a_monitor_that_recovers_stops_being_reported_as_failed(self):
        monitor = _FakeMonitor("m", raises=RuntimeError("boom"))
        self.registry.register(monitor)
        await self.registry.run_due(self.router)
        self.assertIn("m", self.registry.failures)
        monitor.raises = None
        self.clock.advance(3600)
        await self.registry.run_due(self.router)
        self.assertEqual(self.registry.failures, {})

    async def test_unregistering_stops_it_running(self):
        monitor = _FakeMonitor("m")
        self.registry.register(monitor)
        self.registry.unregister("m")
        await self.registry.run_due(self.router)
        self.assertEqual(monitor.checks, 0)
        self.assertEqual(self.registry.names, [])


class DigestTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()

    def _digest(self, hour: int = 8, at: int = 7):
        """Built at `at` o'clock. Default 07:00 -- before the digest
        hour, so the digest is still to come today."""
        return Digest(hour=hour, clock=self.clock, localtime=_at_hour(at))

    def test_it_is_not_due_before_its_hour(self):
        self.assertFalse(self._digest(hour=8, at=7).due())

    def test_it_becomes_due_when_the_hour_arrives(self):
        digest = self._digest(hour=8, at=7)
        self.assertFalse(digest.due())
        self.clock.advance(3600)
        self.assertTrue(digest.due())

    def test_it_is_not_due_twice_in_one_day(self):
        digest = self._digest(hour=8, at=7)
        self.clock.advance(2 * 3600)
        self.assertTrue(digest.due())
        digest.sent()
        self.assertFalse(digest.due())

    def test_it_is_due_again_the_next_day(self):
        digest = self._digest(hour=8, at=7)
        self.clock.advance(2 * 3600)
        self.assertTrue(digest.due())
        digest.sent()
        self.clock.advance(24 * 3600)
        self.assertTrue(digest.due())

    def test_starting_after_the_hour_waits_for_tomorrow(self):
        """Starting Sim at three in the afternoon used to send a "daily
        digest" seconds after boot, containing whatever the first tick
        happened to notice. That is not a summary of a day, and it
        teaches a person that the digest is noise."""
        digest = self._digest(hour=8, at=15)
        self.assertFalse(digest.due())
        self.clock.advance(8 * 3600)   # 23:00 the same day
        self.assertFalse(digest.due())
        self.clock.advance(10 * 3600)  # 09:00 the next day
        self.assertTrue(digest.due())

    def test_nothing_to_say_renders_empty(self):
        """A digest that arrives every day saying nothing trains a
        person to delete it unread -- and then the one that matters
        gets deleted too."""
        self.assertEqual(self._digest().render(), "")

    def test_held_alerts_are_grouped_worst_first(self):
        digest = self._digest()
        digest.hold(Alert("a", "info", "1", "an info thing"))
        digest.hold(Alert("b", "critical", "2", "a critical thing"))
        digest.hold(Alert("c", "warn", "3", "a warn thing"))
        body = digest.render()
        self.assertLess(body.index("CRITICAL"), body.index("WARN"))
        self.assertLess(body.index("WARN"), body.index("INFO"))
        self.assertIn("[b] a critical thing", body)

    def test_a_subsystem_contributes_a_section(self):
        digest = self._digest()
        digest.section("Energy").add("used 30 kWh, £4.10")
        digest.section("Energy").add("solar covered 40%")
        body = digest.render()
        self.assertIn("Energy:", body)
        self.assertIn("- used 30 kWh, £4.10", body)
        self.assertIn("- solar covered 40%", body)

    def test_an_empty_section_is_not_rendered(self):
        digest = self._digest()
        digest.section("Energy")
        self.assertEqual(digest.render(), "")

    def test_held_back_warnings_are_reported(self):
        """A rate limit that silently eats alerts is indistinguishable
        from a monitor that stopped working."""
        digest = self._digest()
        digest.section("x").add("y")
        body = digest.render(suppressed={"certs": 4})
        self.assertIn("certs: 4 further warning(s) held back", body)

    def test_a_broken_monitor_is_named(self):
        digest = self._digest()
        body = digest.render(monitor_failures={"certs": "TimeoutError()"})
        self.assertIn("Monitors that failed to run", body)
        self.assertIn("certs: TimeoutError()", body)

    def test_sending_clears_what_was_in_it(self):
        digest = self._digest()
        digest.hold(Alert("a", "info", "1", "x"))
        digest.section("S").add("line")
        digest.sent()
        self.assertEqual(digest.held, [])
        self.assertEqual(digest.render(), "")


class EndToEndTestCase(unittest.IsolatedAsyncioTestCase):
    """One day of a monitor being wrong, quietly, at night."""

    async def test_a_night_time_warning_arrives_in_the_morning_digest(self):
        clock = _Clock()
        registry = MonitorRegistry(clock=clock)
        router = AlertRouter(clock=clock, quiet_hours="22:00-07:00", localtime=_at_hour(2))
        digest = Digest(hour=8, clock=clock, localtime=_at_hour(2))
        registry.register(_FakeMonitor("sync", [Alert("sync", "warn", "imap:fastmail", "sync failed")]))

        deliveries, _ = await registry.run_due(router)
        self.assertEqual([d.channel for d in deliveries], ["digest"])
        for delivery in deliveries:
            digest.hold(delivery.alert)

        clock.advance(7 * 3600)
        self.assertTrue(digest.due())
        body = digest.render(suppressed=router.take_suppressed())
        self.assertIn("sync failed", body)
        self.assertIn("WARN", body)
