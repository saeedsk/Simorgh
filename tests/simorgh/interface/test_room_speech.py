"""Stage 13 item 3: `/api/room/speech`, a room satellite's reply.

The board's media player fetches the reply by URL and cannot carry a
token, so the route is open -- and what stands in for the token is that
it serves ONLY a ref Voice announced on `voice.room.speech`, only for
two minutes, and nothing else from the ledger.
"""

from __future__ import annotations

import asyncio
import http.client
import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.interface.httpapi import ROOM_SPEECH_TTL_S, HttpApi
from tests.simorgh.interface.test_httpapi import _FakeBus


class _Ledger:
    def __init__(self) -> None:
        self.read: list[str] = []

    async def get_blob(self, ref):
        self.read.append(ref)
        return b"fLaC-fake"


class RoomSpeechTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.ledger = _Ledger()
        self.bus = _FakeBus()
        self.api = HttpApi(self.bus, ledger=self.ledger, host="127.0.0.1", port=0, token="house-secret")
        await self.api.start()
        self.addAsyncCleanup(self.api.stop)
        handler = next(entry[1] for entry in self.bus._subs if entry[0] == topics.VOICE_ROOM_SPEECH)  # noqa: SLF001
        await handler(Message.new(topics.VOICE_ROOM_SPEECH, source="voice",
                                  payload={"ref": "blob:k1", "seconds": 1.2, "device": "kitchen",
                                           "content_type": "audio/flac"}))

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=5)
        conn.request("GET", path)                     # no token: the board has none
        resp = conn.getresponse()
        body = resp.read()
        ctype = resp.getheader("Content-Type")
        conn.close()
        return resp.status, body, ctype

    async def test_an_announced_piece_is_served_without_a_token(self):
        status, body, ctype = await asyncio.to_thread(self._get, "/api/room/speech?ref=blob:k1")
        self.assertEqual((status, body, ctype), (200, b"fLaC-fake", "audio/flac"))

    async def test_anything_else_in_the_ledger_is_not_and_is_never_read(self):
        status, _b, _c = await asyncio.to_thread(self._get, "/api/room/speech?ref=blob:secret-transcript")
        self.assertEqual(status, 404)
        self.assertEqual(self.ledger.read, [], "an unlisted ref never reaches the ledger")
        status, _b, _c = await asyncio.to_thread(self._get, "/api/room/speech")
        self.assertEqual(status, 404)

    async def test_a_piece_expires(self):
        later = self.api._now() + ROOM_SPEECH_TTL_S + 1  # noqa: SLF001
        self.api._now = lambda: later  # type: ignore[method-assign]
        status, _b, _c = await asyncio.to_thread(self._get, "/api/room/speech?ref=blob:k1")
        self.assertEqual(status, 404)

    async def test_the_tv_route_still_wants_its_token(self):
        """The open route is this one alone; the TV's is unchanged."""
        status, _b, _c = await asyncio.to_thread(self._get, "/api/tv/speech?ref=blob:k1")
        self.assertIn(status, (401, 403))


if __name__ == "__main__":
    unittest.main()
