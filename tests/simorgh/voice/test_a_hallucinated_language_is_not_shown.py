"""Whisper's foreign hallucinations never reach the screen.

Near-silence makes Whisper invent a sentence AND name a language for it.
One evening, 2026-09-22: Turkish ("Simse değil mi?"), Russian, Portuguese
("Obrigado."), and a Japanese "はい" that printed under `/tasks` and had
the creator asking what the weird task was.

The FINAL transcript was already dropped by `_other_language`. The
PARTIAL was published before that check, so it reached the screen -- and
the console log, where `console_tail` can hand Sim its own hallucination
back as something a person said.
"""

import asyncio
import unittest
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.voice.api import Utterance

from tests.simorgh.voice.test_session import _Script, _config
from tests.simorgh.voice.test_speaker_session import _Embedder, _Replies, _session
from simorgh.voice.speakers import SpeakerBook


class _Event:
    """What a streaming recogniser yields."""

    def __init__(self, kind, text, language):
        self.kind, self.text, self.language = kind, text, language
        self.confidence, self.audio_seconds, self.engine = 0.9, 1.0, "fake"


class AHallucinatedLanguageIsNotShown(unittest.IsolatedAsyncioTestCase):
    def _make(self):
        import tempfile
        from pathlib import Path

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        book = SpeakerBook(Path(tmp.name) / "sp", household=())
        return _session(_config(), _Script((False, 10)), _Replies(), _Embedder(), book)

    async def test_the_house_speaks_english_and_farsi_only(self):
        session, _bus, _tts = self._make()
        for code in ("ja", "tr", "ru", "pt", "az", "hy"):
            self.assertEqual(session._other_language(code), code, code)   # noqa: SLF001
        for code in ("en", "fa", "", "auto"):
            self.assertEqual(session._other_language(code), "", code)     # noqa: SLF001

    async def test_a_foreign_partial_is_never_published(self):
        session, bus, _tts = self._make()

        async def _stream(frames, *, turn_id=0, language=""):
            for event in (_Event("partial", "はい", "ja"), _Event("final", "はい", "ja")):
                yield event

        session._stt.start_stream = _stream                               # noqa: SLF001
        queue: asyncio.Queue = asyncio.Queue()
        await session._transcribe(1, queue)                               # noqa: SLF001

        partials = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("partial")]
        self.assertEqual(partials, [], "a language this house does not speak is heard as nothing")
        self.assertEqual(session.partial, "", "and nothing is left on the live line")

    async def test_an_english_partial_still_shows(self):
        session, bus, _tts = self._make()

        async def _stream(frames, *, turn_id=0, language=""):
            yield _Event("partial", "turn off the kitchen lights", "en")

        session._stt.start_stream = _stream                               # noqa: SLF001
        await session._transcribe(1, asyncio.Queue())                     # noqa: SLF001
        partials = [p for p in bus.of(topics.VOICE_TRANSCRIPT) if p.get("partial")]
        self.assertEqual([p["text"] for p in partials], ["turn off the kitchen lights"])


if __name__ == "__main__":
    unittest.main()
