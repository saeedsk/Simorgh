"""One reply, one voice (2026-10-05).

The creator: "sim farsi voice changes mid conversation, I heard two
different Farsi voices, one with calm tone, the other excited". Measured:
every sentence was its own ElevenLabs request, and each request is a fresh
reading -- an exclamation came out ~100 Hz above the verse after it. After
the first sentence, what is already written now goes as one request; and a
long request gets the time it needs instead of falling back to Mana."""

from __future__ import annotations

import asyncio
import types
import unittest

from simorgh.voice.tts import elevenlabs
from simorgh.voice.tts.streaming import JOIN_CHARS, _pieces_of


async def _collect(items, *, fixed=()):
    live: asyncio.Queue = asyncio.Queue()
    for item in items:
        live.put_nowait(item)
    request = types.SimpleNamespace(pieces=list(fixed), live=live)
    return [p async for p in _pieces_of(request)]


class SentencesAlreadyWrittenGoTogether(unittest.TestCase):
    def test_the_first_goes_alone_and_the_rest_together(self):
        got = asyncio.run(_collect([("One!", 100), ("Two.", 120), ("Three.", 140), None]))
        self.assertEqual([(t, last) for _s, t, _p, last in got], [("One!", False), ("Two. Three.", False), ("", True)])
        self.assertEqual(got[1][2], 140, "the run keeps its last sentence's pause")

    def test_a_run_stops_growing_at_the_cap(self):
        long = "x" * (JOIN_CHARS - 3) + "."
        got = asyncio.run(_collect([("a.", 0), (long, 0), ("b.", 0), ("c.", 0), None]))
        texts = [t for _s, t, _p, _l in got]
        self.assertEqual(texts[1], f"{long} b.")
        self.assertEqual(texts[2], "c.")

    def test_nothing_waits_for_a_sentence_not_yet_written(self):
        async def main():
            live: asyncio.Queue = asyncio.Queue()
            live.put_nowait(("one.", 0))
            live.put_nowait(("two.", 0))
            gen = _pieces_of(types.SimpleNamespace(pieces=[], live=live))
            first = await gen.__anext__()
            second = await asyncio.wait_for(gen.__anext__(), 1.0)   # does not wait for "three."
            await gen.aclose()
            return first[1], second[1]

        self.assertEqual(asyncio.run(main()), ("one.", "two."))


class LongRequestsGetTheirTime(unittest.TestCase):
    def test_the_timeout_grows_with_the_text(self):
        synth = elevenlabs.ElevenLabsSynthesiser(
            types.SimpleNamespace(tts_elevenlabs_voice="GSj19hKjOQsPFCZlq1le", tts_elevenlabs_timeout_s=6.0),
            key=lambda: "k", fallback=None)
        self.assertEqual(synth._timeout(""), 6.0)                       # noqa: SLF001
        self.assertAlmostEqual(synth._timeout("x" * 300), 6.0 + 4.5)    # noqa: SLF001

    def test_a_fallback_is_logged(self):
        class _Fallback:
            name = "mana"

            async def synthesise(self, text, **kw):
                return "audio"

        synth = elevenlabs.ElevenLabsSynthesiser(
            types.SimpleNamespace(tts_elevenlabs_voice="GSj19hKjOQsPFCZlq1le", tts_elevenlabs_timeout_s=1.0,
                                  tts_elevenlabs_model="eleven_v4_turbo", tts_elevenlabs_language="fa"),
            key=lambda: None, fallback=_Fallback())
        with self.assertLogs("simorgh.voice", "WARNING") as logs:
            self.assertEqual(asyncio.run(synth.synthesise("سلام")), "audio")
        self.assertIn("voice.tts_fallback", logs.output[0])


if __name__ == "__main__":
    unittest.main()
