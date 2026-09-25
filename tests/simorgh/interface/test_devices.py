"""One token per device, with capabilities, and pairing by barcode.

Stage 12 item 2. Before this, `SIM_API_TOKEN` was one shared bearer for
every caller of a system holding the cameras, the door hardware, the
family's mail and a model budget -- with `http_host` at `0.0.0.0`. A phone
left in a taxi was full control of the house with no way to revoke it
short of rotating the token and re-pairing everything that had it.

The properties here are the point, not the plumbing: a stored token is a
hash, a capability is granted rather than inherited, and a pairing code is
worth nothing a minute later.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.interface.devices import (
    CAPABILITIES,
    DEFAULT_CAPABILITIES,
    MAX_PAIR_ATTEMPTS,
    PAIRING_TTL_S,
    DeviceBook,
    barcode,
    normalise,
    pairing_url,
)


class _Clock:
    def __init__(self, t: float = 1_790_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class DeviceBookCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "devices.json"
        self.clock = _Clock()
        self.book = DeviceBook(self.path)
        self.book.clock = self.clock

    def _pair(self, **kw):
        pending = self.book.begin_pairing(**kw)
        got = self.book.redeem(pending.code)
        self.assertNotIsInstance(got, str, got)
        return got


class TheStoredToken(DeviceBookCase):
    def test_the_token_is_never_written_to_disk(self):
        """A leaked devices.json should be names and dates, not keys."""
        device, token = self._pair(name="iPhone")
        on_disk = self.path.read_text(encoding="utf-8")
        self.assertNotIn(token, on_disk)
        self.assertIn(device.id, on_disk)
        row = json.loads(on_disk)["devices"][0]
        self.assertEqual(len(row["token_sha256"]), 64)
        self.assertNotIn("token", {k for k in row if k != "token_sha256"})

    def test_the_right_token_resolves_and_a_wrong_one_does_not(self):
        device, token = self._pair(name="iPhone")
        self.assertEqual(self.book.resolve(token).id, device.id)
        self.assertIsNone(self.book.resolve(token + "x"))
        self.assertIsNone(self.book.resolve(""))

    def test_a_token_survives_a_restart(self):
        _, token = self._pair(name="iPhone")
        reopened = DeviceBook(self.path)
        self.assertIsNotNone(reopened.resolve(token))

    def test_resolving_records_when_it_was_last_seen(self):
        _, token = self._pair(name="iPhone")
        self.clock.t += 60
        self.assertEqual(self.book.resolve(token).last_seen, self.clock.t)


class Capabilities(DeviceBookCase):
    def test_a_scan_alone_grants_read_and_chat_only(self):
        """`control` and `approve` are grants, not defaults: authorising an
        irreversible action should be a sentence somebody said."""
        device, _ = self._pair(name="iPhone")
        self.assertEqual(device.capabilities, tuple(DEFAULT_CAPABILITIES))
        self.assertTrue(device.may("read"))
        self.assertTrue(device.may("chat"))
        self.assertFalse(device.may("control"))
        self.assertFalse(device.may("approve"))

    def test_approve_is_granted_when_it_is_asked_for(self):
        device, _ = self._pair(name="iPhone", capabilities=["read", "approve"])
        self.assertTrue(device.may("approve"))
        self.assertFalse(device.may("chat"))

    def test_an_unknown_capability_grants_nothing_and_is_not_an_error(self):
        """A newer client asking for something this Sim has never heard of
        should get what it can have; an unknown name grants nothing anyway."""
        self.assertEqual(normalise(["read", "telepathy"]), ("read",))
        self.assertEqual(normalise(["TELEPATHY"]), ())

    def test_capabilities_come_back_in_a_stable_order(self):
        self.assertEqual(normalise(["approve", "read", "chat"]), ("read", "chat", "approve"))
        self.assertEqual(normalise(CAPABILITIES), tuple(CAPABILITIES))


class ThePairingCode(DeviceBookCase):
    def test_a_code_works_once(self):
        pending = self.book.begin_pairing(name="iPhone")
        self.assertNotIsInstance(self.book.redeem(pending.code), str)
        self.assertIsInstance(self.book.redeem(pending.code), str)

    def test_a_code_expires(self):
        """A photograph of the terminal is worth nothing a minute later."""
        pending = self.book.begin_pairing(name="iPhone")
        self.clock.t += PAIRING_TTL_S + 1
        self.assertIsNone(self.book.pending())
        self.assertIsInstance(self.book.redeem(pending.code), str)

    def test_pairing_twice_kills_the_first_code(self):
        first = self.book.begin_pairing(name="one")
        self.book.begin_pairing(name="two")
        self.assertIsInstance(self.book.redeem(first.code), str)

    def test_a_wrong_code_says_so_and_is_counted(self):
        pending = self.book.begin_pairing(name="iPhone")
        for _ in range(MAX_PAIR_ATTEMPTS):
            self.assertIn("not the code", self.book.redeem("wrong"))
        # Past the cap the code is dead even if the right one turns up.
        self.assertIn("too many attempts", self.book.redeem(pending.code))
        self.assertIsNone(self.book.pending())

    def test_the_code_rides_in_the_fragment(self):
        """Out of server logs, proxy logs and Referer headers."""
        url = pairing_url("https://sim.example/", "ABC123")
        self.assertEqual(url, "https://sim.example/pair#ABC123")
        self.assertNotIn("?", url)

    def test_redeeming_with_nothing_open_explains_what_to_do(self):
        self.assertIn("run `pair`", self.book.redeem("anything"))


class Revoking(DeviceBookCase):
    def test_a_revoked_token_stops_working_at_once(self):
        device, token = self._pair(name="iPhone")
        self.assertIsNotNone(self.book.resolve(token))
        self.assertIsNotNone(self.book.revoke(device.id))
        self.assertIsNone(self.book.resolve(token))

    def test_revoking_one_device_leaves_the_others_alone(self):
        _, keep = self._pair(name="ipad")
        gone_device, gone = self._pair(name="old phone")
        self.book.revoke(gone_device.id)
        self.assertIsNone(self.book.resolve(gone))
        self.assertIsNotNone(self.book.resolve(keep))

    def test_it_revokes_by_name_too(self):
        _, token = self._pair(name="Saeed iPhone")
        self.assertIsNotNone(self.book.revoke("saeed iphone"))
        self.assertIsNone(self.book.resolve(token))

    def test_a_revoked_device_is_kept_as_a_record(self):
        """What was paired and when is worth more than a tidy file, and a
        reused name would otherwise be indistinguishable."""
        device, _ = self._pair(name="iPhone")
        self.book.revoke(device.id)
        self.assertEqual(self.book.devices(), [])
        kept = self.book.devices(include_revoked=True)
        self.assertEqual([d.id for d in kept], [device.id])
        self.assertTrue(kept[0].revoked)

    def test_revoking_something_that_is_not_there_says_nothing_happened(self):
        self.assertIsNone(self.book.revoke("no such phone"))


class ABrokenBook(unittest.TestCase):
    def test_a_missing_or_corrupt_file_admits_nobody_and_does_not_raise(self):
        """The connectors' first rule: one bad file must not stop Sim
        booting -- and an empty book admits nobody, which is the safe end."""
        with tempfile.TemporaryDirectory() as d:
            missing = DeviceBook(Path(d) / "nope.json")
            self.assertEqual(missing.devices(), [])
            self.assertIsNone(missing.resolve("anything"))

            bad = Path(d) / "bad.json"
            bad.write_text("{not json at all", encoding="utf-8")
            self.assertEqual(DeviceBook(bad).devices(), [])

            partial = Path(d) / "partial.json"
            partial.write_text(json.dumps({"devices": [{"name": "no id or hash"}, "a string"]}), encoding="utf-8")
            self.assertEqual(DeviceBook(partial).devices(), [])


class TheBarcode(unittest.TestCase):
    def test_it_draws_something_scannable_or_says_it_cannot(self):
        """None is the caller's cue to print the URL instead. Pairing must
        never be impossible because a drawing tool is missing."""
        drawn = barcode("https://sim.example/pair#ABC123")
        if drawn is None:
            self.skipTest("no qrencode binary and no qrcode package here")
        self.assertGreater(len(drawn.splitlines()), 10)
        self.assertTrue(any(ch in drawn for ch in "█▀▄#"), "that does not look like a QR")


class TheHttpAuthUsesTheBook(unittest.TestCase):
    """The wiring, not just the store: a paired token must actually open
    the door, a revoked one must actually close it, and the legacy shared
    token must keep working -- the TV page and every existing script hold
    it, and breaking them to add devices would be the wrong trade.

    A store nobody calls is the shape of bug this repository keeps finding,
    so this asserts through `HttpServer` rather than around it.
    """

    def _server(self, *, token: str = "shared-secret", devices=None):
        from simorgh.interface.httpapi import HttpApi

        return HttpApi(bus=None, ledger=None, token=token, devices=devices)

    def _bearer(self, token: str) -> dict:
        return {"authorization": f"Bearer {token}"}

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.book = DeviceBook(Path(self._tmp.name) / "devices.json")

    def _pair(self, **kw) -> str:
        pending = self.book.begin_pairing(**kw)
        _, token = self.book.redeem(pending.code)
        return token

    def test_a_paired_device_is_authorised(self):
        token = self._pair(name="iPhone")
        server = self._server(devices=self.book)
        self.assertTrue(server._authorized(self._bearer(token)))          # noqa: SLF001
        self.assertEqual(server.caller(self._bearer(token)).name, "iPhone")

    def test_a_revoked_device_is_refused_even_with_the_shared_token_set(self):
        token = self._pair(name="old phone")
        server = self._server(devices=self.book)
        self.book.revoke("old phone")
        self.assertFalse(server._authorized(self._bearer(token)))         # noqa: SLF001
        self.assertIsNone(server.caller(self._bearer(token)))

    def test_the_legacy_shared_token_still_works_and_holds_everything(self):
        server = self._server(devices=self.book)
        self.assertTrue(server._authorized(self._bearer("shared-secret")))  # noqa: SLF001
        who = server.caller(self._bearer("shared-secret"))
        self.assertEqual(who, "legacy")
        for capability in CAPABILITIES:
            self.assertTrue(server.may(who, capability), capability)

    def test_a_device_only_holds_what_it_was_granted(self):
        token = self._pair(name="iPhone")                    # read + chat
        server = self._server(devices=self.book)
        who = server.caller(self._bearer(token))
        self.assertTrue(server.may(who, "read"))
        self.assertTrue(server.may(who, "chat"))
        self.assertFalse(server.may(who, "control"))
        self.assertFalse(server.may(who, "approve"))

    def test_approve_reaches_the_server_when_it_was_granted(self):
        token = self._pair(name="iPhone", capabilities=["read", "approve"])
        server = self._server(devices=self.book)
        self.assertTrue(server.may(server.caller(self._bearer(token)), "approve"))

    def test_nobody_holds_a_capability(self):
        server = self._server(devices=self.book)
        self.assertFalse(server.may(None, "read"))

    def test_a_query_token_works_for_a_page_that_cannot_set_a_header(self):
        token = self._pair(name="the TV")
        server = self._server(devices=self.book)
        self.assertTrue(server._authorized({}, {"token": [token]}))       # noqa: SLF001

    def test_a_server_with_no_book_still_takes_the_shared_token(self):
        """Every deployment older than stage 12 item 2."""
        server = self._server(devices=None)
        self.assertTrue(server._authorized(self._bearer("shared-secret")))  # noqa: SLF001
        self.assertFalse(server._authorized(self._bearer("nope")))          # noqa: SLF001

    def test_a_wrong_token_is_refused(self):
        self._pair(name="iPhone")
        server = self._server(devices=self.book)
        self.assertFalse(server._authorized(self._bearer("guessed")))     # noqa: SLF001


class ThePairAndDevicesCommands(DeviceBookCase):
    """`pair` draws the barcode; `devices` lists and revokes. Both act on
    the SAME book the HTTP auth reads -- two books would mean a phone
    paired in the terminal that the server had never heard of.
    """

    def _pair_cmd(self, args: str = ""):
        from simorgh.interface.dispatch import _pair_command

        return _pair_command(self.book, args)

    def _devices_cmd(self, args: str = ""):
        from simorgh.interface.dispatch import _devices_command

        return _devices_command(self.book, args)

    def test_pair_opens_a_code_and_shows_the_url_and_the_code(self):
        out = self._pair_cmd("Saeed iPhone").text
        pending = self.book.pending()
        self.assertIsNotNone(pending)
        self.assertIn(pending.code, out)
        self.assertIn("/pair#", out)
        self.assertIn("Saeed iPhone", out)
        self.assertIn("read, chat", out)

    def test_pair_grants_approve_only_when_it_is_typed(self):
        self.assertNotIn("approve", self._pair_cmd("phone").text)
        out = self._pair_cmd("phone with approve").text
        self.assertIn("approve", out)
        self.assertIn("Guardian's questions", out)
        self.assertIn("approve", self.book.pending().capabilities)

    def test_pair_takes_several_grants(self):
        self._pair_cmd("ipad with approve,control")
        self.assertEqual(self.book.pending().capabilities, ("read", "chat", "control", "approve"))

    def test_the_url_carries_the_code_in_the_fragment(self):
        out = self._pair_cmd("phone").text
        line = next(l for l in out.splitlines() if "/pair#" in l)
        self.assertNotIn("?", line)

    def test_devices_says_when_there_are_none(self):
        self.assertIn("no devices paired", self._devices_cmd().text)

    def test_devices_lists_what_each_may_do(self):
        self._pair()
        out = self._devices_cmd().text
        self.assertIn("1 device(s)", out)
        self.assertIn("read, chat", out)

    def test_devices_revoke_ends_a_token(self):
        device, token = self._pair(name="old phone")
        self.assertIsNotNone(self.book.resolve(token))
        out = self._devices_cmd(f"revoke {device.id}").text
        self.assertIn("stops working now", out)
        self.assertIsNone(self.book.resolve(token))

    def test_devices_revoke_needs_a_name(self):
        self.assertIn("usage:", self._devices_cmd("revoke").text)
        self.assertIn("no device called", self._devices_cmd("revoke nope").text)

    def test_devices_all_shows_the_revoked_ones_too(self):
        device, _ = self._pair(name="old phone")
        self.book.revoke(device.id)
        self.assertIn("no devices paired", self._devices_cmd().text)
        self.assertIn("REVOKED", self._devices_cmd("all").text)

    def test_without_a_book_both_say_so_rather_than_pretending(self):
        from simorgh.interface.dispatch import _devices_command, _pair_command

        self.assertIn("not available", _pair_command(None, "phone").text)
        self.assertIn("no device book", _devices_command(None).text)

    def test_both_verbs_are_in_the_command_table(self):
        """A command that does not autocomplete reads like one that does
        not exist (test_command_table.py's own lesson)."""
        from simorgh.interface.parser import COMMAND_NAMES, SECTIONS

        for verb in ("pair", "devices"):
            self.assertIn(verb, COMMAND_NAMES)
            self.assertTrue(any(verb in names for _, names in SECTIONS), verb)


class ThePairRoute(unittest.IsolatedAsyncioTestCase):
    """`POST /api/pair` -- the only unauthenticated write route, safe only
    because it can SPEND a code and cannot create one."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.book = DeviceBook(Path(self._tmp.name) / "devices.json")
        from simorgh.interface.httpapi import HttpApi

        self.api = HttpApi(bus=None, ledger=None, token="shared", devices=self.book)

    def _route(self):
        return self.api._routes[("POST", "/api/pair")]        # noqa: SLF001

    async def _post(self, payload: dict):
        status, body, _ = await self._route().handler({}, json.dumps(payload).encode("utf-8"), {})
        return status, json.loads(body)

    def test_it_is_registered_unauthenticated_and_rate_limited(self):
        route = self._route()
        self.assertFalse(route.auth, "the pairing route must not require a token")
        self.assertIsNotNone(route.rate, "the only open write route must be rate-limited")

    def test_no_other_write_route_is_unauthenticated(self):
        """The claim the design rests on, held from the table itself."""
        open_writes = [(m, path) for (m, path), route in self.api._routes.items()   # noqa: SLF001
                       if m != "GET" and not route.auth]
        self.assertEqual(open_writes, [("POST", "/api/pair")])

    async def test_a_good_code_returns_a_token_once(self):
        pending = self.book.begin_pairing(name="iPhone", capabilities=["read", "approve"])
        status, body = await self._post({"code": pending.code})
        self.assertEqual(status, 200)
        self.assertEqual(body["name"], "iPhone")
        self.assertIn("approve", body["capabilities"])
        self.assertIsNotNone(self.book.resolve(body["token"]))
        # and the code is spent
        status, body = await self._post({"code": pending.code})
        self.assertEqual(status, 403)

    async def test_a_wrong_code_is_refused_with_a_reason(self):
        self.book.begin_pairing(name="iPhone")
        status, body = await self._post({"code": "nope"})
        self.assertEqual(status, 403)
        self.assertIn("not the code", body["error"]["detail"])

    async def test_it_cannot_create_a_pairing(self):
        """With nothing open there is nothing to spend -- which is the whole
        reason an unauthenticated route is acceptable here."""
        status, body = await self._post({"code": "anything"})
        self.assertEqual(status, 403)
        self.assertIn("run `pair`", body["error"]["detail"])
        self.assertEqual(self.book.devices(), [])

    async def test_rubbish_is_a_400_not_a_crash(self):
        status, _, _ = await self._route().handler({}, b"{not json", {})
        self.assertEqual(status, 400)


class ThePairPage(unittest.IsolatedAsyncioTestCase):
    """The barcode's URL leads somewhere.

    `http://host/pair#CODE` looks like a link and people tap links. It was
    a 404 (the creator, 2026-09-25, opening it in Chrome), which reads as
    "Sim is broken" rather than "this is for the app".

    The code is in the FRAGMENT, which a browser never sends, so the server
    cannot be given it and the page reads `location.hash` itself. That is
    the property worth keeping: the code reaches this server exactly once,
    when it is spent at `POST /api/pair`, and never in a request line a
    proxy or a log could hold.
    """

    def setUp(self) -> None:
        from simorgh.interface.httpapi import HttpApi

        self.api = HttpApi(bus=None, ledger=None, token="shared")

    async def test_it_is_served_without_a_token(self):
        """Nobody has a token yet -- that is what pairing is for."""
        route = self.api._routes[("GET", "/pair")]                  # noqa: SLF001
        self.assertFalse(route.auth)
        status, body, kind = await route.handler({}, b"", {})
        self.assertEqual(status, 200)
        self.assertIn("text/html", kind)
        self.assertIn(b"Pair with Sim", body)

    async def test_the_page_reads_the_code_from_the_fragment(self):
        _, body, _ = await self.api._routes[("GET", "/pair")].handler({}, b"", {})   # noqa: SLF001
        text = body.decode("utf-8")
        self.assertIn("location.hash", text)
        # And says what to do when there is no code, rather than showing an
        # empty box.
        self.assertIn("pair my phone", text)

    async def test_it_carries_no_secret_of_its_own(self):
        _, body, _ = await self.api._routes[("GET", "/pair")].handler({}, b"", {})   # noqa: SLF001
        self.assertNotIn(b"shared", body, "the page must not contain the server's token")

    def test_the_page_is_open_but_is_not_a_write_route(self):
        """Being open is fine for a GET that holds nothing; the invariant
        that matters is that no WRITE route joined it."""
        from simorgh.interface.httpapi import _OPEN_ROUTES

        self.assertIn("/pair", _OPEN_ROUTES)
        open_writes = [(m, path) for (m, path), route in self.api._routes.items()    # noqa: SLF001
                       if m != "GET" and not route.auth]
        self.assertEqual(open_writes, [("POST", "/api/pair")])
