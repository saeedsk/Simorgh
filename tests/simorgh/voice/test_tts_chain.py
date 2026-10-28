"""`FirstThatSpeaks`: the local engines under ElevenLabs, tried at speak time.

Live 2026-10-27: ElevenLabs ran out of credits, its fallback StyleTTS2
opened fine and then raised on every reply (a macOS update broke its
venv's scipy), and Sim went silent with Kokoro working on disk.
"""

import asyncio
import unittest

from simorgh.voice.api import Audio
from simorgh.voice.tts import CHAIN_RETRY_S, FirstThatSpeaks


class _Engine:
    def __init__(self, name, *, fails=False, tone=True):
        self.name, self.fails, self.calls = name, fails, []
        if not tone:
            self.synthesise = self._no_tone  # type: ignore[method-assign]

    async def synthesise(self, text, *, voice="", speed=1.0, tone=""):
        self.calls.append((text, voice, tone))
        if self.fails:
            raise ImportError("dlopen: scipy _spropack")
        return Audio(pcm=b"\x00\x01" * 10, sample_rate=24000)

    async def _no_tone(self, text, *, voice="", speed=1.0):
        self.calls.append((text, voice, None))
        return Audio(pcm=b"\x00\x01" * 10, sample_rate=24000)


class FirstThatSpeaksTestCase(unittest.TestCase):
    def setUp(self):
        self.now = 0.0

    def chain(self, *engines):
        return FirstThatSpeaks([(e.name, (lambda e=e: e)) for e in engines], clock=lambda: self.now)

    def test_a_broken_first_engine_hands_the_reply_to_the_next(self):
        broken, kokoro = _Engine("styletts2", fails=True), _Engine("kokoro")
        chain = self.chain(broken, kokoro)
        audio = asyncio.run(chain.synthesise("hello", voice="ndcUYGFbbd96WXiZVVaQ", tone="warm"))
        self.assertTrue(audio.pcm)
        self.assertEqual(chain.last_engine, "kokoro")
        self.assertEqual(kokoro.calls, [("hello", "", "warm")], "the next engine is not handed the cloud voice id")

    def test_a_failed_engine_is_skipped_until_the_retry_window_passes(self):
        broken, kokoro = _Engine("styletts2", fails=True), _Engine("kokoro")
        chain = self.chain(broken, kokoro)
        asyncio.run(chain.synthesise("one"))
        asyncio.run(chain.synthesise("two"))
        self.assertEqual(len(broken.calls), 1, "not paid again on the next sentence")
        self.now = CHAIN_RETRY_S + 1
        broken.fails = False
        asyncio.run(chain.synthesise("three"))
        self.assertEqual(chain.last_engine, "styletts2", "a fixed engine is back after the window")

    def test_an_engine_that_takes_no_tone_is_not_given_one(self):
        say = _Engine("say", tone=False)
        asyncio.run(self.chain(_Engine("styletts2", fails=True), say).synthesise("hi", tone="bright"))
        self.assertEqual(say.calls, [("hi", "", None)])

    def test_when_every_engine_fails_the_last_error_is_raised(self):
        chain = self.chain(_Engine("a", fails=True), _Engine("b", fails=True))
        with self.assertRaises(ImportError):
            asyncio.run(chain.synthesise("hi"))

    def test_an_engine_that_cannot_open_is_skipped(self):
        def cannot():
            raise ImportError("kokoro-onnx is not installed")

        say = _Engine("say")
        chain = FirstThatSpeaks([("kokoro", cannot), ("say", lambda: say)], clock=lambda: 0.0)
        asyncio.run(chain.synthesise("hi"))
        self.assertEqual(chain.last_engine, "say")


if __name__ == "__main__":
    unittest.main()
