"""ElevenLabs as the Farsi voice, with Mana speaking whenever it cannot.

The creator, 2026-10-04: "go ahead and implement eleven ai live voice tts
integration". No real request is made here: a fake opener stands in for
the API."""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import time
import unittest
import urllib.error

from simorgh.voice.api import Audio
from simorgh.voice.config import Config
from simorgh.voice.tts.elevenlabs import ElevenLabsSynthesiser


class _Mana:
    name = "mana"

    def __init__(self):
        self.spoke: list = []

    async def synthesise(self, text, **_kw):
        self.spoke.append(text)
        return Audio(pcm=b"\x01\x00" * 10, sample_rate=22050)


class _Api:
    def __init__(self, *, fail: int = 0, slow: float = 0.0, voices=None):
        self.calls: list = []
        self._fail, self._slow, self._voices = fail, slow, voices

    def __call__(self, request, timeout=None):
        self.calls.append((request.get_method(), request.full_url, request.get_header("Xi-api-key"),
                           json.loads(request.data) if request.data else None))
        if self._slow:
            time.sleep(self._slow)
        if self._fail:
            raise urllib.error.HTTPError(request.full_url, self._fail, "no", {}, io.BytesIO(b'{"detail":"quota"}'))
        if "/v1/voices" in request.full_url:
            body = json.dumps({"voices": self._voices or []}).encode()
        elif "/v1/shared-voices" in request.full_url:
            body = json.dumps({"voices": [{"name": "Roya - Warm Tehrani Narrator", "voice_id": "roya123"}]}).encode()
        else:
            body = b"\x10\x00" * 2400
        return io.BytesIO(body)


def _engine(api, *, key="sk-test", **cfg):
    config = dataclasses.replace(Config(), **cfg)
    mana = _Mana()
    return ElevenLabsSynthesiser(config, key=lambda: key, fallback=mana, opener=api), mana


class ElevenLabsVoice(unittest.TestCase):
    def test_a_reply_is_spoken_by_elevenlabs_as_24khz_pcm(self):
        api = _Api()
        engine, mana = _engine(api, tts_elevenlabs_voice="abcdefghijklmnopqrstu")
        audio = asyncio.run(engine.synthesise("سلام سعید"))
        self.assertEqual((audio.sample_rate, len(audio.pcm), mana.spoke), (24000, 4800, []))
        method, url, key, body = api.calls[-1]
        self.assertEqual((method, key), ("POST", "sk-test"))
        self.assertIn("/v1/text-to-speech/abcdefghijklmnopqrstu?output_format=pcm_24000", url)
        self.assertEqual(body, {"text": "سلام سعید", "model_id": "eleven_v3", "language_code": "fa"})

    def test_a_voice_name_is_found_in_the_shared_library(self):
        api = _Api()
        engine, _ = _engine(api, tts_elevenlabs_voice="Roya")
        asyncio.run(engine.synthesise("سلام"))
        self.assertIn("/v1/text-to-speech/roya123", api.calls[-1][1])

    def test_no_key_means_mana_speaks_and_says_why(self):
        engine, mana = _engine(_Api(), key=None)
        audio = asyncio.run(engine.synthesise("سلام"))
        self.assertEqual((audio.sample_rate, mana.spoke), (22050, ["سلام"]))
        self.assertIn("ELEVENLABS_API_KEY", engine.problems[-1])

    def test_an_api_error_means_mana_speaks(self):
        engine, mana = _engine(_Api(fail=429), tts_elevenlabs_voice="abcdefghijklmnopqrstu")
        asyncio.run(engine.synthesise("سلام"))
        self.assertEqual(mana.spoke, ["سلام"])
        self.assertIn("HTTP 429", engine.problems[-1])

    def test_a_slow_reply_is_not_waited_for(self):
        engine, mana = _engine(_Api(slow=2.0), tts_elevenlabs_voice="abcdefghijklmnopqrstu",
                               tts_elevenlabs_timeout_s=0.2)
        async def timed():
            started = time.monotonic()
            await engine.synthesise("سلام")
            return time.monotonic() - started   # the thread left behind is not the caller's wait
        self.assertLess(asyncio.run(timed()), 1.8)
        self.assertEqual(mana.spoke, ["سلام"])


if __name__ == "__main__":
    unittest.main()


class EnglishToo(unittest.TestCase):
    """The creator, 2026-10-04: "how can I use farsi and english voice chat
    with sim where it uses eleven_v4?" -- `tts = "elevenlabs"`."""

    def test_the_primary_is_elevenlabs_over_the_local_voice(self):
        from unittest import mock

        from simorgh.voice import tts as tts_mod

        class _Local:
            name = "styletts2"

            def __init__(self, *a, **kw):
                pass

        with mock.patch("simorgh.voice.tts.styletts2.StyleTTS2Synthesiser", _Local):
            engine, _why = tts_mod.open_synthesiser(dataclasses.replace(Config(), tts="elevenlabs",
                                                                        tts_by_language=False))
        cloud = engine._primary                                   # noqa: SLF001
        self.assertIsInstance(cloud, ElevenLabsSynthesiser)
        self.assertEqual(cloud._config.tts_elevenlabs_language, "")   # noqa: SLF001 -- English: no "fa" pinned
        self.assertEqual(cloud._fallback.name, "styletts2")        # noqa: SLF001


class TheToneIsHeard(unittest.TestCase):
    """2026-10-04: every tone tag made an audible difference, in Farideh's
    Farsi and Alexandra's English."""

    def test_a_warm_reply_goes_out_with_its_tag(self):
        api = _Api()
        engine, _ = _engine(api, tts_elevenlabs_voice="abcdefghijklmnopqrstu", tts_elevenlabs_model="eleven_v4_turbo")
        asyncio.run(engine.synthesise("عزیزم، نگران نباش.", tone="warm"))
        self.assertEqual(api.calls[-1][3]["text"], "[warmly] عزیزم، نگران نباش.")

    def test_neutral_and_older_models_get_no_tag(self):
        from simorgh.voice.tts.elevenlabs import tagged

        self.assertEqual(tagged("Hi.", "neutral", "eleven_v4_turbo"), "Hi.")
        self.assertEqual(tagged("Hi.", "warm", "eleven_multilingual_v2"), "Hi.", "it would say 'warmly' aloud")
        self.assertEqual(tagged("Hi.", "sorry", "eleven_v3"), "[apologetically] Hi.")
