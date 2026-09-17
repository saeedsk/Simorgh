"""A stalled reply must not mute Sim (voice/playback.py).

`play_stream` runs holding `speech_lock`, and neither of its two waits
was bounded: the wait for the next synthesised chunk, and the wait for
the speaker to finish playing one. A synthesiser that stopped yielding,
or a speaker that never returned, held that lock for as long as it
hung -- and every later reply queued behind it. Sim did not get slow,
it went mute.

Measured on the creator's own session, 2026-09-16: eight turns waited
on that lock, 262s lost in total, the worst a single 48.3s wait. The
innocent explanation was ruled out by the neighbouring turns -- at
22:19:48 a turn waited 48.34s while the previous spoken turn had ended
184s earlier after speaking for 6.6s. Nothing was talking. Something
was stuck holding the lock.

A truncated reply is recoverable. A mute assistant is not.
"""

from __future__ import annotations

import asyncio
import unittest

from simorgh.voice.api import Audio, AudioChunk
from simorgh.voice.playback import StreamingPlayer

RATE = 16_000
CHUNK_MS = 100


def _chunk(request_id: str, seq: int, *, final: bool = False) -> AudioChunk:
    return AudioChunk(pcm=b"\x00" * int(RATE * 2 * CHUNK_MS / 1000), sample_rate=RATE,
                      request_id=request_id, seq=seq, final=final)


class _Speaker:
    def __init__(self) -> None:
        self.played: list[Audio] = []

    async def play(self, audio: Audio) -> None:
        self.played.append(audio)

    async def stop(self) -> None:
        return None


class _HangingSpeaker(_Speaker):
    """Accepts the audio and never comes back."""

    async def play(self, audio: Audio) -> None:
        self.played.append(audio)
        await asyncio.Event().wait()


async def _never(request_id: str):
    """A synthesiser that yields nothing and never ends."""
    await asyncio.Event().wait()
    yield  # pragma: no cover -- unreachable, keeps this an async generator


async def _one_then_hang(request_id: str):
    yield _chunk(request_id, 0)
    await asyncio.Event().wait()


async def _two(request_id: str):
    yield _chunk(request_id, 0)
    yield _chunk(request_id, 1, final=True)


class PlaybackStallTestCase(unittest.IsolatedAsyncioTestCase):
    def _player(self, speaker=None):
        return StreamingPlayer(speaker or _Speaker(), stall_timeout_s=0.05)

    async def test_a_synthesiser_that_never_yields_gives_up(self):
        report = await asyncio.wait_for(
            self._player().play_stream(_never("r1"), request_id="r1"), timeout=5)
        self.assertTrue(report.stalled)
        self.assertEqual(report.chunks, 0)

    async def test_a_synthesiser_that_stops_midway_keeps_what_it_said(self):
        """A truncated reply, not a lost one -- and not a held lock."""
        report = await asyncio.wait_for(
            self._player().play_stream(_one_then_hang("r2"), request_id="r2"), timeout=5)
        self.assertTrue(report.stalled)
        self.assertEqual(report.chunks, 1)

    async def test_a_speaker_that_never_returns_gives_up(self):
        speaker = _HangingSpeaker()
        report = await asyncio.wait_for(
            self._player(speaker).play_stream(_two("r3"), request_id="r3"), timeout=5)
        self.assertTrue(report.stalled)
        self.assertEqual(len(speaker.played), 1, "it stopped at the chunk that hung")

    async def test_the_speech_lock_is_released_either_way(self):
        """The whole point. `play_stream` is called inside
        `async with speech_lock`, so returning IS the fix."""
        lock = asyncio.Lock()
        async with lock:
            await asyncio.wait_for(
                self._player().play_stream(_never("r4"), request_id="r4"), timeout=5)
        self.assertFalse(lock.locked())

    async def test_an_ordinary_reply_is_untouched(self):
        speaker = _Speaker()
        report = await self._player(speaker).play_stream(_two("r5"), request_id="r5")
        self.assertFalse(report.stalled)
        self.assertEqual(report.chunks, 2)
        self.assertTrue(speaker.played)

    async def test_the_bound_is_not_charged_against_a_long_reply(self):
        """The speaker's allowance is the audio's own length PLUS the
        bound, so a genuinely long utterance is never cut short."""
        class _Slow(_Speaker):
            async def play(self, audio: Audio) -> None:
                self.played.append(audio)
                await asyncio.sleep(audio.seconds)   # real time, as a speaker does

        report = await self._player(_Slow()).play_stream(_two("r6"), request_id="r6")
        self.assertFalse(report.stalled)
        self.assertEqual(report.chunks, 2)


if __name__ == "__main__":
    unittest.main()
