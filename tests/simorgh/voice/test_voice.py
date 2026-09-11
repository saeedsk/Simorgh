"""The voice subsystem, driven end to end on fakes.

Nothing here touches a microphone: the fakes meet the same protocols the
real engines do, which is the only way this pipeline can be tested on a
machine that has no audio -- and the way the design says it must be.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.voice.api import Audio
from simorgh.voice.config import Config
from simorgh.voice.fakes import FakeDetector, FakeMicrophone, FakeRecogniser, FakeSpeaker, FakeSynthesiser, silence
from simorgh.voice.pipeline import NOT_SURE, STILL_THINKING, spoken_form
from simorgh.voice.stt import open_recogniser
from simorgh.voice.tts import open_synthesiser
from simorgh.voice.vad import EnergyDetector, Endpointer, open_detector


class ConfigTestCase(unittest.TestCase):
    def test_every_key_is_reachable_from_the_section(self):
        cfg = Config.from_mapping({"enabled": True, "stt": "fake", "tts": "fake", "endpoint_silence_ms": 300,
                                   "min_confidence": 0.9, "fake_transcript": "turn on the lights"})
        self.assertTrue(cfg.enabled)
        self.assertEqual((cfg.stt, cfg.tts, cfg.endpoint_silence_ms, cfg.min_confidence), ("fake", "fake", 300, 0.9))
        self.assertEqual(cfg.fake_transcript, "turn on the lights")

    def test_unknown_keys_are_ignored_not_fatal(self):
        self.assertEqual(Config.from_mapping({"wyoming_port": 10700}).device, "laptop")


class EngineSelectionTestCase(unittest.TestCase):
    def test_fake_engines_open_without_any_audio_software(self):
        stt, why = open_recogniser(Config(stt="fake", fake_transcript="x"))
        self.assertIsNotNone(stt, why)
        tts, why = open_synthesiser(Config(tts="fake"))
        self.assertIsNotNone(tts, why)

    def test_an_unknown_engine_is_refused_by_name(self):
        stt, why = open_recogniser(Config(stt="cloud-thing"))
        self.assertIsNone(stt)
        self.assertIn("cloud-thing", why)

    def test_a_missing_engine_says_what_to_install(self):
        # faster_whisper is not installed on the test machine (and if it
        # ever is, this still holds for the explicit whisper_cli path with
        # no model).
        stt, why = open_recogniser(Config(stt="faster_whisper"))
        if stt is None:
            self.assertIn("pip install", why)

    def test_the_energy_detector_needs_nothing(self):
        det, note = open_detector("energy")
        self.assertIsInstance(det, EnergyDetector)


class EndpointerTestCase(unittest.TestCase):
    def test_it_never_ends_before_anyone_speaks(self):
        ep = Endpointer(FakeDetector(speech_frames=0), silence_ms=90, max_seconds=100)
        self.assertFalse(any(ep.feed(b"\x00" * 960) for _ in range(50)))

    def test_silence_after_speech_ends_it(self):
        ep = Endpointer(FakeDetector(speech_frames=5), silence_ms=90, max_seconds=100)  # 3 frames of silence
        results = [ep.feed(b"\x00" * 960) for _ in range(8)]
        self.assertTrue(results[-1])
        self.assertEqual(ep.ended_by, "silence")
        self.assertTrue(ep.heard_speech)

    def test_the_hard_cap_ends_it_regardless(self):
        ep = Endpointer(FakeDetector(speech_frames=1000), silence_ms=700, max_seconds=0.3)  # 10 frames
        results = [ep.feed(b"\x00" * 960) for _ in range(10)]
        self.assertTrue(results[-1])
        self.assertEqual(ep.ended_by, "max_seconds")

    def test_the_energy_detector_hears_a_tone_over_silence(self):
        import array, math
        det = EnergyDetector(0.5)
        quiet = array.array("h", [3] * 480).tobytes()
        loud = array.array("h", [int(8000 * math.sin(i / 3)) for i in range(480)]).tobytes()
        for _ in range(5):
            det.is_speech(quiet)
        self.assertFalse(det.is_speech(quiet))
        self.assertTrue(det.is_speech(loud))


class SpokenFormTestCase(unittest.TestCase):
    def test_markdown_does_not_get_read_aloud(self):
        self.assertEqual(spoken_form("**Kitchen** lights are `off`.\n\n- one\n- two"), "Kitchen lights are off.\none\ntwo")

    def test_code_blocks_are_dropped(self):
        self.assertEqual(spoken_form("Run this:\n```\nls -la\n```\nthen tell me."), "Run this:\nthen tell me.")


class PipelineOnAKernelTestCase(unittest.IsolatedAsyncioTestCase):
    """The whole path through a real Kernel: a fake mic hears a fake
    transcript, the words go to Orchestration as `channel=voice`, and
    whatever comes back is spoken through the fake synthesiser."""

    async def _kernel(self, **voice):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kernel = Kernel(LoadedConfig({
            "runtime": {"data_dir": str(Path(tmp.name) / "data")},
            "curiosity": {"autonomy_on_boot": False},
            "voice": {"stt": "fake", "tts": "fake", "microphone": "fake", "speaker": "fake", "vad": "fake",
                      "reply_timeout_s": 20.0, **voice},
        }, None), secrets=EnvSecretStore({}))
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        return kernel

    async def test_voice_status_answers_when_off(self):
        kernel = await self._kernel()
        reply = await kernel.bus.request(kernel.bus.new(topics.VOICE_STATUS_REQUEST, {}), timeout=10)
        self.assertFalse(reply.payload["enabled"])

    async def test_a_spoken_turn_reaches_sim_and_the_answer_is_spoken(self):
        kernel = await self._kernel(fake_transcript="what is two plus two")
        seen: dict[str, list] = {"percept": [], "spoken": [], "transcript": []}

        async def _percept(m):
            seen["percept"].append(m.payload)

        async def _spoken(m):
            seen["spoken"].append(m.payload)

        async def _transcript(m):
            seen["transcript"].append(m.payload)

        await kernel.bus.subscribe(topics.PERCEPT_TEXT_RECEIVED, _percept)
        await kernel.bus.subscribe(topics.VOICE_SPOKEN, _spoken)
        await kernel.bus.subscribe(topics.VOICE_TRANSCRIPT, _transcript)

        reply = await kernel.bus.request(kernel.bus.new(topics.VOICE_LISTEN_REQUEST, {}), timeout=60)
        self.assertTrue(reply.payload["ok"], reply.payload)
        self.assertEqual(reply.payload["heard"], "what is two plus two")
        self.assertTrue(reply.payload.get("said"), "the answer, whatever it was, must have been spoken")
        self.assertEqual(seen["transcript"][0]["text"], "what is two plus two")
        voice_percepts = [p for p in seen["percept"] if p.get("channel") == "voice"]
        self.assertEqual(len(voice_percepts), 1, "one spoken turn is one percept, on the voice channel")
        self.assertEqual(voice_percepts[0]["device"], "laptop")
        self.assertTrue(seen["spoken"] and seen["spoken"][0]["text"] == reply.payload["said"])

    async def test_a_low_confidence_hearing_is_asked_about_not_acted_on(self):
        kernel = await self._kernel(fake_transcript="delete everything", min_confidence=0.99)
        percepts = []

        async def _percept(m):
            percepts.append(m.payload)
        await kernel.bus.subscribe(topics.PERCEPT_TEXT_RECEIVED, _percept)
        # the fake recogniser reports 0.95 -- below the bar set here
        reply = await kernel.bus.request(kernel.bus.new(topics.VOICE_LISTEN_REQUEST, {}), timeout=60)
        self.assertTrue(reply.payload["ok"], reply.payload)
        self.assertEqual(reply.payload["said"], NOT_SURE.format(text="delete everything"))
        self.assertEqual([p for p in percepts if p.get("channel") == "voice"], [], "nothing was asked of Sim")

    async def test_listen_only_transcribes_without_asking(self):
        kernel = await self._kernel(fake_transcript="just a note")
        percepts = []

        async def _percept(m):
            percepts.append(m.payload)
        await kernel.bus.subscribe(topics.PERCEPT_TEXT_RECEIVED, _percept)
        reply = await kernel.bus.request(kernel.bus.new(topics.VOICE_LISTEN_REQUEST, {"respond": False}), timeout=60)
        self.assertEqual(reply.payload["heard"], "just a note")
        self.assertEqual(reply.payload.get("said", ""), "")
        self.assertEqual([p for p in percepts if p.get("channel") == "voice"], [])

    async def test_voice_test_speaks_the_text(self):
        kernel = await self._kernel()
        spoken = []

        async def _spoken(m):
            spoken.append(m.payload["text"])
        await kernel.bus.subscribe(topics.VOICE_SPOKEN, _spoken)
        reply = await kernel.bus.request(kernel.bus.new(topics.VOICE_SPEAK_REQUEST, {"text": "**hello** there"}), timeout=60)
        self.assertTrue(reply.payload["ok"], reply.payload)
        for _ in range(50):
            if spoken:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(spoken, ["hello there"], "markdown is not read aloud")

    async def test_on_then_off_runs_and_stops_the_loop(self):
        kernel = await self._kernel(fake_transcript="")
        on = await kernel.bus.request(kernel.bus.new(topics.VOICE_CONTROL_REQUEST, {"action": "on"}), timeout=60)
        self.assertTrue(on.payload["ok"], on.payload)
        self.assertTrue(on.payload["enabled"])
        off = await kernel.bus.request(kernel.bus.new(topics.VOICE_CONTROL_REQUEST, {"action": "off"}), timeout=60)
        self.assertFalse(off.payload["enabled"])

    async def test_the_probes_reach_the_capabilities_stream(self):
        kernel = await self._kernel()
        events = await kernel.ledger.read("capabilities")
        names = {e.payload.get("name") for e in events}
        self.assertTrue({"speech-to-text", "text-to-speech", "microphone", "audio-playback"} <= names)


if __name__ == "__main__":
    unittest.main()


class SpeakRepliesTestCase(unittest.IsolatedAsyncioTestCase):
    """`[voice] speak_replies`: a reply to a TYPED turn is spoken too --
    the ask the creator gave Sim itself on 2026-09-10, on the one path."""

    async def test_a_typed_turns_reply_is_spoken_when_asked(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kernel = Kernel(LoadedConfig({
            "runtime": {"data_dir": str(Path(tmp.name) / "data")},
            "curiosity": {"autonomy_on_boot": False},
            "voice": {"stt": "fake", "tts": "fake", "microphone": "fake", "speaker": "fake", "vad": "fake",
                      "speak_replies": True},
        }, None), secrets=EnvSecretStore({}))
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        spoken = []

        async def _spoken(m):
            spoken.append(m.payload["text"])
        await kernel.bus.subscribe(topics.VOICE_SPOKEN, _spoken)
        await kernel.bus.publish(kernel.bus.new(topics.TURN_COMPLETED, {"session_id": "typed-1", "task_id": "typed-1", "text": "**Four.**", "floor": False, "tool_steps": 0}))
        for _ in range(100):
            if spoken:
                break
            await asyncio.sleep(0.02)
        self.assertEqual(spoken, ["Four."])

    async def test_off_by_default_nothing_is_spoken_for_typed_turns(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kernel = Kernel(LoadedConfig({
            "runtime": {"data_dir": str(Path(tmp.name) / "data")},
            "curiosity": {"autonomy_on_boot": False},
            "voice": {"stt": "fake", "tts": "fake", "microphone": "fake", "speaker": "fake", "vad": "fake"},
        }, None), secrets=EnvSecretStore({}))
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        spoken = []

        async def _spoken(m):
            spoken.append(m.payload["text"])
        await kernel.bus.subscribe(topics.VOICE_SPOKEN, _spoken)
        await kernel.bus.publish(kernel.bus.new(topics.TURN_COMPLETED, {"session_id": "typed-2", "task_id": "typed-2", "text": "Four.", "floor": False, "tool_steps": 0}))
        await asyncio.sleep(0.3)
        self.assertEqual(spoken, [])


class PlaybackPathOrderTestCase(unittest.TestCase):
    def test_auto_prefers_the_command_player_over_portaudio(self):
        from simorgh.voice import audio as audio_mod

        spk, why = audio_mod.open_speaker("auto")
        if spk is None:
            self.skipTest(why)
        # On a machine with afplay/ffplay it must win even when sounddevice is installed.
        import shutil
        if shutil.which("afplay") or shutil.which("ffplay"):
            self.assertIsInstance(spk, audio_mod.CommandSpeaker)

