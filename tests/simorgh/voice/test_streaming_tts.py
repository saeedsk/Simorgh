"""Streaming synthesis (voice/tts/streaming.py) and interruptible
streaming playback (voice/playback.py): chunks in order with their
pauses, a bounded lookahead, prompt cancellation, stale audio never
played, levels that do not jump."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.voice.api import Audio, AudioChunk, TtsRequest
from simorgh.voice.fakes import FakeSpeaker, FakeSynthesiser
from simorgh.voice.playback import StreamingPlayer
from simorgh.voice.tts.streaming import StreamingSynthesiser, levelled


class _SlowSynth(FakeSynthesiser):
    def __init__(self, delay: float = 0.0, amplitude: int = 3000) -> None:
        super().__init__()
        self.delay = delay
        self.amplitude = amplitude
        self.calls = 0

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
        self.calls += 1
        self.spoken.append(text)
        if self.delay:
            await asyncio.sleep(self.delay)
        n = max(160, len(text) * 40)
        sample = self.amplitude.to_bytes(2, "little", signed=True)
        return Audio(pcm=sample * n, sample_rate=16_000)


def _request(*texts: str, request_id: str = "r1", pause: int = 100) -> TtsRequest:
    return TtsRequest(request_id=request_id, pieces=tuple((t, pause) for t in texts))


class TestStreamingSynthesiser(unittest.IsolatedAsyncioTestCase):
    async def test_chunks_arrive_in_order_with_pauses_and_the_last_is_final(self) -> None:
        synth = StreamingSynthesiser(_SlowSynth(), level=False)
        chunks = [c async for c in synth.synthesise_stream(_request("One.", "Two.", "Three."))]
        self.assertEqual([c.seq for c in chunks], [0, 1, 2])
        self.assertEqual([c.text for c in chunks], ["One.", "Two.", "Three."])
        self.assertEqual([c.final for c in chunks], [False, False, True])
        pause_bytes = int(16_000 * 0.1) * 2
        self.assertTrue(chunks[0].pcm.endswith(b"\x00" * pause_bytes))
        self.assertFalse(chunks[2].pcm.endswith(b"\x00" * pause_bytes))  # no pause after the last

    async def test_cancel_stops_further_synthesis(self) -> None:
        inner = _SlowSynth(delay=0.05)
        synth = StreamingSynthesiser(inner, level=False)
        got = []
        async for c in synth.synthesise_stream(_request("A.", "B.", "C.", "D.", "E.")):
            got.append(c.seq)
            if c.seq == 1:
                await synth.cancel("r1")
        self.assertEqual(got, [0, 1])
        self.assertLessEqual(inner.calls, 4)  # at most the lookahead ran ahead

    async def test_lookahead_is_bounded(self) -> None:
        inner = _SlowSynth()
        synth = StreamingSynthesiser(inner, lookahead=1, level=False)
        stream = synth.synthesise_stream(_request(*[f"P{i}." for i in range(8)]))
        first = await stream.__anext__()
        await asyncio.sleep(0.05)
        self.assertEqual(first.seq, 0)
        self.assertLessEqual(inner.calls, 3)  # one yielded, one queued, at most one in flight
        await stream.aclose()

    async def test_levels_are_matched_between_pieces(self) -> None:
        # Within the gain range the leveller allows (0.5x to 3x): the
        # clamp exists so a near-silent piece is not boosted into hiss.
        quiet = _SlowSynth(amplitude=1500)
        loud = _SlowSynth(amplitude=6000)
        q = [c async for c in StreamingSynthesiser(quiet).synthesise_stream(_request("Quiet piece here.", pause=0))][0]
        l = [c async for c in StreamingSynthesiser(loud).synthesise_stream(_request("Loud piece here.", pause=0))][0]
        from simorgh.voice.tts.streaming import _rms
        self.assertLess(abs(_rms(q.pcm) - _rms(l.pcm)) / max(_rms(l.pcm), 1), 0.35)

    async def test_warmup_runs_once(self) -> None:
        inner = _SlowSynth()
        synth = StreamingSynthesiser(inner)
        first = await synth.warmup()
        second = await synth.warmup()
        self.assertGreaterEqual(first, 0.0)
        self.assertEqual(second, 0.0)
        self.assertEqual(inner.calls, 1)
        self.assertTrue(synth.warm)

    def test_levelling_leaves_silence_alone_and_never_clips(self) -> None:
        self.assertEqual(levelled(b"\x00" * 3200), b"\x00" * 3200)
        hot = (30000).to_bytes(2, "little", signed=True) * 1600
        out = levelled(hot)
        import numpy as np
        self.assertLessEqual(int(np.abs(np.frombuffer(out, dtype=np.int16)).max()), 32000)


async def _stream(chunks, delay: float = 0.0):
    for c in chunks:
        if delay:
            await asyncio.sleep(delay)
        yield c


def _chunk(seq: int, request_id: str = "r1", seconds: float = 0.05, final: bool = False) -> AudioChunk:
    return AudioChunk(pcm=b"\x01\x00" * int(16_000 * seconds), sample_rate=16_000, request_id=request_id, seq=seq,
                      final=final)


class TestStreamingPlayer(unittest.IsolatedAsyncioTestCase):
    async def test_ready_chunks_are_joined_and_played_gaplessly(self) -> None:
        speaker = FakeSpeaker()
        player = StreamingPlayer(speaker)
        report = await player.play_stream(_stream([_chunk(0), _chunk(1), _chunk(2, final=True)]), request_id="r1")
        self.assertEqual(report.chunks, 3)
        self.assertGreaterEqual(report.first_audio_s, 0.0)
        self.assertFalse(report.interrupted)
        self.assertEqual(report.underruns, 0)
        self.assertLessEqual(len(speaker.played), 3)
        self.assertEqual([s.state for s in report.states][0], "started")
        self.assertEqual([s.state for s in report.states][-1], "finished")

    async def test_a_late_chunk_is_an_underrun_not_a_loss(self) -> None:
        speaker = FakeSpeaker()
        player = StreamingPlayer(speaker)
        report = await player.play_stream(_stream([_chunk(0), _chunk(1), _chunk(2, final=True)], delay=0.03),
                                          request_id="r1")
        self.assertEqual(report.chunks, 3)
        self.assertGreaterEqual(report.underruns, 1)

    async def test_stop_cuts_playback_and_drops_the_rest(self) -> None:
        speaker = FakeSpeaker(realtime=True)
        player = StreamingPlayer(speaker)
        chunks = [_chunk(i, seconds=0.5) for i in range(6)]

        async def _feed():
            for c in chunks:
                await asyncio.sleep(0.01)
                yield c

        task = asyncio.create_task(player.play_stream(_feed(), request_id="r1"))
        await asyncio.sleep(0.15)
        started = asyncio.get_running_loop().time()
        await player.stop()
        report = await task
        self.assertLess(asyncio.get_running_loop().time() - started, 0.15)
        self.assertTrue(report.interrupted)
        self.assertLess(report.chunks, 6)
        self.assertEqual(report.states[-1].state, "stopped")
        self.assertGreaterEqual(speaker.stopped, 1)

    async def test_stale_chunks_from_an_old_response_never_play(self) -> None:
        speaker = FakeSpeaker()
        player = StreamingPlayer(speaker)
        report = await player.play_stream(
            _stream([_chunk(0, "old"), _chunk(0, "r2"), _chunk(1, "old"), _chunk(1, "r2", final=True)]), request_id="r2")
        self.assertEqual(report.chunks, 2)
        self.assertEqual(report.dropped_stale, 2)

    async def test_first_audio_callback_and_chunk_callback(self) -> None:
        seen = []
        player = StreamingPlayer(FakeSpeaker())
        await player.play_stream(_stream([_chunk(0), _chunk(1, final=True)]), request_id="r1",
                                 on_first_audio=lambda s: seen.append(("first", s >= 0)),
                                 on_chunk=lambda c: seen.append(("chunk", c.seq)))
        self.assertEqual(seen[0], ("first", True))
        self.assertIn(("chunk", 1), seen)


if __name__ == "__main__":
    unittest.main()
