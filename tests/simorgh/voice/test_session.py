"""The spoken conversation end to end with fakes (voice/session.py):
ten consecutive turns, barge-in, a stale reply dropped, self-echo not
answered, and the diagnostics that come out of it."""

from __future__ import annotations

import asyncio
import unittest

from simorgh.contracts import topics
from simorgh.voice.api import Audio, SAMPLE_RATE, SAMPLE_WIDTH
from simorgh.voice.config import Config
from simorgh.voice.fakes import FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser, silence
from simorgh.voice.pipeline import Pipeline
from simorgh.voice.session import VoiceSession
from simorgh.voice.turns import AGENT_SPEAKING, LISTENING, THINKING, USER_SPEAKING

FRAME = SAMPLE_RATE * 30 // 1000 * SAMPLE_WIDTH


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    def new(self, topic: str, payload: dict):
        return (topic, payload)

    async def publish(self, message) -> None:
        self.published.append(message)

    async def subscribe(self, topic, handler, **kw):
        class _Sub:
            async def unsubscribe(self_inner) -> None:
                pass
        return _Sub()

    def of(self, topic: str) -> list[dict]:
        return [p for t, p in self.published if t == topic]


class _Script:
    """A detector that follows a script of (speech?, frames) runs and
    then reports silence forever; `add` appends more runs live."""

    name = "script"

    def __init__(self, *runs: tuple[bool, int]) -> None:
        self.runs = list(runs)
        self.rms_value = 900.0

    def add(self, *runs: tuple[bool, int]) -> None:
        self.runs.extend(runs)

    def is_speech(self, frame: bytes) -> bool:
        while self.runs and self.runs[0][1] <= 0:
            self.runs.pop(0)
        if not self.runs:
            return False
        speech, left = self.runs[0]
        self.runs[0] = (speech, left - 1)
        return speech

    def rms(self, frame: bytes) -> float:
        return self.rms_value

    def raise_floor(self, rms: float) -> None:
        pass

    def set_ratio(self, ratio: float) -> None:
        pass


class _Replies:
    def __init__(self, replies: list[str], *, delay: float = 0.0) -> None:
        self.replies = replies
        self.delay = delay
        self.asked: list[str] = []

    async def ask(self, text: str, *, session_id=None, speaker_name: str = "", confidence: float = 1.0) -> str:
        self.asked.append(text)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.replies[min(len(self.asked) - 1, len(self.replies) - 1)]


def _config(**kw) -> Config:
    base = dict(stt="fake", tts="fake", endpoint_silence_ms=300, min_speech_ms=150, barge_in_speech_ms=300,
                stt_partials=False, ack_after_ms=0, reply_timeout_s=5.0, keep_transcripts=False)
    base.update(kw)
    return Config(**base)


def _session(config: Config, script: _Script, replies: _Replies, *, speaker=None, recogniser=None,
             mic_delay: float = 0.0005):
    bus = _Bus()
    mic = FakeMicrophone(silence(0.03), frame_delay=mic_delay)
    speaker = speaker or FakeSpeaker()
    stt = recogniser or FakeRecogniser("what time is it", 0.95)
    tts = FakeSynthesiser()
    pipeline = Pipeline(bus=bus, clock=None, logger=None, ledger=None, config=config, microphone=mic, speaker=speaker,
                        recogniser=stt, synthesiser=tts, detector_factory=lambda: script)
    pipeline.ask = replies.ask  # type: ignore[method-assign] -- Sim, in one line
    session = VoiceSession(pipeline=pipeline, config=config, microphone=mic, speaker=speaker, recogniser=stt,
                           synthesiser=tts, detector_factory=lambda: script)
    return session, bus, speaker, tts


async def _run_until(session: VoiceSession, predicate, *, timeout: float = 5.0) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(session.run(stop))
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while not predicate():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError(f"timed out; state={session.state} turns={session.stats.turns}")
            await asyncio.sleep(0.01)
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=3.0)


class TestTenTurns(unittest.IsolatedAsyncioTestCase):
    async def test_ten_consecutive_turns_flow_and_are_measured(self) -> None:
        # 20 frames of speech (600 ms), then 15 of silence (450 ms) -- ten times.
        script = _Script(*[(True, 20), (False, 15)] * 10 + [(False, 10_000)])
        replies = _Replies(["I'll check that now.", "It is three o'clock.", "Yes, that is right."])
        session, bus, speaker, tts = _session(_config(), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 10, timeout=8.0)
        self.assertEqual(session.stats.turns, 10)
        self.assertEqual(len(replies.asked), 10)
        self.assertEqual(session.turns.turn_id, 10)
        self.assertEqual(session.turns.response_id, 10)
        spoken = bus.of(topics.VOICE_SPOKEN)
        self.assertEqual(len(spoken), 10)
        self.assertEqual([p["turn"] for p in spoken], list(range(1, 11)))
        self.assertTrue(all("metrics" in p for p in spoken))
        m = spoken[-1]["metrics"]
        for key in ("stt", "llm", "first_audio", "response", "underruns", "chunks"):
            self.assertIn(key, m)
        # Connectors: sparse, never every turn.
        self.assertLessEqual(sum(1 for p in spoken if p["metrics"]["connector"]), 4)
        # Stopped by the test; before that, every reply handed the floor back.
        self.assertEqual(session.state, "idle")
        self.assertGreaterEqual(sum(1 for _f, to, _w in session.turns.transitions if to == LISTENING), 10)
        self.assertGreaterEqual(len(tts.spoken), 10)

    async def test_partials_are_published_and_the_final_replaces_them(self) -> None:
        class Growing(FakeRecogniser):
            async def transcribe(self, audio: Audio, *, language: str = "") -> object:
                await asyncio.sleep(0.005)
                words = max(1, int(audio.seconds / 0.3))
                from simorgh.voice.api import Utterance
                return Utterance(text=" ".join(["word"] * words), confidence=0.9, seconds=audio.seconds, engine="fake")

        script = _Script((True, 60), (False, 15), (False, 10_000))
        replies = _Replies(["Okay."])
        session, bus, *_ = _session(_config(stt_partials=True, stt_partial_every_ms=300), script, replies,
                                    recogniser=Growing(), mic_delay=0.002)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        transcripts = bus.of(topics.VOICE_TRANSCRIPT)
        partials = [p for p in transcripts if p.get("partial")]
        finals = [p for p in transcripts if not p.get("partial")]
        self.assertGreaterEqual(len(partials), 1)
        self.assertEqual(len(finals), 1)
        self.assertGreaterEqual(len(finals[0]["text"]), len(partials[0]["text"]))


