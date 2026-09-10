"""`domains`, `config` and `alerts`: the three commands that answer
"what have I got, is it working, and what has it noticed".

Each reads a Ledger stream some other subsystem already writes, which
is why they are small. The behaviour worth pinning is the wording: a
domain nobody has configured is not a fault and must not read like one,
and a config value that matches its default is not the same fact as one
a person set to that value on purpose."""

from __future__ import annotations

import unittest

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts.envelope import Event
from simorgh.interface import dispatch as dispatch_module
from simorgh.interface.dispatch import dispatch
from simorgh.interface.parser import Command
from simorgh.interface.vitals import VitalsCache
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock


class _CommandTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(backend, source="interface", ledger=self.ledger,
                               clock=self.clock.now)
        await self.bus.start()
        self.vitals = VitalsCache()

    async def asyncTearDown(self):
        await self.bus.stop()
        await self.ledger.stop()

    async def _append(self, stream: str, type_: str, payload: dict) -> None:
        await self.ledger.append(stream, Event(
            stream=stream, type=type_, ts=self.clock.now(), trace_id="", causation_id=None,
            payload=payload))

    async def _run(self, name: str, args: str = "") -> str:
        outcome = await dispatch(
            Command(name=name, args=args, raw=f"{name} {args}"),
            bus=self.bus, clock=self.clock, session_id="s1", vitals=self.vitals,
            ledger=self.ledger)
        return outcome.text

    async def _probe(self, name: str, ok: bool, detail: str) -> None:
        await self._append(dispatch_module.CAPABILITIES_STREAM, "probed", {
            "name": f"connector:{name}", "ok": ok, "detail": detail, "cost": "cheap",
            "tools": []})


class DomainsTestCase(_CommandTestCase):
    async def test_before_any_probe_it_says_so(self):
        self.assertIn("no domain probes recorded yet", await self._run("domains"))

    async def test_a_working_domain_is_marked_ok(self):
        await self._probe("security", True, "3 open finding(s)")
        answer = await self._run("domains")
        self.assertIn("[ok]", answer)
        self.assertIn("3 open finding(s)", answer)

    async def test_an_unconfigured_domain_does_not_read_as_broken(self):
        """"Nothing set up yet" and "set up and failing" are different
        facts, and a person needs them kept apart."""
        await self._probe("home", False, "set HOME_ASSISTANT_URL and HOME_ASSISTANT_TOKEN")
        answer = await self._run("domains")
        self.assertIn("nothing is set up yet, not that something is broken", answer)
        self.assertIn("HOME_ASSISTANT_URL", answer)

    async def test_it_counts_how_many_work(self):
        await self._probe("security", True, "ready")
        await self._probe("home", False, "not configured")
        self.assertIn("1 of 6 domains working", await self._run("domains"))

    async def test_mail_accounts_are_listed_one_by_one(self):
        """One mailbox failing while another works is exactly what a
        single `pim` row would hide."""
        await self._probe("imap:fastmail", True, "signed in, 12 folder(s)")
        await self._probe("imap:work", False, "the server refused these credentials")
        answer = await self._run("domains")
        self.assertIn("imap:fastmail", answer)
        self.assertIn("imap:work", answer)
        self.assertIn("refused these credentials", answer)

    async def test_with_no_mail_account_it_says_how_to_add_one(self):
        await self._probe("security", True, "ready")
        answer = await self._run("domains")
        self.assertIn("execution.pim_accounts", answer)
        self.assertIn("simorgh vault add", answer)

    async def test_the_newest_probe_wins(self):
        await self._probe("home", False, "not configured")
        self.clock.advance(60)
        await self._probe("home", True, "home assistant is running")
        answer = await self._run("domains")
        self.assertIn("home assistant is running", answer)
        self.assertNotIn("not configured", answer)


