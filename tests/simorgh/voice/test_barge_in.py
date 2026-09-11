"""Sim stops talking the moment a person starts.

The creator, 2026-09-10: "I want sim to stop talking as soon as I
start talking, so basically I can interrupt sim." Design section 4.1.
The microphone stays open while Sim speaks; `barge_in_speech_ms` of a
person's speech, measured over the level the mic hears of Sim's own
voice through the speakers, stops playback and becomes the start of
the next turn.
"""

from __future__ import annotations

import array
import asyncio
import math
import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.voice.api import SAMPLE_RATE, SAMPLE_WIDTH, Audio
from simorgh.voice.config import Config
from simorgh.voice.fakes import FakeDetector, FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser, silence
from simorgh.voice.pipeline import Pipeline
from simorgh.voice.vad import BargeInEndpointer, EnergyDetector


def _tone(seconds: float, amplitude: int = 8000) -> Audio:
    n = int(seconds * SAMPLE_RATE)
    return Audio(array.array("h", [int(amplitude * math.sin(i / 3)) for i in range(n)]).tobytes())


class _Bus:
    def __init__(self):
        self.handlers: dict[str, list] = {}
        self.published: list[Message] = []

    async def subscribe(self, topic, handler, **_):
        self.handlers.setdefault(topic, []).append(handler)

        class _Sub:
            async def unsubscribe(self_inner):
                pass
        return _Sub()

    def new(self, topic, payload):
        return Message.new(topic, source="voice", payload=payload)

    async def publish(self, message):
        self.published.append(message)
        for h in self.handlers.get(message.type, []):
            await h(message)


class _Clock:
    def now(self):
        return 1.0


def _pipeline(*, mic, speaker, stt, config=None):
    return Pipeline(bus=_Bus(), clock=_Clock(), logger=None, ledger=None,
                    config=config or Config(barge_in=True, barge_in_speech_ms=300, endpoint_silence_ms=90,
                                            barge_in_calibrate_ms=150, barge_in_ratio=2.0, reply_timeout_s=1.0),
                    microphone=mic, speaker=speaker, recogniser=stt, synthesiser=FakeSynthesiser(),
                    detector_factory=lambda: FakeDetector(speech_frames=40))


class BargeInEndpointerTestCase(unittest.TestCase):
    def test_the_echo_of_sims_own_voice_does_not_count(self):
        # The first frames are what the mic hears of the speakers; the
        # floor rises to them, and the same level afterwards is silence.
        det = EnergyDetector(0.5)
        ep = BargeInEndpointer(det, silence_ms=90, max_seconds=10, speech_ms=300, calibrate_frames=4, ratio=2.0)
        echo = _tone(0.03, amplitude=3000).pcm
        for _ in range(30):
            self.assertFalse(ep.feed(echo))
        self.assertFalse(ep.barged, "Sim hearing itself is not a person cutting in")

    def test_a_louder_voice_over_the_echo_cuts_in_and_keeps_the_utterance(self):
        det = EnergyDetector(0.5)
        fired = []
        ep = BargeInEndpointer(det, silence_ms=90, max_seconds=10, speech_ms=300, calibrate_frames=4,
                               on_barge_in=lambda: fired.append(True))
        echo, voice, quiet = _tone(0.03, 3000).pcm, _tone(0.03, 20000).pcm, silence(0.03).pcm
        for _ in range(6):
            ep.feed(echo)
        for _ in range(12):  # 360 ms of a person
            ended = ep.feed(voice)
        self.assertEqual(fired, [True], "fires once, at the threshold")
        self.assertTrue(ep.barged)
        self.assertFalse(ended, "the utterance is still going")
        for _ in range(4):
            ended = ep.feed(quiet)
        self.assertTrue(ended, "and ends at silence like any utterance")
        self.assertEqual(ep.ended_by, "silence")


class InterruptingSimTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_speech_during_playback_stops_the_speaker(self):
        speaker = FakeSpeaker(realtime=True)
        # A quiet second (the level gate learns Sim's echo as "quiet"), then
        # 0.8 s of a loud voice, frames arriving 5 ms apart while a 3 s reply
        # plays. The fake voice detector calls every post-calibration frame
        # a voice; the level gate needs it louder than the echo -- both.
        mic = FakeMicrophone(Audio(silence(1.0).pcm + _tone(0.8, 20000).pcm), frame_delay=0.005)
        pipe = _pipeline(mic=mic, speaker=speaker, stt=FakeRecogniser("wait, stop"))
        long_reply = "x" * 60  # the fake synthesiser makes 3 s of audio for this
        started = asyncio.get_running_loop().time()
        said = await pipe.speak(long_reply)
        elapsed = asyncio.get_running_loop().time() - started
        self.assertEqual(speaker.stopped, 1, "the speaker was told to stop")
        self.assertLess(elapsed, 2.0, f"playback ended early, not after the full 3 s ({elapsed:.2f}s)")
        self.assertIsNotNone(pipe.pending_audio, "the interrupting words are kept for the next turn")
        spoken = [m.payload for m in pipe._bus.published if m.type == topics.VOICE_SPOKEN]  # noqa: SLF001
        self.assertTrue(spoken and spoken[-1]["interrupted"] is True)

    async def test_the_interruption_becomes_the_next_turn(self):
        speaker = FakeSpeaker(realtime=True)
        mic = FakeMicrophone(Audio(silence(1.0).pcm + _tone(0.8, 20000).pcm), frame_delay=0.005)
        stt = FakeRecogniser("actually never mind")
        pipe = _pipeline(mic=mic, speaker=speaker, stt=stt)
        await pipe.speak("x" * 60)
        pending = pipe.pending_audio
        self.assertIsNotNone(pending)
        utterance, _ = await pipe.listen_once(pending=pending, respond=False)
        self.assertEqual(utterance.text, "actually never mind")
        self.assertEqual(mic.captures, 1, "the pending audio stood in for a fresh capture")

    async def test_silence_during_playback_does_not_interrupt(self):
        speaker = FakeSpeaker(realtime=True)
        mic = FakeMicrophone(silence(3.0), frame_delay=0.005)
        pipe = Pipeline(bus=_Bus(), clock=_Clock(), logger=None, ledger=None,
                        config=Config(barge_in=True, barge_in_speech_ms=300, endpoint_silence_ms=90),
                        microphone=mic, speaker=speaker, recogniser=FakeRecogniser(""),
                        synthesiser=FakeSynthesiser(), detector_factory=lambda: FakeDetector(speech_frames=0))
        await pipe.speak("x" * 10)  # 0.5 s
        self.assertEqual(speaker.stopped, 0)
        self.assertIsNone(pipe.pending_audio)

    async def test_barge_in_off_plays_to_the_end(self):
        speaker = FakeSpeaker(realtime=True)
        mic = FakeMicrophone(silence(1.8), frame_delay=0.005)
        pipe = _pipeline(mic=mic, speaker=speaker, stt=FakeRecogniser("stop"),
                         config=Config(barge_in=False))
        await pipe.speak("x" * 10)
        self.assertEqual(speaker.stopped, 0)
        self.assertEqual(mic.captures, 0, "the mic is not opened while Sim speaks")


if __name__ == "__main__":
    unittest.main()


class EchoByContentTestCase(unittest.TestCase):
    def test_sims_own_reply_coming_back_is_an_echo(self):
        from simorgh.voice.pipeline import is_echo
        said = ("Got it -- you're pointing me at the benchmark. What I have on record: four astropy cases "
                "have all ended in timeouts so far.")
        heard = "Got it, you're pointing me at the benchmark. What I have on record, four Astropie cases have all ended in timeout so far."
        self.assertTrue(is_echo(heard, said))

    def test_a_real_reply_that_shares_a_few_words_is_not(self):
        from simorgh.voice.pipeline import is_echo
        self.assertFalse(is_echo("run the benchmark on the astropy case again please", "four astropy cases timed out"))

    def test_short_utterances_are_never_called_echoes(self):
        from simorgh.voice.pipeline import is_echo
        self.assertFalse(is_echo("yes", "yes, that is right, yes"))


class EchoIsNotATurnTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_heard_echo_of_the_last_reply_is_dropped_before_sim_sees_it(self):
        said_text = "the kitchen lights are on and the door is locked for the night"
        stt = FakeRecogniser("the kitchen lights are on and the door is locked for the night")
        pipe = _pipeline(mic=FakeMicrophone(silence(1.0)), speaker=FakeSpeaker(), stt=stt,
                         config=Config(barge_in=False, reply_timeout_s=0.2))
        pipe.last_said = said_text
        utterance, said = await pipe.listen_once()
        self.assertEqual(said, "", "nothing was spoken in reply")
        percepts = [m for m in pipe._bus.published if m.type == topics.PERCEPT_TEXT_RECEIVED]  # noqa: SLF001
        self.assertEqual(percepts, [], "Sim was never asked")
        transcripts = [m.payload for m in pipe._bus.published if m.type == topics.VOICE_TRANSCRIPT]  # noqa: SLF001
        self.assertTrue(transcripts and transcripts[-1].get("echo") is True)