class TestBargeIn(unittest.IsolatedAsyncioTestCase):
    async def test_talking_over_sim_stops_it_promptly_and_starts_the_next_turn(self) -> None:
        class LongSynth(FakeSynthesiser):
            async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
                self.spoken.append(text)
                return silence(3.0)

        speaker = FakeSpeaker(realtime=True)
        script = _Script((True, 20), (False, 15))
        replies = _Replies(["This is a long answer that will take a while to say out loud."])
        session, bus, speaker, tts = _session(_config(), script, replies, speaker=speaker)
        # Swap in the long synthesiser after construction.
        from simorgh.voice.tts.streaming import StreamingSynthesiser
        session._tts = StreamingSynthesiser(LongSynth(), lookahead=1)  # noqa: SLF001
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            for _ in range(500):
                if session.state == AGENT_SPEAKING:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(session.state, AGENT_SPEAKING)
            script.add((True, 40), (False, 15), (False, 10_000))  # a person cuts in for 1.2 s
            t0 = asyncio.get_running_loop().time()
            for _ in range(500):
                if session.stats.interruptions >= 1 and not session._player.playing:  # noqa: SLF001
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(session.stats.interruptions, 1)
            self.assertLess(asyncio.get_running_loop().time() - t0, 2.0)
            self.assertGreaterEqual(speaker.stopped, 1)
            self.assertEqual(session.turns.turn_id, 2)
            self.assertIn(session.state, (USER_SPEAKING, THINKING, AGENT_SPEAKING, LISTENING))
            for _ in range(500):
                if len(replies.asked) >= 2:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(len(replies.asked), 2)  # the interrupting words became the next turn
            spoken = bus.of(topics.VOICE_SPOKEN)
            self.assertTrue(spoken[0]["interrupted"])
            self.assertIn("interruption", spoken[0]["metrics"])
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)

    async def test_no_interruption_when_barge_in_is_off(self) -> None:
        speaker = FakeSpeaker(realtime=True)

        class LongSynth(FakeSynthesiser):
            async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
                return silence(0.6)

        script = _Script((True, 20), (False, 15), (True, 40), (False, 10_000))
        replies = _Replies(["A reply."])
        session, bus, speaker, tts = _session(_config(barge_in=False), script, replies, speaker=speaker)
        from simorgh.voice.tts.streaming import StreamingSynthesiser
        session._tts = StreamingSynthesiser(LongSynth())  # noqa: SLF001
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        self.assertEqual(session.stats.interruptions, 0)
        self.assertEqual(speaker.stopped, 0)


class TestStaleAndEcho(unittest.IsolatedAsyncioTestCase):
    async def test_a_reply_to_a_turn_that_is_over_is_never_spoken(self) -> None:
        # Sim is slow; the person speaks again meanwhile. The first reply
        # must be dropped, the second spoken.
        script = _Script((True, 20), (False, 15), (True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["first answer", "second answer"], delay=0.5)
        session, bus, speaker, tts = _session(_config(), script, replies)
        await _run_until(session, lambda: session.stats.turns >= 1, timeout=8.0)
        await asyncio.sleep(0.05)
        spoken = bus.of(topics.VOICE_SPOKEN)
        self.assertEqual(len(spoken), 1)
        self.assertEqual(spoken[0]["turn"], 2)
        self.assertEqual(spoken[0]["response"], 1)
        self.assertNotIn("first answer", " ".join(tts.spoken))

    async def test_sims_own_words_coming_back_are_not_a_turn(self) -> None:
        script = _Script((True, 20), (False, 15), (True, 20), (False, 15), (False, 10_000))
        replies = _Replies(["the pool is exhausted so every request waits for a free connection"])
        heard = FakeRecogniser("what is wrong", 0.95)
        session, bus, speaker, tts = _session(_config(), script, replies, recogniser=heard)
        stop = asyncio.Event()
        task = asyncio.create_task(session.run(stop))
        try:
            for _ in range(500):
                if session.stats.turns >= 1:
                    break
                await asyncio.sleep(0.01)
            heard.text = "the pool is exhausted so every request waits for a free connection"  # the echo
            await asyncio.sleep(1.5)
            self.assertEqual(len(replies.asked), 1)
            echoes = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("echo")]
            self.assertEqual(len(echoes), 1)
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=3.0)


if __name__ == "__main__":
    unittest.main()
