"""A token-gated HLS relay a player can actually play.

`/tv/hls/` is gated: it was open until 2026-09-19 and that let anyone on
the LAN watch the house (S15/V2). But a player asks for
`index.m3u8?token=X`, reads `index59.ts` out of the playlist, and resolves
that against the playlist's URL -- which DROPS the query string. So every
segment arrived with no token, the route refused it, and the player showed
a black rectangle and no error: a 401 on a segment is not something HLS
has a way to report.

The creator, 2026-09-25: "in the camera page, when I click on camera feed
icon, the live view only shows a black screen and no live feed is actually
happening" -- with ffmpeg relaying that camera the whole time. The dash
page's `<video>` and the TV's resolve relative URLs the same way, so all
three had it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.interface.devices import DeviceBook
from simorgh.interface.httpapi import HttpApi

PLAYLIST = b"""#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:59
#EXTINF:4.008722,
index59.ts
#EXTINF:3.991656,
index60.ts
"""


class HlsSegmentsCarryTheToken(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name) / "workspace" / "cameras" / "hls" / "11"
        root.mkdir(parents=True)
        (root / "index.m3u8").write_bytes(PLAYLIST)
        (root / "index59.ts").write_bytes(b"\x47" + b"\x00" * 187)
        self.book = DeviceBook(Path(self._tmp.name) / "devices.json")
        self.api = HttpApi(bus=None, ledger=None, token="shared", devices=self.book)
        self.api._hls_root = (root.parent).resolve()          # noqa: SLF001

    def _token(self) -> str:
        pending = self.book.begin_pairing(name="iPhone", capabilities=("read", "chat"))
        _, token = self.book.redeem(pending.code)
        return token

    async def _get(self, rest: str, token: str | None):
        handler = next(h for method, prefix, h in self.api._prefixes             # noqa: SLF001
                       if method == "GET" and prefix == "/tv/hls/")
        query = {"token": [token]} if token else {}
        return await handler(query, b"", {}, rest=rest)

    async def test_every_segment_in_the_playlist_carries_the_token(self):
        token = self._token()
        status, body, kind = await self._get("11/index.m3u8", token)
        self.assertEqual(status, 200)
        self.assertEqual(kind, "application/vnd.apple.mpegurl")
        text = body.decode()
        self.assertIn(f"index59.ts?token={token}", text)
        self.assertIn(f"index60.ts?token={token}", text)

    async def test_the_tags_are_left_exactly_as_they_were(self):
        status, body, _ = await self._get("11/index.m3u8", self._token())
        self.assertEqual(status, 200)
        for tag in (b"#EXTM3U", b"#EXT-X-VERSION:3", b"#EXT-X-MEDIA-SEQUENCE:59", b"#EXTINF:4.008722,"):
            self.assertIn(tag, body)
        # A tag must never be given a query string: a player parses these
        # and a mangled one breaks the whole stream rather than one segment.
        self.assertNotIn(b"#EXTM3U?token", body)
        self.assertNotIn(b"#EXTINF:4.008722,?token", body)

    async def test_a_segment_named_by_the_rewritten_playlist_is_served(self):
        """The round trip: read the playlist as a player does, then ask for
        the first segment exactly as the playlist names it."""
        token = self._token()
        _, playlist, _ = await self._get("11/index.m3u8", token)
        first = next(line for line in playlist.decode().splitlines()
                     if line and not line.startswith("#"))
        path, _, query = first.partition("?")
        status, body, kind = await self._get(f"11/{path}", query.removeprefix("token="))
        self.assertEqual((status, kind), (200, "video/mp2t"))
        self.assertEqual(body[:1], b"\x47", "an MPEG-TS packet, not an error page")

    async def test_a_header_authenticated_caller_gets_the_playlist_untouched(self):
        """It will send the same header for the segments, and there is no
        token in the query to append."""
        _, body, _ = await self._get("11/index.m3u8", None)
        self.assertEqual(body, PLAYLIST)

    async def test_nothing_outside_the_relay_directory_is_served(self):
        for escape in ("../../../etc/passwd", "11/../../../../etc/passwd"):
            status, _, _ = await self._get(escape, self._token())
            self.assertEqual(status, 404, escape)
