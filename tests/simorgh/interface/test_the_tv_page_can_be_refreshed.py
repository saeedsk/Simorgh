"""A change to the dashboard reaches the television.

Live, 2026-09-22: the camera-zoom fix was written, committed, and the
creator reported "none of those command actually put ring camera in
full screen on tv". The command was right and the page was old --
`dash.html` was read into memory once at boot, so the new page could
not be served even by re-casting, and a Cast receiver in a living room
is the last screen anybody thinks to refresh.

Two halves, both pinned here: the server serves the file as it is NOW,
and the page already on the TV is told which build the server has so it
can reload itself.
"""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import pytest

from simorgh.interface import httpapi as httpapi_mod
from simorgh.interface.httpapi import HttpApi

from .test_httpapi import _FakeBus

pytestmark = pytest.mark.contract


class TheTvPageCanBeRefreshed(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.static = Path(self._tmp.name)
        real = Path(httpapi_mod.__file__).resolve().parent / "static"
        for src in real.glob("*"):          # the logo and anything else the server reads at start
            (self.static / src.name).write_bytes(src.read_bytes())
        for name in ("dash.html", "tv.html", "dashboard.html", "remote.html"):
            (self.static / name).write_text(f"<html>{name} v1</html>")
        self._patch = mock.patch.object(httpapi_mod, "_STATIC_DIR", self.static)
        self._patch.start()
        self.addCleanup(self._patch.stop)
        self.api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0)
        await self.api.start()
        self.addAsyncCleanup(self.api.stop)

    async def asyncTearDown(self):
        self._tmp.cleanup()

    async def _get(self, path: str) -> str:
        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=5)
            conn.request("GET", path)
            body = conn.getresponse().read().decode()
            conn.close()
            return body

        return await asyncio.to_thread(_do)

    async def test_the_page_served_is_the_file_as_it_is_now(self):
        self.assertIn("dash.html v1", await self._get("/dash"))
        page = self.static / "dash.html"
        page.write_text("<html>dash.html v2</html>")
        os.utime(page, (time.time() + 1, time.time() + 1))
        self.assertIn("dash.html v2", await self._get("/dash"),
                      "the fix was in a string this process read at startup and held until it restarted")

    async def test_the_state_says_which_build_the_server_has(self):
        state = json.loads(await self._get("/api/dash/state"))
        first = state.get("build")
        self.assertTrue(first, "a page cannot notice a change it is never told about")
        page = self.static / "dash.html"
        page.write_text("<html>dash.html v2</html>")
        os.utime(page, (time.time() + 5, time.time() + 5))
        self.assertNotEqual(json.loads(await self._get("/api/dash/state")).get("build"), first)


if __name__ == "__main__":
    unittest.main()