class WhisperAnnotationsTestCase(unittest.TestCase):
    def test_blank_audio_is_no_words(self):
        from simorgh.voice.stt.whisper_cli import clean_transcript
        self.assertEqual(clean_transcript("[BLANK_AUDIO]"), "")
        self.assertEqual(clean_transcript(" (silence) "), "")
        self.assertEqual(clean_transcript("[MUSIC] hello there [inaudible]"), "hello there")
        self.assertEqual(clean_transcript("*laughs* okay"), "okay")

    def test_real_words_with_brackets_survive(self):
        from simorgh.voice.stt.whisper_cli import clean_transcript
        self.assertEqual(clean_transcript("call foo (the old one) now"), "call foo (the old one) now",
                         "a parenthetical a person spoke is not an annotation")


class _Voice:
    """A stand-in voice detector: says 'voice' for the frames it is told to."""
    name = "voice"

    def __init__(self, answers):
        self._answers = list(answers)

    def is_speech(self, frame):
        return self._answers.pop(0) if self._answers else False


class CompositeDetectorTestCase(unittest.TestCase):
    """Typing, clapping, a chair: loud but not a voice. Sim's own voice
    through the speakers: a voice but not louder than the echo floor.
    Only a voice that is also louder than Sim is a person cutting in."""

    def test_loud_noise_that_is_not_a_voice_is_not_speech(self):
        from simorgh.voice.vad import CompositeDetector
        level = EnergyDetector(0.5)
        for _ in range(5):
            level.is_speech(silence(0.03).pcm)  # learn a quiet floor
        det = CompositeDetector(_Voice([False] * 10), level)
        self.assertFalse(any(det.is_speech(_tone(0.03, 20000).pcm) for _ in range(5)), "a clap is loud, not a voice")

    def test_a_voice_no_louder_than_the_echo_is_not_speech(self):
        from simorgh.voice.vad import CompositeDetector
        level = EnergyDetector(0.5)
        det = CompositeDetector(_Voice([True] * 10), level)
        det.raise_floor(EnergyDetector.rms(_tone(0.03, 8000).pcm))  # what the mic hears of Sim
        self.assertFalse(det.is_speech(_tone(0.03, 8000).pcm), "Sim's own voice at its own level")

    def test_a_louder_voice_is_speech(self):
        from simorgh.voice.vad import CompositeDetector
        level = EnergyDetector(0.5)
        det = CompositeDetector(_Voice([True] * 10), level)
        det.raise_floor(EnergyDetector.rms(_tone(0.03, 3000).pcm))
        self.assertTrue(det.is_speech(_tone(0.03, 20000).pcm))

    def test_barge_in_uses_the_composite_when_the_detector_is_a_voice_detector(self):
        from simorgh.voice import pipeline as pipeline_mod
        import inspect
        self.assertIn("CompositeDetector(", inspect.getsource(pipeline_mod.Pipeline._play_interruptibly))


class SileroSmokeTestCase(unittest.TestCase):
    def test_silero_tells_a_voice_from_a_tone_when_installed(self):
        try:
            from simorgh.voice.vad import SileroDetector
            det = SileroDetector(0.5)
        except ImportError as exc:
            self.skipTest(str(exc))
        # a pure tone is not a voice
        flags = [det.is_speech(_tone(0.03, 8000).pcm) for _ in range(20)]
        self.assertLessEqual(sum(flags), 2)


