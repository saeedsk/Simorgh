"""StyleTTS 2: the expressive engine that does not cost a spoken turn.

Suggested by Gemini via the creator, 2026-09-17: "a strong middle ground
... generates audio incredibly fast". Measured on the M3 Pro before any
of this was written, because tonight produced four confident wrong
claims from reasoning instead of measuring:

    load                 5 s     (MisoTTS: 159-229 s)
    cold   5.30 s of audio in 4.69 s  ->  0.89x real time
    warm   2.67 s of audio in 1.12 s  ->  0.42x real time

Against the field measured here -- Kokoro 0.19x, Chatterbox ~1.8x, Miso
~10x -- it is the only expressive-class engine that renders faster than
it speaks.

That single fact decides its wiring, and this file pins the decision:
it is NOT wrapped in the lane pair. Chatterbox and Miso are wrapped
because a spoken turn cannot wait for them and Kokoro takes the turns
beside them. Wrapping a 0.42x engine would relegate it to typed replies,
which is the opposite of the point.

The other thing pinned here is the format. `inference()` returns FLOATS
and writes a float32 WAV; Sim's `Audio` is little-endian int16. A player
handed float samples makes noise or silence while reporting success --
exactly the fault that cost an evening with MisoTTS -- so the server
converts, once, and the conversion is tested rather than assumed.
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from simorgh.voice.tts import styletts2


class TheEngineTestCase(unittest.TestCase):
    def test_it_asks_about_itself_not_about_torch(self):
        """The mistake that let a broken MisoTTS report ready all
        evening: probing a dependency instead of the engine."""
        source = inspect.getsource(styletts2.available)
        self.assertIn('"styletts2"', source)
        self.assertNotIn('"torch"', source)

    def test_it_is_quick_enough_for_the_fast_path(self):
        """Under 1.15 means the player keeps its ordinary floor and none
        of the slow-lane waiting applies."""
        self.assertLess(styletts2.StyleTTS2Synthesiser.nominal_pace, 1.15)

    def test_torch_is_pinned_below_the_weights_only_change(self):
        """torch >= 2.6 defaults `weights_only=True`; the package's own
        checkpoint loader does not pass it and dies on UnpicklingError.
        Measured 2026-09-17 with torch 2.14."""
        self.assertTrue(any(p.startswith("torch==2.5") for p in styletts2.TORCH_PIN))

    def test_the_pin_is_applied_after_the_package(self):
        """Installing them together lets the package's own resolution
        undo the pin -- the same shape as miso's numpy fix."""
        source = inspect.getsource(styletts2.install)
        self.assertLess(source.index("create_venv"), source.index("TORCH_PIN"))


class TheEmotionDialTestCase(unittest.TestCase):
    def test_every_tone_has_an_emotion_scale(self):
        for tone, params in styletts2.TONES.items():
            with self.subTest(tone=tone):
                self.assertIn("embedding_scale", params)
                self.assertIn("diffusion_steps", params)

    def test_a_lively_tone_is_more_emotional_than_a_calm_one(self):
        """`embedding_scale`, in the package's own words: higher means
        more emotional."""
        tones = styletts2.TONES
        self.assertGreater(tones["playful"]["embedding_scale"], tones["calm"]["embedding_scale"])
        self.assertGreater(tones["bright"]["embedding_scale"], tones["serious"]["embedding_scale"])

    def test_an_unknown_tone_falls_back_to_neutral(self):
        engine = styletts2.StyleTTS2Synthesiser.__new__(styletts2.StyleTTS2Synthesiser)
        engine._scale = 0.0  # noqa: SLF001
        self.assertEqual(engine.params_for("exuberant"), styletts2.TONES["neutral"])

    def test_a_fixed_setting_beats_the_tone_table(self):
        engine = styletts2.StyleTTS2Synthesiser.__new__(styletts2.StyleTTS2Synthesiser)
        engine._scale = 2.5  # noqa: SLF001
        self.assertEqual(engine.params_for("calm")["embedding_scale"], 2.5)


class TheWiringTestCase(unittest.TestCase):
    def test_it_is_a_choice_a_person_can_set(self):
        from simorgh.contracts.settings import VOICE_SAFE_KEYS

        self.assertIn("styletts2", VOICE_SAFE_KEYS["tts"][1])

    def test_open_synthesiser_knows_it(self):
        from simorgh.voice.tts import open_synthesiser

        self.assertIn('"styletts2"', inspect.getsource(open_synthesiser))

    def test_it_is_not_relegated_to_the_slow_lane(self):
        """The decision this engine exists to make. Wrapping a 0.42x
        engine in the lane pair would hand spoken turns to Kokoro and
        leave this one answering typed replies only."""
        from simorgh.voice.tts import open_synthesiser

        source = inspect.getsource(open_synthesiser)
        wrapped = source.split("isinstance(primary,")[1].split(")")[0]
        self.assertNotIn("StyleTTS2Synthesiser", wrapped)

    def test_voice_models_can_install_it(self):
        import simorgh.voice.service as service

        self.assertIn("styletts2", inspect.getsource(service.Service._on_models))  # noqa: SLF001

    def test_its_settings_reach_the_config(self):
        from simorgh.voice.config import Config

        self.assertEqual(Config().styletts2_embedding_scale, 0.0)
        self.assertEqual(Config.from_mapping({"styletts2_embedding_scale": 1.4}).styletts2_embedding_scale, 1.4)


class TheServerTestCase(unittest.TestCase):
    """It runs in its own venv, so it is read rather than imported."""

    def setUp(self):
        self.path = Path("simorgh/voice/tts/servers/styletts2_server.py")
        self.source = self.path.read_text()

    def test_it_is_standalone(self):
        """A server that imported simorgh could not run in its own venv."""
        bad = []
        for node in ast.walk(ast.parse(self.source)):
            if isinstance(node, ast.Import):
                bad += [a.name for a in node.names if a.name.startswith("simorgh")]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("simorgh"):
                bad.append(node.module)
        self.assertEqual(bad, [])

    def test_it_writes_sixteen_bit_pcm(self):
        """`inference()` returns floats; `Audio` is int16. Handing float
        samples to the player is silence that reports success."""
        self.assertIn("setsampwidth(2)", self.source)
        self.assertIn("int16", self.source)

    def test_empty_audio_is_an_error_not_a_success(self):
        self.assertIn("returned no audio", self.source)

    def test_it_reports_the_rate_it_writes(self):
        self.assertIn("RATE = 24_000", self.source)


if __name__ == "__main__":
    unittest.main()
