"""Sim announces itself, and says every address it answers on.

The app had ONE address, typed at pairing time, and it was a LAN address.
The creator turned Tailscale on, walked out of the house, and the app was
dead ("I turned on tailscale on both mac and iphone and went outside, sim
app didn't work", 2026-09-25) -- while Sim answered on the tailnet the
whole time, because `[interface] http_host` is `0.0.0.0`.

Two mechanisms, because neither covers both places:

  - mDNS (`_simorgh._tcp`) finds Sim with no configuration on the SAME
    network, and survives a new DHCP lease. Multicast is not routed, so it
    finds nothing over a tailnet.
  - The address list, which Sim reports itself, tailnet FIRST -- that is
    the one that works away from home.

Which is why the mDNS TXT record carries the address list too: one browse
hands a phone the address that mDNS itself can never reach.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.interface import addresses as addr
from simorgh.interface.announce import SERVICE, Announcer, command, how
from simorgh.interface.devices import DeviceBook
from simorgh.interface.httpapi import HttpApi


class WhereSimCanBeReached(unittest.TestCase):
    def test_the_tailnet_comes_before_the_lan(self):
        """Not an aesthetic choice: the tailnet address reaches Sim at home
        AND away, so preferring it costs a home user nothing and saves an
        away user the whole app."""
        with mock.patch.object(addr, "tailnet_name", return_value="mac.tailnet.ts.net"), \
             mock.patch.object(addr, "_source_address_for",
                               side_effect=lambda t: "100.71.125.30" if t == addr._TAILSCALE_DNS else "192.168.50.33"):
            found = addr.reachable(8765)
        self.assertEqual(found, ["http://mac.tailnet.ts.net:8765", "http://100.71.125.30:8765",
                                 "http://192.168.50.33:8765", "http://127.0.0.1:8765"])

    def test_a_machine_with_no_tailnet_still_gets_a_list(self):
        with mock.patch.object(addr, "tailnet_name", return_value=""), \
             mock.patch.object(addr, "_source_address_for",
                               side_effect=lambda t: "" if t == addr._TAILSCALE_DNS else "192.168.50.33"):
            found = addr.reachable(8765)
        self.assertEqual(found, ["http://192.168.50.33:8765", "http://127.0.0.1:8765"])

    def test_an_address_that_is_not_in_the_cgnat_range_is_not_called_a_tailnet_one(self):
        """`_source_address_for` answers for whatever route exists; on a
        machine with no tailnet that is the LAN address, and calling it a
        tailnet address would put a LAN-only address first."""
        with mock.patch.object(addr, "tailnet_name", return_value=""), \
             mock.patch.object(addr, "_source_address_for", return_value="192.168.50.33"):
            found = addr.reachable(8765)
        self.assertEqual(found[0], "http://192.168.50.33:8765")

    def test_no_address_is_ever_listed_twice(self):
        with mock.patch.object(addr, "tailnet_name", return_value=""), \
             mock.patch.object(addr, "_source_address_for", return_value="127.0.0.1"):
            self.assertEqual(addr.reachable(8765), ["http://127.0.0.1:8765"])

    def test_discovery_never_raises_on_a_machine_with_no_network(self):
        """Boot must not depend on this: an address list is a convenience."""
        with mock.patch("socket.socket", side_effect=OSError("no network")):
            self.assertEqual(addr._source_address_for("8.8.8.8"), "")


class WhatIsAnnounced(unittest.TestCase):
    def test_the_record_carries_the_addresses_mdns_cannot_reach(self):
        argv = command(8765, ["http://mac.ts.net:8765", "http://192.168.50.33:8765"])
        self.assertIn(SERVICE, argv)
        joined = " ".join(argv)
        self.assertIn("base=http://mac.ts.net:8765", joined)
        self.assertIn("addresses=http://mac.ts.net:8765 http://192.168.50.33:8765", joined)

    def test_nothing_to_publish_with_is_an_empty_argv_not_a_crash(self):
        with mock.patch("simorgh.interface.announce._dns_sd", return_value=""), \
             mock.patch("simorgh.interface.announce._avahi", return_value=""):
            self.assertEqual(command(8765, ["http://x:1"]), [])

    def test_an_announcer_with_no_publisher_says_what_is_missing(self):
        with mock.patch("simorgh.interface.announce._dns_sd", return_value=""), \
             mock.patch("simorgh.interface.announce._avahi", return_value=""):
            announcer = Announcer(8765, ["http://x:1"])
            self.assertFalse(announcer.start())
            self.assertIn("no mDNS publisher", announcer.detail)
            self.assertFalse(announcer.running)
            announcer.stop()          # must be safe to stop one that never started

    def test_this_machine_can_publish(self):
        """Not a mock: if macOS ever stops shipping `dns-sd` this should
        fail here rather than silently in a house."""
        self.assertIn(how(), ("dns-sd", "avahi", "zeroconf"))


class TheAddressesRoute(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.book = DeviceBook(Path(self._tmp.name) / "devices.json")
        self.api = HttpApi(bus=None, ledger=None, token="shared", devices=self.book, port=8765)

    def _token(self, *, capabilities=("read", "chat")) -> str:
        pending = self.book.begin_pairing(name="iPhone", capabilities=capabilities)
        _, token = self.book.redeem(pending.code)
        return token

    async def test_a_paired_device_is_told_every_address(self):
        handler = self.api._routes[("GET", "/api/addresses")].handler        # noqa: SLF001
        status, payload, _ = await handler({}, b"", {"authorization": f"Bearer {self._token()}"})
        self.assertEqual(status, 200)
        found = json.loads(payload)["addresses"]
        self.assertTrue(found, "this machine answers on at least loopback")
        self.assertTrue(all(a.startswith("http://") for a in found), found)

    async def test_an_unpaired_caller_is_refused(self):
        handler = self.api._routes[("GET", "/api/addresses")].handler        # noqa: SLF001
        status, _, _ = await handler({}, b"", {})
        self.assertEqual(status, 403)

    async def test_pairing_hands_the_addresses_over_at_the_one_certain_moment(self):
        """The phone is definitely talking to Sim while it pairs. Learning
        the tailnet address then is what saves the first trip out."""
        pending = self.book.begin_pairing(name="iPhone", capabilities=("read", "chat"))
        handler = self.api._routes[("POST", "/api/pair")].handler            # noqa: SLF001
        status, payload, _ = await handler({}, json.dumps({"code": pending.code}).encode(), {})
        self.assertEqual(status, 200, payload)
        body = json.loads(payload)
        self.assertIn("addresses", body)
        self.assertTrue(body["addresses"])
