"""Audio for somebody else's ears and somebody else's microphone.

The phone has neither Sim's speaker nor Sim's microphone, and until
2026-09-24 it used Apple's engines and sounded like it -- "why the voice
on sim app sounds robotic, I want to have same voice chat experience as I
have on mac with same stt and tts engines" (the creator).

`voice.synthesise.request` makes a WAV and does NOT play it here;
`voice.transcribe.request` reads a WAV recorded elsewhere. Both carry the
audio through the ledger as a blob, the way the TV's speech already does.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
import wave
from pathlib import Path

from simorgh.contracts import topics
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel


class ThePhoneBorrowsSimsEngines(unittest.IsolatedAsyncioTestCase):
    async def _kernel(self, **voice):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        kernel = Kernel(LoadedConfig({
            "runtime": {"data_dir": str(Path(tmp.name) / "data")},
            "growth": {"explore": {"autonomy_on_boot": False}},
            "voice": {"stt": "fake", "tts": "fake", "microphone": "fake", "speaker": "fake", "vad": "fake",
                      "reply_timeout_s": 20.0, **voice},
        }, None), secrets=EnvSecretStore({}))
        await kernel.boot()
        self.addAsyncCleanup(kernel.shutdown)
        return kernel

    async def test_synthesise_returns_a_playable_wav_and_says_nothing_aloud(self):
        kernel = await self._kernel()
        spoken: list[dict] = []
        await kernel.bus.subscribe(topics.VOICE_SPOKEN, lambda m: spoken.append(m.payload))
        reply = await kernel.bus.request(
            kernel.bus.new(topics.VOICE_SYNTHESISE_REQUEST, {"text": "the lights are on"}), timeout=60)
        self.assertTrue(reply.payload.get("ok"), reply.payload)
        ref = reply.payload["ref"]
        data = await kernel.ledger.get_blob(ref)
        with wave.open(__import__("io").BytesIO(data), "rb") as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth()), (1, 2))
            self.assertGreater(w.getnframes(), 0)
        self.assertGreater(reply.payload["seconds"], 0.0)
        # The whole point: the room stayed silent. A phone turn must not
        # make Sim think it is talking here.
        await asyncio.sleep(0.05)
        self.assertEqual(spoken, [], "synthesising for the phone is not speaking in the room")

    async def test_nothing_to_say_is_refused_without_an_engine_call(self):
        kernel = await self._kernel()
        reply = await kernel.bus.request(kernel.bus.new(topics.VOICE_SYNTHESISE_REQUEST, {"text": "   "}), timeout=30)
        self.assertFalse(reply.payload.get("ok", True))
        self.assertIn("nothing to say", reply.payload["detail"])
        self.assertEqual(reply.payload["error"]["code"], "nothing_to_say", "a refusal that passes its own contract")

    async def test_transcribe_reads_audio_recorded_somewhere_else(self):
        kernel = await self._kernel(fake_transcript="turn the kitchen light off")
        made = await kernel.bus.request(
            kernel.bus.new(topics.VOICE_SYNTHESISE_REQUEST, {"text": "turn the kitchen light off"}), timeout=60)
        ref = made.payload["ref"]
        heard = await kernel.bus.request(
            kernel.bus.new(topics.VOICE_TRANSCRIBE_REQUEST, {"ref": ref}), timeout=60)
        self.assertTrue(heard.payload.get("ok"), heard.payload)
        self.assertEqual(heard.payload["text"], "turn the kitchen light off")
        self.assertGreater(heard.payload["seconds"], 0.0)

    async def test_a_ref_that_is_not_there_is_an_answer_not_a_crash(self):
        kernel = await self._kernel()
        reply = await kernel.bus.request(
            kernel.bus.new(topics.VOICE_TRANSCRIBE_REQUEST, {"ref": "sha256:" + "0" * 64}), timeout=30)
        self.assertFalse(reply.payload.get("ok", True))
        self.assertIn("could not read the audio", reply.payload["detail"])
        self.assertEqual(reply.payload["error"]["code"], "engine_failed")


class WavAlreadyInMemory(unittest.TestCase):
    def test_sixteen_kilohertz_mono_is_read_without_ffmpeg(self):
        from simorgh.voice.api import Audio
        from simorgh.voice.audio import read_wav_bytes, wav_bytes

        pcm = b"\x01\x00" * 1600
        self.assertEqual(read_wav_bytes(wav_bytes(Audio(pcm))).pcm, pcm)
