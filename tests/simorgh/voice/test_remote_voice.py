"""A phone as a microphone, over a WebSocket (voice/remote.py).

The creator, 2026-09-24: "I like to have live voice connection from my
iphone to sim". This is the transport and the microphone; the second
VoiceSession that answers into a phone's ear rather than out loud in the
house is the step after.

The handshake is checked against RFC 6455 section 1.3's own worked
example, which caught a transposed GUID on the first run -- `...95CA-
5AB0DC85B11F` instead of `...95CA-C5AB0DC85B11`. Every browser would have
refused the connection, and the failure would have looked like a network
problem rather than one character.
"""

from __future__ import annotations

import asyncio
import unittest

from simorgh.voice.api import SAMPLE_RATE, SAMPLE_WIDTH
from simorgh.voice.remote import (
    FRAME_BYTES,
    ProtocolError,
    RemoteMicrophone,
    RemoteSpeaker,
    accept_key,
    frame,
    handshake_response,
    read_frame,
    token_ok,
)


def _client_frame(payload: bytes, *, opcode: int = 0x2, mask: bytes = b"\x01\x02\x03\x04") -> bytes:
    """What a BROWSER sends: masked, as RFC 6455 section 5.1 requires."""
    body = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
    size = len(payload)
    head = bytes([0x80 | opcode])
    if size < 126:
        head += bytes([0x80 | size])
    elif size < (1 << 16):
        head += bytes([0x80 | 126]) + size.to_bytes(2, "big")
    else:
        head += bytes([0x80 | 127]) + size.to_bytes(8, "big")
    return head + mask + body


class _Reader:
    def __init__(self, data: bytes) -> None:
        self._data, self._at = data, 0

    async def readexactly(self, n: int) -> bytes:
        if self._at + n > len(self._data):
            raise asyncio.IncompleteReadError(self._data[self._at:], n)
        out = self._data[self._at:self._at + n]
        self._at += n
        return out


