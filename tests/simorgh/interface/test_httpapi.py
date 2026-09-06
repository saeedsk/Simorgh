"""HttpApi: the live-status dashboard's server (simorgh/interface/httpapi.py).
Real sockets, real HTTP/1.1 requests via `http.client` -- this module
hand-rolls request parsing, so the thing actually worth testing is what
a real client sees on the wire, not a mocked reader/writer."""

from __future__ import annotations

import http.client
import json
import unittest

from simorgh.interface.httpapi import HttpApi


class _FakeReply:
    def __init__(self, payload: dict) -> None:
        self.payload = payload


class _FakeBus:
    """`request_or_error` is the only method HttpApi calls."""

    def __init__(self, payload: dict | None = None, *, raises: Exception | None = None) -> None:
        self._payload = payload or {}
        self._raises = raises
        self.calls: list = []

    async def request_or_error(self, message, *, timeout=None):
        self.calls.append((message, timeout))
        if self._raises is not None:
            raise self._raises
        return _FakeReply(self._payload)


class HttpApiTestCase(unittest.IsolatedAsyncioTestCase):
    async def _start(self, bus) -> HttpApi:
        api = HttpApi(bus, host="127.0.0.1", port=0)  # port 0 -> OS picks a free one
        await api.start()
        self.addAsyncCleanup(api.stop)
        return api

    async def _get(self, api: HttpApi, path: str) -> http.client.HTTPResponse:
        import asyncio

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.body = resp.read()
            conn.close()
            return resp

        return await asyncio.to_thread(_do)

    async def test_root_serves_the_dashboard_html(self):
        api = await self._start(_FakeBus({}))
        resp = await self._get(api, "/")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.getheader("Content-Type"))
        self.assertIn(b"Simorgh", resp.body)
        self.assertIn(b"/api/status", resp.body)  # the page actually polls this route

    async def test_api_status_proxies_the_real_status_reply_as_json(self):
        payload = {"state": "running", "mode": "single", "run_id": "abc123",
                   "uptime_seconds": 12.5, "subsystems": [{"name": "bus", "status": "ok"}]}
        bus = _FakeBus(payload)
        api = await self._start(bus)
        resp = await self._get(api, "/api/status")
        self.assertEqual(resp.status, 200)
        self.assertIn("application/json", resp.getheader("Content-Type"))
        self.assertEqual(json.loads(resp.body), payload)
        self.assertEqual(len(bus.calls), 1)

    async def test_api_status_degrades_honestly_when_the_bus_request_fails(self):
        """An unreachable kernel is data for the page to render (the
        "lost contact" banner), never a crash -- graceful degradation
        applies to this dashboard's own backend call same as anywhere
        else in the system."""
        api = await self._start(_FakeBus(raises=TimeoutError("no reply")))
        resp = await self._get(api, "/api/status")
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.body)
        self.assertEqual(body["state"], "unknown")
        self.assertIn("error", body)

    async def test_unknown_path_is_404(self):
        api = await self._start(_FakeBus({}))
        resp = await self._get(api, "/nope")
        self.assertEqual(resp.status, 404)

    async def test_non_get_method_is_405(self):
        import asyncio

        api = await self._start(_FakeBus({}))

        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", api.port, timeout=5)
            conn.request("POST", "/api/status", body=b"{}")
            resp = conn.getresponse()
            resp.read()
            conn.close()
            return resp

        resp = await asyncio.to_thread(_do)
        self.assertEqual(resp.status, 405)

    async def test_a_bare_connection_with_no_bytes_does_not_crash_the_server(self):
        import asyncio

        api = await self._start(_FakeBus({}))
        reader, writer = await asyncio.open_connection("127.0.0.1", api.port)
        writer.close()
        await writer.wait_closed()
        # The server must still answer the next real request.
        resp = await self._get(api, "/")
        self.assertEqual(resp.status, 200)

    async def test_two_requests_in_a_row_both_get_full_responses(self):
        api = await self._start(_FakeBus({"state": "running"}))
        first = await self._get(api, "/api/status")
        second = await self._get(api, "/api/status")
        self.assertEqual(first.status, 200)
        self.assertEqual(second.status, 200)


if __name__ == "__main__":
    unittest.main()
