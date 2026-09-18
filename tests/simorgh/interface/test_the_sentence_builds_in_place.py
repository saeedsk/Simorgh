"""What is being heard is one line, rewritten -- not a new line each time.

The creator, 2026-09-17, after watching it done elsewhere: "I don't like
that sim write and repeate the new detection sentence voice in new lines,
I'd like sim behaves like gemini that they are modifying, updating the
sentence inplace as the user speaks".

Before this, a partial scrolled. It was throttled to one line every few
seconds precisely because thirty near-identical lines were unreadable
(2026-09-13) -- which also meant that with a streaming recogniser, the
revisions the creator wanted to see were the ones being thrown away.
"""

from __future__ import annotations

import io
import types
import unittest
from contextlib import redirect_stdout

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.interface.config import Config
from simorgh.interface.service import Service


class _Footer:
    """A live status line that remembers what it was asked to draw."""

    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.drawn: list[str] = []

    def render(self, text: str) -> None:
        self.drawn.append(text)

    def clear(self) -> None:
        pass

    def restore(self) -> None:
        pass


def _service(footer: _Footer) -> Service:
    service = Service.__new__(Service)
    service.config = Config()
    service._color = False
    service._input_pending = False
    service._last_time_marker = 1e18
    service._live = footer
    service._partial_at = 0.0
    service._partial_turn = None
    service._book = types.SimpleNamespace(on_created=lambda record: None)
    return service


async def _run(service: Service, payload: dict) -> list[str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        await service._on_voice_transcript(
            Message.new(topics.VOICE_TRANSCRIPT, source="voice", payload=payload))
    return buffer.getvalue().splitlines()


class TheSentenceBuildsInPlace(unittest.IsolatedAsyncioTestCase):
    async def test_every_revision_redraws_one_line_and_scrolls_nothing(self):
        footer = _Footer(enabled=True)
        service = _service(footer)
        for said in ("Hi", "Hi seed", "Hi seed, I'm", "Hi seed, I'm Sim"):
            scrolled = await _run(service, {"text": said, "partial": True, "turn": 7, "confidence": 1.0})
            self.assertEqual(scrolled, [], "a revision must not scroll")
        self.assertEqual(len(footer.drawn), 4, "every revision redraws, none is throttled away")
        self.assertIn("Hi seed, I'm Sim", footer.drawn[-1])

    async def test_the_draft_is_forgotten_when_the_turn_settles(self):
        footer = _Footer(enabled=True)
        service = _service(footer)
        await _run(service, {"text": "Hi se", "partial": True, "turn": 7, "confidence": 1.0})
        lines = await _run(service, {"text": "Hi Sim", "speaker": "Saeed", "turn": 7, "confidence": 1.0})
        self.assertEqual(lines, ["🎤 Saeed: Hi Sim"])
        # `clear()` erases the screen but keeps the text, and `_out` restores
        # it after printing -- only render("") makes the footer forget.
        self.assertEqual(footer.drawn[-1], "", "the draft is dropped, not left under the real line")

    async def test_without_a_footer_it_still_scrolls_as_before(self):
        footer = _Footer(enabled=False)
        service = _service(footer)
        scrolled = await _run(service, {"text": "Hi seed", "partial": True, "turn": 7, "confidence": 1.0})
        self.assertTrue(scrolled and "hearing:" in scrolled[0],
                        "a piped or headless run still shows progress")


class TheColourCodesAreNeverCutInHalf(unittest.IsolatedAsyncioTestCase):
    """The creator, live, minutes after the footer landed: "I can see the
    formatting characters".

    `LiveStatus.render` truncates by raw length, which counts escape bytes
    the screen never shows. This was the first caller to hand it *styled*
    text, so a long line was cut mid-sequence: the trailing reset lost, the
    fragments visible. A first fix subtracted a guessed margin of six and
    still produced 106 characters for a 100-column window.
    """

    async def test_a_long_sentence_still_fits_and_keeps_its_reset(self):
        from simorgh.interface import render as render_mod

        footer = _Footer(enabled=True)
        service = _service(footer)
        service._color = True
        width = render_mod.terminal_width()
        await _run(service, {"text": "word " * 400, "partial": True, "turn": 1, "confidence": 1.0})
        drawn = footer.drawn[-1]
        self.assertLess(len(drawn), width, "render() truncates above this, cutting an escape in half")
        self.assertTrue(drawn.endswith("\x1b[0m"), "the colour is closed, so it cannot bleed into the prompt")
        self.assertIn("…", drawn, "the words are trimmed, not the escape codes")

    async def test_a_short_sentence_is_left_whole(self):
        from simorgh.interface import render as render_mod

        footer = _Footer(enabled=True)
        service = _service(footer)
        service._color = True
        await _run(service, {"text": "Hi Sim", "partial": True, "turn": 1, "confidence": 1.0})
        self.assertIn("Hi Sim", footer.drawn[-1])
        self.assertNotIn("…", footer.drawn[-1])
        self.assertLess(len(footer.drawn[-1]), render_mod.terminal_width())


if __name__ == "__main__":
    unittest.main()