class TheHandshake(unittest.TestCase):
    def test_the_accept_key_is_the_rfc_worked_example(self):
        self.assertEqual(accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_a_browser_upgrade_is_answered_101(self):
        out = handshake_response({"Upgrade": "websocket", "Connection": "Upgrade",
                                  "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ=="})
        self.assertIsNotNone(out)
        self.assertTrue(out.startswith(b"HTTP/1.1 101 "))
        self.assertIn(b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=", out)

    def test_header_case_does_not_matter(self):
        """Browsers send both spellings, at different times."""
        for headers in (
            {"upgrade": "WebSocket", "connection": "keep-alive, Upgrade", "sec-websocket-key": "abc"},
            {"UPGRADE": "websocket", "CONNECTION": "upgrade", "SEC-WEBSOCKET-KEY": "abc"},
        ):
            self.assertIsNotNone(handshake_response(headers), headers)

    def test_an_ordinary_request_is_not_an_upgrade(self):
        self.assertIsNone(handshake_response({"Host": "x"}))
        self.assertIsNone(handshake_response({"Upgrade": "websocket"}))          # no Connection
        self.assertIsNone(handshake_response({"Upgrade": "websocket", "Connection": "Upgrade"}))  # no key


class TheToken(unittest.TestCase):
    def test_an_unset_token_admits_nobody(self):
        """A microphone open to the LAN is worse than a readable dashboard."""
        self.assertFalse(token_ok("anything", ""))
        self.assertFalse(token_ok("", ""))

    def test_only_the_right_token_is_accepted(self):
        self.assertTrue(token_ok("s3cret", "s3cret"))
        self.assertFalse(token_ok("s3cre", "s3cret"))
        self.assertFalse(token_ok("S3CRET", "s3cret"))


class TheFraming(unittest.IsolatedAsyncioTestCase):
    async def test_a_masked_client_frame_is_unmasked(self):
        opcode, payload = await read_frame(_Reader(_client_frame(b"hello")))
        self.assertEqual((opcode, payload), (0x2, b"hello"))

    async def test_the_three_length_forms_all_round_trip(self):
        for size in (5, 125, 126, 1000, 70_000):
            data = bytes(range(256)) * (size // 256) + bytes(size % 256)
            _, payload = await read_frame(_Reader(_client_frame(data[:size])))
            self.assertEqual(len(payload), size, f"size {size}")

    async def test_continuation_frames_are_joined(self):
        first = _client_frame(b"abc", opcode=0x2)[:]
        first = bytes([first[0] & 0x7F]) + first[1:]      # clear FIN
        rest = _client_frame(b"def", opcode=0x0)
        _, payload = await read_frame(_Reader(first + rest))
        self.assertEqual(payload, b"abcdef")

    async def test_an_unmasked_client_frame_is_a_protocol_error(self):
        """Tolerating it is how a proxy's half-understood traffic becomes audio."""
        with self.assertRaises(ProtocolError):
            await read_frame(_Reader(frame(b"hello")))     # a SERVER frame, unmasked

    async def test_a_server_frame_is_never_masked(self):
        self.assertFalse(frame(b"x")[1] & 0x80)

    async def test_an_oversized_frame_is_refused_not_buffered(self):
        head = bytes([0x82, 0x80 | 127]) + (1 << 30).to_bytes(8, "big") + b"\x00\x00\x00\x00"
        with self.assertRaises(ProtocolError):
            await read_frame(_Reader(head))


class TheRemoteMicrophone(unittest.IsolatedAsyncioTestCase):
    async def test_it_yields_whole_frames_only(self):
        """A short frame reads as a QUIET frame to the endpointer, which is
        how a chopped-up network stream would look like silence."""
        mic = RemoteMicrophone()
        mic.feed(b"\x01\x02" * (FRAME_BYTES // 2))        # exactly one frame
        mic.feed(b"\x03\x04" * 10)                        # a partial one
        mic.close()
        frames = [f async for f in mic.stream()]
        self.assertEqual(len(frames[0]), FRAME_BYTES)
        self.assertEqual(len(frames[-1]), 20, "the held tail should flush at close")

    async def test_a_split_frame_is_reassembled(self):
        mic = RemoteMicrophone()
        whole = bytes(FRAME_BYTES)
        mic.feed(whole[:100])
        mic.feed(whole[100:])
        mic.close()
        frames = [f async for f in mic.stream()]
        self.assertEqual([len(f) for f in frames], [FRAME_BYTES])

    async def test_closing_ends_a_waiting_stream(self):
        """A phone walking out of wifi must not leave the session hanging."""
        mic = RemoteMicrophone()
        pulled = asyncio.ensure_future(self._drain(mic))
        await asyncio.sleep(0)
        mic.close()
        self.assertEqual(await asyncio.wait_for(pulled, timeout=2), [])

    async def _drain(self, mic) -> list:
        return [f async for f in mic.stream()]

    async def test_a_listener_that_falls_behind_loses_the_OLDEST_audio(self):
        """A growing delay is worse than a gap: the recent past is what the
        person is waiting to hear answered."""
        mic = RemoteMicrophone(max_queued=3)
        for i in range(6):
            mic.feed(bytes([i]) * FRAME_BYTES)
        mic.close()
        frames = [f async for f in mic.stream()]
        self.assertEqual(mic.dropped, 3)
        self.assertEqual(frames[0][0], 3, "the three oldest frames should be the ones gone")

    async def test_max_seconds_stops_it(self):
        mic = RemoteMicrophone()
        for _ in range(100):
            mic.feed(bytes(FRAME_BYTES))
        got = [f async for f in mic.stream(max_seconds=0.06)]     # two 30 ms frames
        self.assertEqual(len(got), 2)

    async def test_capture_ends_where_the_endpointer_says(self):
        class _Ends:
            def __init__(self): self.seen = 0
            def feed(self, chunk):
                self.seen += 1
                return self.seen == 2

        mic = RemoteMicrophone()
        for _ in range(5):
            mic.feed(bytes(FRAME_BYTES))
        mic.close()
        audio = await mic.capture(max_seconds=10, endpointer=_Ends())
        self.assertEqual(len(audio.pcm), FRAME_BYTES * 2)
        self.assertEqual(audio.sample_rate, SAMPLE_RATE)


class TheRemoteSpeaker(unittest.IsolatedAsyncioTestCase):
    async def test_it_sends_the_voice_and_takes_the_audio_s_own_time(self):
        """It keeps the turn's time like `SilentSpeaker`: the speaking flag,
        the echo gate and barge-in all follow the player, so returning at
        once would have Sim think it had finished before a word was heard."""
        from simorgh.voice.api import Audio

        sent: list[bytes] = []

        async def _send(data: bytes) -> None:
            sent.append(data)

        seconds = 0.12
        pcm = bytes(int(SAMPLE_RATE * seconds) * SAMPLE_WIDTH)
        started = asyncio.get_running_loop().time()
        await RemoteSpeaker(_send).play(Audio(pcm=pcm, sample_rate=SAMPLE_RATE))
        took = asyncio.get_running_loop().time() - started

        self.assertEqual(b"".join(sent), pcm)
        self.assertEqual(len(sent), 4)                      # 120 ms in 30 ms frames
        self.assertGreater(took, seconds * 0.7, "it returned faster than the audio plays")

    async def test_stop_cuts_it_mid_reply(self):
        """Barge-in has to be able to stop a phone reply too."""
        from simorgh.voice.api import Audio

        speaker = RemoteSpeaker(lambda data: asyncio.sleep(0))
        sent: list[bytes] = []

        async def _send(data: bytes) -> None:
            sent.append(data)
            speaker.stop()

        speaker._send = _send                                # noqa: SLF001
        await speaker.play(Audio(pcm=bytes(FRAME_BYTES * 10), sample_rate=SAMPLE_RATE))
        self.assertEqual(len(sent), 1)
