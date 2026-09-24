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