class EchoFloorTracksTheWholeReplyTestCase(unittest.TestCase):
    """A reply that swells -- quiet open, loud middle -- must not
    interrupt itself. The floor follows Sim's loudest moment, so its own
    later syllables never clear the bar (creator, 2026-09-11)."""

    def test_a_swelling_reply_never_barges_on_itself(self):
        from simorgh.voice.vad import BargeInEndpointer, CompositeDetector, EnergyDetector

        fired = []
        voiced_always = _Voice([True] * 10000)
        det = CompositeDetector(voiced_always, EnergyDetector(0.5))
        ep = BargeInEndpointer(det, silence_ms=300, max_seconds=100, speech_ms=650,
                               calibrate_frames=10, ratio=2.8, on_barge_in=lambda: fired.append(True))
        # quiet opening, then a long loud swell -- all Sim's own voice
        for _ in range(10):
            ep.feed(_tone(0.03, 1500).pcm)
        for amp in range(2000, 16000, 500):       # rising loudness
            for _ in range(4):
                ep.feed(_tone(0.03, amp).pcm)
        self.assertEqual(fired, [], "Sim's own swell must never register as a person")

    def test_a_person_still_clears_the_tracked_floor(self):
        from simorgh.voice.vad import BargeInEndpointer, CompositeDetector, EnergyDetector

        fired = []
        det = CompositeDetector(_Voice([True] * 10000), EnergyDetector(0.5))
        ep = BargeInEndpointer(det, silence_ms=300, max_seconds=100, speech_ms=300,
                               calibrate_frames=10, ratio=2.8, on_barge_in=lambda: fired.append(True))
        for _ in range(10):
            ep.feed(_tone(0.03, 2000).pcm)          # Sim's loudest echo ~2000
        for _ in range(15):
            ep.feed(_tone(0.03, 20000).pcm)         # a person, well above 2000*2.8
        self.assertEqual(fired, [True])


class BargeToggleTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_barge_off_then_on_flips_the_live_config(self):
        import tempfile
        from pathlib import Path
        from simorgh.contracts import topics
        from simorgh.kernel.config import LoadedConfig
        from simorgh.kernel.secrets import EnvSecretStore
        from simorgh.kernel.service import Kernel

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kernel = Kernel(LoadedConfig({
            "runtime": {"data_dir": str(Path(tmp.name) / "data")},
            "curiosity": {"autonomy_on_boot": False},
            "voice": {"stt": "fake", "tts": "fake", "microphone": "fake", "speaker": "fake", "vad": "fake"},
        }, None), secrets=EnvSecretStore({}))
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        svc = kernel._supervisor.services["voice"].service  # noqa: SLF001
        off = await kernel.bus.request(kernel.bus.new(topics.VOICE_CONTROL_REQUEST, {"action": "barge_off"}), timeout=10)
        self.assertIn("barge-in off", off.payload["detail"])
        self.assertFalse(svc.config.barge_in)
        on = await kernel.bus.request(kernel.bus.new(topics.VOICE_CONTROL_REQUEST, {"action": "barge_on"}), timeout=10)
        self.assertIn("barge-in on", on.payload["detail"])
        self.assertTrue(svc.config.barge_in)


class BargeInWithAecTestCase(unittest.IsolatedAsyncioTestCase):
    """The whole loop with AEC on: a reply plays, its echo comes back
    through the mic, and only when a person is added does barge fire."""

    async def _run(self, add_person: bool):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy required")
        from simorgh.voice.api import SAMPLE_RATE

        frame = SAMPLE_RATE * 30 // 1000
        rng = np.random.default_rng(7)
        path = np.zeros(200, dtype=np.float32); path[40], path[70] = 0.8, 0.3
        n = 80  # frames of reply
        ref = (rng.standard_normal(n * frame).astype(np.float32) * 0.3)
        mic = np.convolve(ref, path)[: n * frame].copy()
        if add_person:
            mic[50 * frame:] += rng.standard_normal(len(mic) - 50 * frame).astype(np.float32) * 0.3
        reply = Audio((np.clip(ref, -1, 1) * 32767).astype(np.int16).tobytes())
        mic_audio = Audio((np.clip(mic, -1, 1) * 32767).astype(np.int16).tobytes())

        speaker = FakeSpeaker(realtime=True)
        pipe = Pipeline(bus=_Bus(), clock=_Clock(), logger=None, ledger=None,
                        config=Config(barge_in=True, aec=True, aec_taps=512, aec_mu=0.5,
                                      aec_residual_threshold=0.05, barge_in_speech_ms=300,
                                      barge_in_calibrate_ms=300, endpoint_silence_ms=300),
                        microphone=FakeMicrophone(mic_audio, frame_delay=0.0),
                        speaker=speaker, recogniser=FakeRecogniser("stop"), synthesiser=FakeSynthesiser(),
                        detector_factory=lambda: _Voice([True] * 100000))
        return await pipe._play_interruptibly(reply)

    async def test_echo_alone_does_not_barge(self):
        self.assertFalse(await self._run(add_person=False))

    async def test_a_person_over_the_echo_barges(self):
        self.assertTrue(await self._run(add_person=True))

