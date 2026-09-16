"""The voice match score, on the line it belongs to.

The creator, 2026-09-15: "why are you not showing the score on the screen,
the voice recognition score?" Every turn carried one and it only ever
reached the debug log."""

from __future__ import annotations

import io
import types
import unittest
from contextlib import redirect_stdout

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.interface.config import Config
from simorgh.interface.service import Service


def _service(config: Config) -> Service:
    service = Service.__new__(Service)
    service.config = config
    service._color = False
    service._input_pending = False
    service._last_time_marker = 1e18          # no time marker in the way
    service._live = types.SimpleNamespace(clear=lambda: None, restore=lambda: None)
    return service


async def _lines(service: Service, payload: dict) -> list[str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        await service._on_voice_transcript(Message.new(topics.VOICE_TRANSCRIPT, source="voice", payload=payload))
    return buffer.getvalue().splitlines()


class ScoreOnScreen(unittest.IsolatedAsyncioTestCase):
    async def test_a_placed_voice_shows_its_score(self):
        service = _service(Config(show_speaker_score=True))
        lines = await _lines(service, {"text": "hello", "speaker": "Saeed", "speaker_score": 0.6234,
                                       "confidence": 1.0, "turn": 1})
        self.assertEqual(lines, ["🎤 Saeed: hello  (0.62)"])

    async def test_off_prints_the_line_as_before(self):
        service = _service(Config(show_speaker_score=False))
        lines = await _lines(service, {"text": "hello", "speaker": "Saeed", "speaker_score": 0.6234,
                                       "confidence": 1.0, "turn": 1})
        self.assertEqual(lines, ["🎤 Saeed: hello"])

    async def test_a_voice_it_cannot_place_says_why_on_its_own_line(self):
        service = _service(Config(show_speaker_score=True))
        lines = await _lines(service, {"text": "hello", "speaker": "", "speaker_score": 0.44, "confidence": 1.0,
                                       "speaker_note": "closest is Saeed at 0.44, under the threshold 0.50",
                                       "turn": 1})
        self.assertEqual(lines[0], "🎤 you: hello", "no bare number for a voice with no name")
        self.assertIn("closest is Saeed at 0.44", lines[1])


if __name__ == "__main__":
    unittest.main()
