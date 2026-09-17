"""A slow engine is waited for, and a stopped one still is not.

The creator, 2026-09-17, after two hours: "miso experience was a failure
... I didn't hear a single word live from sim itself, however i could
manual play wav files".

Both halves were true and together they name the fault exactly.
MisoTTS synthesised correctly every time -- the wavs were on disk and
played by hand -- and not one sample ever reached the speaker.

`StreamingPlayer.play_stream` bounds the wait for each synthesised
chunk by `tts_stall_timeout_s`, a flat 20 seconds. Miso needs ~65 s for
a first piece (10x real time warm, 44x cold). So the player timed out,
set `stalled`, gave up the speech lock, and returned before a sample was
played -- while the engine went on rendering perfectly. The ledger
settles it: 1,209 kokoro turns, 33 piper, 12 chatterbox (which fits
inside 20 s at ~2x), and zero miso.

The guard itself is right and was expensive to learn: an unbounded wait
holds `speech_lock` forever and leaves Sim MUTE rather than slow -- 262 s
lost across eight turns on 2026-09-16. So it is not removed or raised
for everyone. The wait now comes from the engine's own measured
`pace_ratio`, the same figure `hold_seconds` already uses, and the
floor is unchanged for anything that keeps up.
"""

from __future__ import annotations

import asyncio
import unittest

from simorgh.voice.api import Audio, AudioChunk, TtsRequest
from simorgh.voice.playback import StreamingPlayer
from simorgh.voice.tts.streaming import MAX_CHUNK_WAIT_S, StreamingSynthesiser


class _Speaker:
    def __init__(self):
        self.played: list[Audio] = []

    async def play(self, audio: Audio) -> None:
        self.played.append(audio)


def _request(text: str = "hello saeed, how are you doing today", lane: str = "expressive") -> TtsRequest:
    return TtsRequest(request_id="r", pieces=((text, 0),), voice="", speed=1.0, lane=lane)


class _Engine:
    def __init__(self, ratio: float):
        self._ratio = ratio
        self.name = "fake"

    def pace_ratio(self, lane: str = "") -> float:
        return self._ratio


async def _after(delay: float, *, request_id: str = "r"):
    """One chunk, that long in coming."""
    await asyncio.sleep(delay)
    yield AudioChunk(pcm=b"\x00\x01" * 800, sample_rate=24_000, request_id=request_id,
                     seq=0, final=True, text="hi", pause_ms=0)


class TheWaitComesFromThePaceTestCase(unittest.TestCase):
    def test_an_engine_that_keeps_up_asks_for_nothing_extra(self):
        """Kokoro renders five times faster than it speaks: the caller
        keeps its own floor, and the mute-Sim guard is untouched."""
        self.assertEqual(StreamingSynthesiser(_Engine(0.0)).chunk_timeout(_request()), 0.0)

    def test_a_barely_slow_engine_still_asks_for_nothing(self):
        self.assertEqual(StreamingSynthesiser(_Engine(1.1)).chunk_timeout(_request()), 0.0)

    def test_a_ten_times_engine_asks_for_a_minute(self):
        """Miso measured 10x warm. The piece is ~2.6 s of speech, so
        rendering it takes ~26 s; the wait must clear that."""
        wait = StreamingSynthesiser(_Engine(10.0)).chunk_timeout(_request())
        self.assertGreater(wait, 26.0)
        self.assertLessEqual(wait, MAX_CHUNK_WAIT_S)

    def test_a_longer_piece_is_waited_for_longer(self):
        short = StreamingSynthesiser(_Engine(10.0)).chunk_timeout(_request("hello"))
        long = StreamingSynthesiser(_Engine(10.0)).chunk_timeout(_request("hello " * 40))
        self.assertGreater(long, short)

    def test_there_is_a_ceiling(self):
        """Past this the engine really has stopped, and a mute Sim is
        worse than a truncated reply."""
        wait = StreamingSynthesiser(_Engine(44.0)).chunk_timeout(_request("hello " * 200))
        self.assertEqual(wait, MAX_CHUNK_WAIT_S)


class ThePlayerHonoursItTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_slow_chunk_is_played_when_the_caller_allows_it(self):
        """The fix, in one assertion: audio that arrives after the floor
        still reaches the speaker."""
        speaker = _Speaker()
        player = StreamingPlayer(speaker, stall_timeout_s=0.05)
        report = await player.play_stream(_after(0.25), request_id="r", chunk_timeout=2.0)
        self.assertEqual(len(speaker.played), 1, "the audio never reached the speaker")
        self.assertFalse(report.stalled)

    async def test_without_it_the_same_chunk_is_abandoned(self):
        """What happened every time to Miso."""
        speaker = _Speaker()
        player = StreamingPlayer(speaker, stall_timeout_s=0.05)
        report = await player.play_stream(_after(0.25), request_id="r")
        self.assertEqual(speaker.played, [], "this is the bug: it should have given up")
        self.assertTrue(report.stalled)

    async def test_an_engine_that_really_stopped_is_still_abandoned(self):
        """The guard must still fire, or Sim goes mute holding the lock."""
        async def _never():
            await asyncio.sleep(10)
            yield None

        speaker = _Speaker()
        player = StreamingPlayer(speaker, stall_timeout_s=0.05)
        report = await player.play_stream(_never(), request_id="r", chunk_timeout=0.2)
        self.assertTrue(report.stalled)
        self.assertEqual(speaker.played, [])

    async def test_the_bound_is_never_below_the_floor(self):
        """A caller asking for less than the floor must not weaken the
        protection that stops a mute Sim."""
        speaker = _Speaker()
        player = StreamingPlayer(speaker, stall_timeout_s=0.5)
        report = await player.play_stream(_after(0.2), request_id="r", chunk_timeout=0.01)
        self.assertEqual(len(speaker.played), 1)
        self.assertEqual(report.chunk_timeout_s, 0.5)

    async def test_what_it_waited_is_recorded(self):
        speaker = _Speaker()
        player = StreamingPlayer(speaker, stall_timeout_s=0.05)
        report = await player.play_stream(_after(0.1), request_id="r", chunk_timeout=1.5)
        self.assertEqual(report.chunk_timeout_s, 1.5)


if __name__ == "__main__":
    unittest.main()
