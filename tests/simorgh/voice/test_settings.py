"""`voice set` (voice/settings.py): only safe keys, checked values,
persisted without disturbing the rest of the file."""

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from simorgh.voice import settings
from simorgh.voice.config import Config


class TestParse(unittest.TestCase):
    def test_bools_ints_floats_and_choices(self) -> None:
        self.assertEqual(settings.parse("barge_in", "off"), (False, ""))
        self.assertEqual(settings.parse("endpoint_silence_ms", "600"), (600, ""))
        self.assertEqual(settings.parse("tts_speed", "1.1"), (1.1, ""))
        self.assertEqual(settings.parse("vad_sensitivity", "high"), ("high", ""))

    def test_ranges_choices_and_unknown_keys_are_refused(self) -> None:
        self.assertIn("between", settings.parse("tts_speed", "9")[1])
        self.assertIn("one of", settings.parse("vad_sensitivity", "extreme")[1])
        self.assertIn("not a setting", settings.parse("model_dir", "/etc")[1])
        self.assertIn("not a setting", settings.parse("stt_model", "/tmp/x.bin")[1])
        self.assertIn("takes", settings.parse("min_speech_ms", "soon")[1])

    def test_apply_returns_a_new_config(self) -> None:
        config = settings.apply(Config(), "tts_speed", 1.2)
        self.assertEqual(config.tts_speed, 1.2)
        self.assertEqual(Config().tts_speed, 1.0)


class TestPersist(unittest.TestCase):
    def test_writes_the_voice_table_and_keeps_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simorgh.toml"
            path.write_text('[runtime]\ndata_dir = "/x/y"\n\n[voice]\ntts_voice = "af_heart"\n\n[bus]\nbackend = "memory"\n')
            settings.persist(path, "tts_speed", 1.1)
            settings.persist(path, "barge_in", False)
            data = tomllib.loads(path.read_text())
        self.assertEqual(data["runtime"]["data_dir"], "/x/y")
        self.assertEqual(data["bus"]["backend"], "memory")
        self.assertEqual(data["voice"], {"tts_voice": "af_heart", "tts_speed": 1.1, "barge_in": False})

    def test_creates_the_file_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "simorgh.toml"
            settings.persist(path, "stt_language", "fa")
            self.assertEqual(tomllib.loads(path.read_text()), {"voice": {"stt_language": "fa"}})

    def test_every_safe_key_is_a_real_config_field(self) -> None:
        from dataclasses import fields
        names = {f.name for f in fields(Config)}
        for key in settings.SAFE_KEYS:
            self.assertIn(key, names)


if __name__ == "__main__":
    unittest.main()


class NearestKeyTestCase(unittest.TestCase):
    def test_a_misspelt_key_gets_the_nearest_real_one(self):
        from simorgh.voice.settings import parse
        value, problem = parse("ttc_voice", "af_kore")
        self.assertIsNone(value)
        self.assertIn("did you mean tts_voice?", problem)


class OutputSettingTestCase(unittest.TestCase):
    def test_output_takes_laptop_tv_or_both(self):
        from simorgh.voice.settings import parse
        self.assertEqual(parse("output", "tv")[0], "tv")
        self.assertIsNone(parse("output", "radio")[0])
