"""`/api/cam/live/` -- go2rtc's player and API behind Sim's token.

go2rtc listens on loopback only (domains/home/go2rtc.py); the phone and
the dashboard reach it through this route. A second video server open on
the LAN is the 2026-09-19 mistake (`/tv/hls/`, S15/V2), so: no token, no
video; the token never reaches go2rtc; and a WebSocket -- the video
itself -- is carried both ways for as long as it lasts."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.interface.httpapi import HttpApi
from tests.simorgh.interface.test_httpapi import _FakeBus

TOKEN = "house-secret-token"


class _FakeGo2rtc:
    """Answers a page with the request it saw; answers an upgrade with 101
    and then echoes every byte back, upper-cased."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self.server = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def _serve(self, reader, writer) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode("latin-1")
        self.requests.append(head)
        if "upgrade: websocket" in head.lower():
            writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
            await writer.drain()
            while data := await reader.read(1024):
                writer.write(data.upper())
                await writer.drain()
        else:
            body = head.split("\r\n", 1)[0].encode("latin-1")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
            await writer.drain()
        writer.close()


class CameraLiveProxy(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.go2rtc = _FakeGo2rtc()
        port = await self.go2rtc.start()
        self.api = HttpApi(_FakeBus(), ledger=None, host="127.0.0.1", port=0, token=TOKEN)
        self.api.go2rtc_port = port
        await self.api.start()
        self.addAsyncCleanup(self.api.stop)

    async def _raw(self, request: bytes, *, then: bytes = b"") -> tuple[bytes, bytes]:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.api.port)
        writer.write(request)
        await writer.drain()
        head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        rest = b""
        if then:
            writer.write(then)
            await writer.drain()
            rest = await asyncio.wait_for(reader.read(1024), 5)
        else:
            rest = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        return head, rest

    async def test_the_player_is_proxied_with_the_token_and_the_token_goes_no_further(self):
        head, body = await self._raw(b"GET /api/cam/live/stream.html?src=office&token=" + TOKEN.encode()
                                     + b" HTTP/1.1\r\nHost: sim\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 200"), head)
        self.assertEqual(body, b"GET /stream.html?src=office HTTP/1.1", "the path and query, without the token")
        self.assertNotIn(TOKEN, self.go2rtc.requests[-1], "go2rtc never sees the house token")
        self.assertIn(b"Set-Cookie: sim_cam=" + TOKEN.encode(), head)
        self.assertIn(b"Path=/api/cam/live/", head)

    async def test_no_token_is_no_video(self):
        head, _ = await self._raw(b"GET /api/cam/live/stream.html?src=office HTTP/1.1\r\nHost: sim\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 401"), head)
        self.assertEqual(self.go2rtc.requests, [], "nothing reached go2rtc")

    async def test_the_pages_own_relative_requests_pass_on_the_cookie(self):
        head, _ = await self._raw(b"GET /api/cam/live/video-stream.js HTTP/1.1\r\nHost: sim\r\nCookie: sim_cam="
                                  + TOKEN.encode() + b"\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 200"), head)
        head, _ = await self._raw(b"GET /api/cam/live/video-stream.js HTTP/1.1\r\nHost: sim\r\nCookie: sim_cam=wrong\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 401"), head)

    async def test_a_websocket_is_carried_both_ways(self):
        head, echoed = await self._raw(
            b"GET /api/cam/live/api/ws?src=office HTTP/1.1\r\nHost: sim\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nCookie: sim_cam=" + TOKEN.encode() + b"\r\n\r\n", then=b"frame-bytes")
        self.assertTrue(head.startswith(b"HTTP/1.1 101"), head)
        self.assertEqual(echoed, b"FRAME-BYTES")
        self.assertIn("GET /api/ws?src=office", self.go2rtc.requests[-1])

    async def test_a_stopped_relay_says_how_to_start_it(self):
        self.go2rtc.server.close()
        await self.go2rtc.server.wait_closed()
        head, body = await self._raw(b"GET /api/cam/live/stream.html?token=" + TOKEN.encode()
                                     + b" HTTP/1.1\r\nHost: sim\r\n\r\n")
        self.assertTrue(head.startswith(b"HTTP/1.1 503"), head)
        self.assertIn(b"cam_webrtc start", body)


if __name__ == "__main__":
    unittest.main()
