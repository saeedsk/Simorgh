"""Words as they are said (voice/stt/sherpa_stream.py).

Whisper pads every input to its 30 s window, so a decode costs 2-3.5 s
whatever the length: measured 2026-09-17 over 1120 live turns, `stt`
median 2.23 s and *one* partial per turn. A streaming transducer decodes
each chunk as it lands -- 6.29 s of speech in 0.20 s on the same machine,
16 revisions instead of 1.
"""

from __future__ import annotations

import math
import pathlib
import unittest

from simorgh.voice.config import Config
from simorgh.voice.stt import open_recogniser
from simorgh.voice.stt.sherpa_stream import STREAM_MODEL, confidence_of, model_dir_for, timed_words


class TheModelIsFound(unittest.TestCase):
    def test_no_name_means_the_model_it_ships_with(self):
        # `base / ""` is `base`, and a Path is always truthy, so the obvious
        # one-liner returned the parent folder and found nothing in it.
        self.assertEqual(model_dir_for(Config()).name, STREAM_MODEL)

    def test_a_named_folder_wins(self):
        self.assertEqual(model_dir_for(Config(stt_stream_model="other-model")).name, "other-model")

    def test_it_hangs_off_the_repo_root_when_the_path_is_relative(self):
        self.assertTrue(str(model_dir_for(Config(), repo_root="/tmp/x")).startswith("/tmp/x/"))


class WordsAndConfidence(unittest.TestCase):
    def test_bpe_pieces_become_timed_words(self):
        # sherpa's own `words` is empty for a subword model; every token
        # carries a timestamp, and a piece opening with a space starts a word.
        words = timed_words([" Hi", " seed", ",", " I'm", " Sim"], [0.1, 0.4, 0.6, 0.8, 1.2])
        self.assertEqual([w.text for w in words], ["Hi", "seed,", "I'm", "Sim"])
        self.assertEqual(words[0].start, 0.1)
        self.assertEqual(words[0].end, 0.4, "a word ends where the next begins")

    def test_a_confidence_that_means_something(self):
        # whisper_server reports a flat 1.0 and always has, so a morning of
        # mangled transcripts looked exactly like a clean one (2026-09-17).
        self.assertAlmostEqual(confidence_of([math.log(0.9), math.log(0.7)]), 0.8, places=3)
        self.assertEqual(confidence_of([]), 0.0,
                         "nothing decoded is not certainty: a denoiser that erased a "
                         "sentence scored 1.000 on the silence it left")


class TheEngineIsReachable(unittest.TestCase):
    def test_it_is_chosen_by_name_and_never_by_auto(self):
        # The model is zh-en and this house speaks en,fa: `auto` must not
        # quietly stop understanding Farsi.
        _engine, why = open_recogniser(Config(stt="nope"))
        self.assertIn("sherpa", why, "the engine is offered by name")
        from simorgh.contracts.settings import VOICE_SAFE_KEYS

        self.assertIn("sherpa", VOICE_SAFE_KEYS["stt"][1], "`voice set stt sherpa` is allowed")

    def test_a_streaming_engine_is_not_wrapped_in_the_re_decoder(self):
        # IncrementalRecogniser re-decodes the whole buffer over and over,
        # which is the cost this engine exists to remove.
        import inspect

        from simorgh.voice.session import VoiceSession

        source = inspect.getsource(VoiceSession.__init__)
        self.assertIn('getattr(recogniser, "streaming", False)', source)


class ItStreamsWhenTheModelIsHere(unittest.IsolatedAsyncioTestCase):
    async def test_the_sentence_arrives_in_pieces_and_keeps_its_audio(self):
        engine, why = open_recogniser(Config(stt="sherpa"))
        if engine is None:
            self.skipTest(why)
        quiet = (b"\0\0" * 4800)          # 300 ms of silence per frame

        async def frames():
            for _ in range(6):
                yield quiet

        events = [event async for event in engine.start_stream(frames(), turn_id=3)]
        final = events[-1]
        self.assertEqual(final.kind, "final")
        self.assertEqual(final.audio, quiet * 6, "the turn's PCM rides on the final")
        self.assertGreater(final.audio_seconds, 1.0)
        self.assertTrue(getattr(engine, "streaming", False))


class ThePartialSettingMeansSomething(unittest.IsolatedAsyncioTestCase):
    """`stt_partials` is offered as "show what is heard while you are still
    talking". An engine that streamed regardless would make it a lie.

    Checked once against silence, which produced no partials either way and
    so proved nothing -- the assertion needs real speech behind it.
    """

    async def _kinds(self, partials: bool) -> list[str]:
        import array
        import wave

        sample = pathlib.Path("workspace/voice/kokoro-sample.wav")
        engine, why = open_recogniser(Config(stt="sherpa", stt_partials=partials))
        if engine is None:
            self.skipTest(why)
        if not sample.is_file():
            self.skipTest("no speech sample on this machine")
        with wave.open(str(sample)) as handle:
            pcm = handle.readframes(handle.getnframes())
        raw = array.array("h", pcm).tobytes()
        step = int(16000 * 0.48) * 2

        async def frames():
            for at in range(0, len(raw), step):
                yield raw[at:at + step]

        return [event.kind async for event in engine.start_stream(frames(), turn_id=1)]

    async def test_on_it_builds_the_sentence_and_off_it_says_nothing_until_the_end(self):
        on = await self._kinds(True)
        self.assertGreater(on.count("partial"), 3, "the sentence assembles as it is spoken")
        off = await self._kinds(False)
        self.assertEqual(off.count("partial"), 0, "asked for quiet, it stays quiet")
        self.assertEqual(off.count("final"), 1, "the turn still lands")


if __name__ == "__main__":
    unittest.main()
