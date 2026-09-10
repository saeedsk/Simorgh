"""The pim connectors and the four tools.

**No test here touches a real account, network or device.** The IMAP
side runs the real `ImapConnector` against a fake IMAP *server*, so the
FETCH-response shredding, the RFC 2047 subject decoding and the
multipart body walk are all genuinely exercised -- a fake that returned
finished objects would skip exactly the code most likely to be wrong.

The behaviour worth pinning hardest is what happens with nothing
configured, because that is the state this ships in and will sit in
until somebody adds an account: it must refuse and name what to set."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config
from simorgh.execution.pim.accounts import build_all, parse_accounts, secret_for
from simorgh.execution.pim.api import Event
from simorgh.execution.pim.connectors import CalDavConnector, FakeCalDav, FakeImap, ImapConnector
from simorgh.execution.pim.connectors.fakes import FakeImapServer
from simorgh.execution.pim.connectors.imap import decode_folder, decode_header
from simorgh.execution.pim.tools import pim_tools

UTC = timezone.utc
WEDNESDAY = datetime(2026, 9, 9, 14, 30)


class _Bus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, message) -> None:
        self.published.append(message)


class _Clock:
    def __init__(self, value: float = 1_757_400_000.0) -> None:
        self.value = value

    def now(self) -> float:
        return self.value


def _ctx(bus=None) -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=Path("."), clock=_Clock(), logger=None, ledger=None, bus=bus)


MESSAGES = [
    {"uid": 1, "folder": "INBOX", "subject": "=?UTF-8?B?UsOpc2VydmF0aW9u?=",
     "from": "Hotel Meridien <bookings@hotel.example>",
     "body": "Your booking is confirmed for 12 March.", "flags": [],
     "date": datetime(2026, 9, 9, 10, 0, tzinfo=UTC)},
    {"uid": 2, "folder": "INBOX", "subject": "Invoice 4471", "from": "billing@utility.example",
     "body": "Amount due is 210 pounds.", "flags": ["\\Seen"], "attachment": "invoice.pdf",
     "date": datetime(2026, 9, 8, 9, 0, tzinfo=UTC)},
    {"uid": 3, "folder": "Archive", "subject": "Old thing", "from": "someone@x.example",
     "body": "archived", "flags": ["\\Seen"], "date": datetime(2026, 1, 1, tzinfo=UTC)},
]

EVENTS = [
    Event("e1", "Dentist", datetime(2026, 9, 9, 9, 0), datetime(2026, 9, 9, 9, 30),
          location="High Street", calendar="home"),
    Event("e2", "Plumber", datetime(2026, 9, 10, 15, 0), datetime(2026, 9, 10, 16, 0),
          calendar="home"),
    Event("e3", "Sprint review", datetime(2026, 9, 11, 11, 0), datetime(2026, 9, 11, 12, 0),
          calendar="work"),
]


class ImapConnectorTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.connector = FakeImap(messages=MESSAGES)

    async def test_probe_signs_in_and_counts_folders(self):
        status = await self.connector.probe()
        self.assertTrue(status.ok, status.detail)
        self.assertIn("folder", status.detail)

    async def test_probe_without_a_password_names_the_vault_command(self):
        connector = ImapConnector(name="home", host="imap.x", username="me", password="")
        status = await connector.probe()
        self.assertFalse(status.ok)
        self.assertIn("vault add imap:home password", status.detail)
        self.assertIn("password", status.missing)

    async def test_probe_without_a_host_says_so_without_opening_a_socket(self):
        status = await ImapConnector(name="home", host="", username="me", password="p").probe()
        self.assertFalse(status.ok)
        self.assertIn("host", status.missing)

    async def test_a_refused_login_never_echoes_the_password(self):
        """`imaplib` puts the whole LOGIN command -- password included --
        in its own exception strings."""
        server = FakeImapServer(messages=[], password="the-real-password")
        connector = ImapConnector(name="home", host="imap.x", username="me",
                                  password="WRONGPASSWORD", client_factory=lambda: server)
        status = await connector.probe()
        self.assertFalse(status.ok)
        self.assertNotIn("WRONGPASSWORD", status.detail)
        self.assertIn("app-specific password", status.detail)

    async def test_folders_are_listed(self):
        self.assertEqual(await self.connector.folders(), ["INBOX", "Archive"])

    async def test_search_decodes_an_encoded_subject(self):
        messages = await self.connector.search("")
        self.assertIn("Réservation", [m.subject for m in messages])

    async def test_search_returns_no_bodies(self):
        """Headers are personal, bodies are sensitive. If a search
        pulled every body back, the cheap operation would be the
        exposing one and nobody would notice."""
        for message in await self.connector.search(""):
            self.assertEqual(message.body, "")

    async def test_search_reports_unread_and_attachments(self):
        by_uid = {m.uid: m for m in await self.connector.search("")}
        self.assertTrue(by_uid["1"].unread)
        self.assertFalse(by_uid["2"].unread)
        self.assertTrue(by_uid["2"].has_attachments)

    async def test_search_matches_text(self):
        messages = await self.connector.search("invoice")
        self.assertEqual([m.subject for m in messages], ["Invoice 4471"])

    async def test_search_can_ask_for_unread_only(self):
        messages = await self.connector.search("", unread_only=True)
        self.assertEqual([m.uid for m in messages], ["1"])

    async def test_search_is_bounded_by_its_limit(self):
        self.assertEqual(len(await self.connector.search("", limit=1)), 1)

    async def test_a_folder_that_does_not_exist_is_an_error_not_an_empty_result(self):
        with self.assertRaises(Exception):
            await self.connector.search("", folder="Nope")

    async def test_fetch_body_returns_the_text(self):
        message = await self.connector.fetch_body("1")
        self.assertIn("booking is confirmed", message.body)
        self.assertEqual(message.subject, "Réservation")

    async def test_an_html_only_message_is_converted_rather_than_dropped(self):
        connector = FakeImap(messages=[{"uid": 9, "folder": "INBOX", "subject": "Newsletter",
                                        "from": "n@x.example", "body": "",
                                        "html": "<html><body><p>Sale on now</p></body></html>"}])
        message = await connector.fetch_body("9")
        self.assertIn("Sale on now", message.body)

    async def test_fetching_something_that_is_not_there_answers_none(self):
        self.assertIsNone(await self.connector.fetch_body("999"))

    async def test_close_is_idempotent(self):
        await self.connector.probe()
        await self.connector.close()
        await self.connector.close()

    async def test_the_budget_refuses_rather_than_hammering_the_server(self):
        from simorgh.contracts.connector import Budget, BudgetExhausted

        connector = FakeImap(messages=MESSAGES)
        connector._budget = Budget("imap:test", limit=1, window_s=3600.0)
        await connector.search("")
        with self.assertRaises(BudgetExhausted):
            await connector.search("")


class FolderNameTestCase(unittest.TestCase):
    def test_modified_utf7_folder_names_are_decoded(self):
        self.assertEqual(decode_folder("INBOX/&AMk-coles"), "INBOX/Écoles")

    def test_a_plain_name_is_unchanged(self):
        self.assertEqual(decode_folder("INBOX/Receipts"), "INBOX/Receipts")

    def test_an_encoded_header_is_decoded(self):
        self.assertEqual(decode_header("=?UTF-8?B?SGVsbG8gd29ybGQ=?="), "Hello world")

    def test_an_unencoded_header_survives(self):
        self.assertEqual(decode_header("Plain subject"), "Plain subject")


class CalDavConnectorTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_construction_never_raises_on_a_bad_url(self):
        CalDavConnector(name="x", url="not a url")   # no raise

    async def test_probe_without_credentials_names_the_vault_command(self):
        status = await CalDavConnector(name="home", url="https://caldav.x/").probe()
        self.assertFalse(status.ok)
        self.assertIn("vault add caldav:home password", status.detail)

    async def test_probe_rejects_a_non_http_url_without_a_socket(self):
        status = await CalDavConnector(name="home", url="ftp://x/", username="u",
                                        password="p").probe()
        self.assertFalse(status.ok)
        self.assertIn("not an http(s) URL", status.detail)

    async def test_a_401_says_to_use_an_app_password(self):
        import urllib.error

        def _opener(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

        status = await CalDavConnector(name="home", url="https://caldav.x/", username="u",
                                        password="p", opener=_opener).probe()
        self.assertFalse(status.ok)
        self.assertIn("app-specific password", status.detail)

    async def test_an_unreachable_host_is_a_status_not_an_exception(self):
        import urllib.error

        def _opener(request, timeout=None):
            raise urllib.error.URLError("nodename nor servname provided")

        status = await CalDavConnector(name="home", url="https://caldav.x/", username="u",
                                        password="p", opener=_opener).probe()
        self.assertFalse(status.ok)
        self.assertIn("could not reach", status.detail)

    async def test_a_credential_never_appears_in_a_probe_result(self):
        import urllib.error

        def _opener(request, timeout=None):
            raise urllib.error.URLError("boom")

        status = await CalDavConnector(name="home", url="https://caldav.x/", username="u",
                                        password="SUPERSECRET", opener=_opener).probe()
        self.assertNotIn("SUPERSECRET", status.detail)

    async def test_events_are_parsed_from_a_calendar_query_response(self):
        ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:1\r\nSUMMARY:Dentist\r\n"
               "DTSTART:20260909T090000Z\r\nDTEND:20260909T093000Z\r\nEND:VEVENT\r\n"
               "END:VCALENDAR")
        multistatus = (
            '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:caldav"><d:response>'
            "<d:href>/cal/home/</d:href><d:propstat><d:prop>"
            f"<c:calendar-data>{ics}</c:calendar-data>"
            "</d:prop></d:propstat></d:response></d:multistatus>")

        class _Response:
            status = 207

            def __init__(self, body): self._body = body.encode()
            def read(self): return self._body
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        def _opener(request, timeout=None):
            return _Response(multistatus)

        connector = CalDavConnector(name="home", url="https://caldav.x/cal/home",
                                     username="u", password="p", opener=_opener)
        events = await connector.events(datetime(2026, 9, 9, tzinfo=UTC),
                                        datetime(2026, 9, 10, tzinfo=UTC))
        self.assertEqual([e.summary for e in events], ["Dentist"])


class AccountsTestCase(unittest.TestCase):
    ROWS = [
        {"name": "fastmail", "kind": "imap", "url": "imap.fastmail.com", "username": "me@x.com"},
        {"name": "home", "kind": "caldav", "url": "https://caldav.x/", "username": "me"},
        {"name": "broken", "kind": "carrier-pigeon"},
    ]

    def test_rows_become_accounts_and_nonsense_is_dropped(self):
        accounts = parse_accounts(self.ROWS)
        self.assertEqual([a.name for a in accounts], ["fastmail", "home"])

    def test_a_credential_id_defaults_to_kind_and_name(self):
        self.assertEqual(parse_accounts(self.ROWS)[0].cred_id, "imap:fastmail")

    def test_the_vault_is_preferred_over_the_environment(self):
        class _Secrets:
            def get(self, name):
                return "from-vault" if name == "vault:imap:fastmail:password" else None

        account = parse_accounts(self.ROWS)[0]
        self.assertEqual(secret_for(account, secrets=_Secrets(),
                                     env={"PIM_FASTMAIL_PASSWORD": "from-env"}), "from-vault")

    def test_the_environment_is_the_fallback_for_trying_it_out(self):
        account = parse_accounts(self.ROWS)[0]
        self.assertEqual(secret_for(account, secrets=None,
                                     env={"PIM_FASTMAIL_PASSWORD": "from-env"}), "from-env")

    def test_no_credential_anywhere_is_an_empty_string_not_a_raise(self):
        self.assertEqual(secret_for(parse_accounts(self.ROWS)[0], secrets=None, env={}), "")

    def test_a_port_in_the_url_is_honoured(self):
        built = build_all([{"name": "x", "kind": "imap", "url": "imap.x.com:1143"}], env={})
        self.assertEqual(built["x"].port, 1143)

    def test_building_never_raises_on_a_broken_row(self):
        self.assertEqual(sorted(build_all(self.ROWS, env={})), ["fastmail", "home"])


class _ToolCase(unittest.IsolatedAsyncioTestCase):
    def _tools(self, *, connectors=None, **overrides) -> dict:
        config = Config(**overrides)
        return {tool.name: tool for tool in pim_tools(
            config, connectors=connectors, clock=lambda: WEDNESDAY.timestamp())}


class NothingConfiguredTestCase(_ToolCase):
    """The state this ships in. A tool that says "no results" to
    somebody who never configured an account has told them nothing."""

    async def test_cal_list_names_the_toml_and_the_vault_command(self):
        result = await self._tools()["cal_list"].run({}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("execution.pim_accounts", result.error)
        self.assertIn("vault add caldav:", result.error)

    async def test_mail_search_names_the_toml_and_the_vault_command(self):
        result = await self._tools()["mail_search"].run({}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("kind = \"imap\"", result.error)

    async def test_mail_read_refuses_too(self):
        result = await self._tools()["mail_read"].run({"message": "1"}, ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_remind_still_works_because_it_needs_no_account(self):
        bus = _Bus()
        result = await self._tools()["remind"].run(
            {"when": "20m", "text": "take the bins out"}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)


class CalListTestCase(_ToolCase):
    def _tools(self, **overrides):
        return super()._tools(connectors={"home": FakeCalDav("home", EVENTS)}, **overrides)

    async def test_today_shows_todays_events_only(self):
        result = await self._tools()["cal_list"].run({"range": "today"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("Dentist", result.output)
        self.assertNotIn("Plumber", result.output)

    async def test_this_week_shows_all_of_them(self):
        result = await self._tools()["cal_list"].run({"range": "this week"}, ctx=_ctx())
        self.assertEqual(result.metadata["events"], 3)

    async def test_an_empty_day_says_so_rather_than_erroring(self):
        result = await self._tools()["cal_list"].run({"range": "2026-12-25"}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("nothing on the calendar", result.output)

    async def test_results_are_rows_so_query_data_can_aggregate_them(self):
        result = await self._tools()["cal_list"].run({"range": "this week"}, ctx=_ctx())
        self.assertEqual(len(result.metadata["rows"]), 3)
        self.assertIn("summary", result.metadata["rows"][0])

    async def test_a_calendar_filter_narrows_it(self):
        result = await self._tools()["cal_list"].run(
            {"range": "this week", "calendar": "work"}, ctx=_ctx())
        self.assertEqual([r["summary"] for r in result.metadata["rows"]], ["Sprint review"])

    async def test_an_unreadable_range_is_refused_with_what_would_work(self):
        result = await self._tools()["cal_list"].run({"range": "whenever"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("this week", result.error)

    async def test_one_unreachable_account_does_not_lose_the_others(self):
        class _Broken(FakeCalDav):
            async def events(self, start, end):
                raise OSError("network is down")

        tools = {tool.name: tool for tool in pim_tools(
            Config(), connectors={"home": FakeCalDav("home", EVENTS), "work": _Broken("work")},
            clock=lambda: WEDNESDAY.timestamp())}
        result = await tools["cal_list"].run({"range": "this week"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("Dentist", result.output)
        self.assertIn("could not read", result.output)


class MailToolTestCase(_ToolCase):
    """Mail mechanics. Bodies are allowed through here on purpose --
    the withholding rule has its own case below, and mixing the two
    would leave the mechanics untested behind the gate."""

    def _tools(self, **overrides):
        overrides.setdefault("pim_cloud_llm_may_see", ("public", "personal", "sensitive"))
        return super()._tools(connectors={"fastmail": FakeImap("fastmail", MESSAGES)}, **overrides)

    async def test_search_lists_subjects_and_senders(self):
        result = await self._tools()["mail_search"].run({}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("Invoice 4471", result.output)
        self.assertIn("Réservation", result.output)

    async def test_search_prints_a_reference_mail_read_accepts(self):
        result = await self._tools()["mail_search"].run({"query": "invoice"}, ctx=_ctx())
        self.assertIn("[fastmail:INBOX:2]", result.output)
        opened = await self._tools()["mail_read"].run(
            {"message": "fastmail:INBOX:2"}, ctx=_ctx())
        self.assertTrue(opened.ok, opened.error)
        self.assertIn("210 pounds", opened.output)

    async def test_search_never_returns_a_body(self):
        result = await self._tools()["mail_search"].run({}, ctx=_ctx())
        self.assertNotIn("Amount due", result.output)
        self.assertEqual(result.metadata["privacy"], "personal")

    async def test_rows_carry_the_headers_and_not_the_body(self):
        result = await self._tools()["mail_search"].run({}, ctx=_ctx())
        for row in result.metadata["rows"]:
            self.assertNotIn("body", row)

    async def test_an_unknown_account_lists_the_real_ones(self):
        result = await self._tools()["mail_search"].run({"account": "gmail"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("fastmail", result.error)

    async def test_reading_a_message_that_is_not_there_says_so(self):
        result = await self._tools()["mail_read"].run(
            {"message": "fastmail:INBOX:999"}, ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_an_empty_reference_is_refused(self):
        result = await self._tools()["mail_read"].run({"message": " "}, ctx=_ctx())
        self.assertFalse(result.ok)

    async def test_a_bare_uid_defaults_to_the_inbox_of_the_one_account(self):
        result = await self._tools()["mail_read"].run({"message": "1"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("booking is confirmed", result.output)


class MailPrivacyTestCase(_ToolCase):
    """Bodies are `sensitive`. The gate is in the tool rather than in
    the caller because the caller is a model, and by the time it could
    decide, the text is already in its context."""

    def _tools(self, **overrides):
        return super()._tools(connectors={"fastmail": FakeImap("fastmail", MESSAGES)}, **overrides)

    async def test_a_body_is_withheld_by_default(self):
        result = await self._tools()["mail_read"].run({"message": "1"}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertTrue(result.metadata["withheld"])
        self.assertNotIn("booking is confirmed", result.output)
        self.assertIn("pim_cloud_llm_may_see", result.output)

    async def test_naming_sensitive_in_config_lets_it_through(self):
        tools = self._tools(pim_cloud_llm_may_see=("public", "personal", "sensitive"))
        result = await tools["mail_read"].run({"message": "1"}, ctx=_ctx())
        self.assertFalse(result.metadata["withheld"])
        self.assertIn("booking is confirmed", result.output)

    async def test_search_still_works_when_bodies_are_withheld(self):
        result = await self._tools()["mail_search"].run({}, ctx=_ctx())
        self.assertTrue(result.ok)
        self.assertIn("Invoice 4471", result.output)


class RemindTestCase(_ToolCase):
    async def test_a_reminder_becomes_a_kernel_schedule(self):
        """The Kernel has had a complete scheduler since the beginning.
        This is the door a person actually reaches for."""
        bus = _Bus()
        result = await self._tools()["remind"].run(
            {"when": "20m", "text": "take the bins out"}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(bus.published), 1)
        message = bus.published[0]
        self.assertEqual(message.type, topics.SYSTEM_SCHEDULE_ADD)
        self.assertEqual(message.payload["label"], "take the bins out")
        self.assertAlmostEqual(message.payload["at"], _Clock().now() + 1200, delta=2)
        self.assertIsNone(message.payload["every_seconds"])

    async def test_a_recurring_reminder_sets_every_seconds_instead(self):
        bus = _Bus()
        await self._tools()["remind"].run(
            {"when": "1d", "text": "water the plants", "every": True}, ctx=_ctx(bus))
        payload = bus.published[0].payload
        self.assertIsNone(payload["at"])
        self.assertEqual(payload["every_seconds"], 86400)

    async def test_a_natural_phrase_is_resolved_and_reported_back(self):
        bus = _Bus()
        result = await self._tools()["remind"].run(
            {"when": "tomorrow 8am", "text": "call the plumber"}, ctx=_ctx(bus))
        self.assertIn("Thu 10 Sep at 08:00", result.output)

    async def test_an_ambiguous_time_is_refused_rather_than_guessed_at(self):
        """A reminder that fires on the wrong day is worse than one that
        was never set."""
        bus = _Bus()
        result = await self._tools()["remind"].run(
            {"when": "at 3", "text": "x"}, ctx=_ctx(bus))
        self.assertFalse(result.ok)
        self.assertIn("3am", result.error)
        self.assertEqual(bus.published, [], "a refusal must not have scheduled anything")

    async def test_a_time_in_the_past_is_refused(self):
        result = await self._tools()["remind"].run(
            {"when": "2020-01-01 09:00", "text": "x"}, ctx=_ctx(_Bus()))
        self.assertFalse(result.ok)
        self.assertIn("in the past", result.error)

    async def test_an_absurdly_distant_reminder_is_refused(self):
        result = await self._tools()["remind"].run(
            {"when": "2099-01-01 09:00", "text": "x"}, ctx=_ctx(_Bus()))
        self.assertFalse(result.ok)
        self.assertIn("days away", result.error)

    async def test_an_empty_reminder_is_refused(self):
        result = await self._tools()["remind"].run({"when": "20m", "text": "  "}, ctx=_ctx(_Bus()))
        self.assertFalse(result.ok)

    async def test_without_a_bus_it_says_so_rather_than_silently_doing_nothing(self):
        result = await self._tools()["remind"].run(
            {"when": "20m", "text": "x"}, ctx=_ctx(None))
        self.assertFalse(result.ok)
        self.assertIn("bus", result.error)