class AlertsTestCase(_CommandTestCase):
    async def _raised(self, monitor: str, key: str, severity: str, message: str,
                      *, channel: str = "notify", reason: str = "", reopened: float = 0.0) -> None:
        await self._append(dispatch_module.ALERTS_STREAM, "raised", {
            "monitor": monitor, "key": key, "severity": severity, "message": message,
            "channel": channel, "reason": reason, "reopened": reopened, "entity": ""})

    async def test_with_nothing_raised_it_says_so_honestly(self):
        answer = await self._run("alerts")
        self.assertIn("nothing has been raised", answer)
        self.assertIn("honest answer rather than a clean bill of health", answer)

    async def test_an_open_alert_is_shown_worst_first(self):
        await self._raised("certs", "a", "warn", "expires in 20 days")
        await self._raised("boiler", "b", "critical", "the boiler is off")
        answer = await self._run("alerts")
        self.assertLess(answer.index("critical"), answer.index("warn"))

    async def test_a_cleared_alert_stops_being_open(self):
        await self._raised("certs", "a", "warn", "expires in 20 days")
        await self._append(dispatch_module.ALERTS_STREAM, "cleared",
                           {"monitor": "certs", "key": "a", "message": "expires in 20 days"})
        answer = await self._run("alerts")
        self.assertIn("nothing open", answer)
        self.assertIn("raised and resolved", answer)

    async def test_a_held_alert_says_where_it_went_and_why(self):
        """"Why didn't I hear about this" has an answer, and this is
        where a person can read it."""
        await self._raised("sync", "s", "warn", "sync failed", channel="digest",
                           reason="quiet hours (22:00-07:00): held for the digest")
        answer = await self._run("alerts")
        self.assertIn("waiting for the daily digest", answer)
        self.assertIn("quiet hours", answer)

    async def test_a_regressed_alert_is_marked(self):
        await self._raised("certs", "a", "warn", "expired", reopened=2.0)
        self.assertIn("REGRESSED", await self._run("alerts"))

    async def test_the_history_is_available(self):
        await self._raised("certs", "a", "warn", "expires in 20 days")
        await self._append(dispatch_module.ALERTS_STREAM, "cleared",
                           {"monitor": "certs", "key": "a", "message": "x"})
        answer = await self._run("alerts", "all")
        self.assertIn("raised", answer)
        self.assertIn("cleared", answer)


class ConfigTestCase(_CommandTestCase):
    async def _record(self, **overrides) -> None:
        payload = {
            "sections": {
                "execution": {
                    "shell": {"value": False, "source": "default"},
                    "notify_provider": {"value": "ntfy", "source": "file"},
                },
                "guardian": {"auto_approve": {"value": True, "source": "file"}},
                "interface": {"http_port": {"value": 8765, "source": "default"}},
            },
            "dead_sections": [], "dead_fields": [],
            "path": "/repo/simorgh.toml", "hash": "abc123",
        }
        payload.update(overrides)
        await self._append(dispatch_module.CONFIG_STREAM, "effective", payload)

    async def test_before_a_boot_records_anything_it_says_so(self):
        self.assertIn("no config has been recorded yet", await self._run("config"))

    async def test_it_names_the_file_the_settings_came_from(self):
        await self._record()
        self.assertIn("/repo/simorgh.toml", await self._run("config"))

    async def test_the_summary_shows_only_what_the_file_sets(self):
        await self._record()
        answer = await self._run("config")
        self.assertIn("notify_provider", answer)
        self.assertNotIn("shell", answer)

    async def test_a_section_at_its_defaults_says_so_rather_than_listing_nothing(self):
        await self._record()
        self.assertIn("all 1 setting(s) at their defaults", await self._run("config"))

    async def test_naming_a_section_shows_every_setting_in_it(self):
        await self._record()
        answer = await self._run("config", "execution")
        self.assertIn("shell", answer)
        self.assertIn("notify_provider", answer)

    async def test_a_setting_the_file_sets_is_marked(self):
        """"It is the default" and "you set it to the same thing as the
        default" look identical in the value alone, and only one of them
        means a config line is doing nothing."""
        await self._record()
        answer = await self._run("config", "execution")
        marked = [line for line in answer.splitlines() if "notify_provider" in line]
        self.assertTrue(marked[0].strip().startswith("*"), marked)
        unmarked = [line for line in answer.splitlines() if " shell " in line]
        self.assertFalse(unmarked[0].strip().startswith("*"), unmarked)

    async def test_settings_nothing_reads_are_named(self):
        await self._record(dead_fields=["persona.min_confidence_to_use"],
                           dead_sections=["typoed"])
        answer = await self._run("config")
        self.assertIn("nothing reads", answer)
        self.assertIn("persona.min_confidence_to_use", answer)
        self.assertIn("typoed", answer)

    async def test_a_section_that_would_not_parse_is_still_listed(self):
        await self._record(sections={"execution": {"error": "this section could not be parsed"}})
        self.assertIn("could not be parsed", await self._run("config"))

    async def test_the_newest_record_wins(self):
        await self._record(path="/old/simorgh.toml")
        self.clock.advance(60)
        await self._record(path="/new/simorgh.toml")
        self.assertIn("/new/simorgh.toml", await self._run("config"))
