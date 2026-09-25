"""`GET /api/house/assistant`: the app does not ask the person for an address.

The Home Assistant tab is a web view and needs a URL. Sim already has the
right one, in `HOME_ASSISTANT_URL`, because that is what its own `home_*`
tools call -- so asking the person to type it into the phone as well was
asking them to keep two copies of one fact in step. The creator,
2026-09-25: "in the home tab, automatically make ha available to me (don't
like the idea that i have to manually enter ha address)".

The URL and never the token: this is a browser, so it is HA's own login and
its own cookie. Interface is allowed to read exactly one of the two
(`kernel/registry.py`).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.interface.devices import DeviceBook
from simorgh.interface.httpapi import HttpApi


class ThePhoneIsToldWhereHomeAssistantIs(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.book = DeviceBook(Path(self._tmp.name) / "devices.json")

    def _api(self, url: str = "http://192.168.50.208") -> HttpApi:
        return HttpApi(bus=None, ledger=None, token="shared", devices=self.book, home_assistant_url=url)

    def _token(self, *, capabilities=("read", "chat")) -> str:
        pending = self.book.begin_pairing(name="iPhone", capabilities=capabilities)
        _, token = self.book.redeem(pending.code)
        return token

    async def _get(self, api: HttpApi, token: str | None):
        handler = api._routes[("GET", "/api/house/assistant")].handler    # noqa: SLF001
        headers = {"authorization": f"Bearer {token}"} if token else {}
        status, payload, _ = await handler({}, b"", headers)
        return status, json.loads(payload)

    async def test_a_paired_device_is_told_the_address(self):
        status, body = await self._get(self._api(), self._token())
        self.assertEqual(status, 200)
        self.assertEqual(body["url"], "http://192.168.50.208")
        self.assertTrue(body["configured"])

    async def test_a_trailing_slash_is_not_passed_on(self):
        """It is joined to paths on the phone; two slashes 404 on HA."""
        status, body = await self._get(self._api("http://192.168.50.208/"), self._token())
        self.assertEqual(body["url"], "http://192.168.50.208")

    async def test_an_unconfigured_house_says_so_with_the_fix(self):
        status, body = await self._get(self._api(""), self._token())
        self.assertEqual(status, 200, "not knowing is an answer, not an error")
        self.assertFalse(body["configured"])
        self.assertIn("HOME_ASSISTANT_URL", body["detail"])

    async def test_an_unpaired_caller_is_refused(self):
        status, _ = await self._get(self._api(), None)
        self.assertEqual(status, 403)

    async def test_the_token_is_not_something_this_server_can_leak(self):
        """Interface is not allowed to READ `HOME_ASSISTANT_TOKEN`, so there
        is nothing here to hand out even by mistake. Pinned from the
        allowlist itself, so widening it fails this test."""
        from simorgh.kernel.registry import DEFAULT_SECRETS

        allowed = DEFAULT_SECRETS["interface"]
        self.assertIn("HOME_ASSISTANT_URL", allowed)
        self.assertNotIn("HOME_ASSISTANT_TOKEN", allowed)
