"""The voice engine Sim was told to use is the one it wakes up with.

The creator, 2026-09-16: "lets enable MisoTTS as one of sim's voice
engine and tell me how to switch to MisoTTs at runtime, sim should store
voice engine selection and automatically keep that setting over
restarts."

Both halves of that are already built, and neither half was pinned. The
existing settings test proves `persist()` writes `tts_speed` and
`barge_in` into the file; nothing proved the ENGINE choice round-trips,
and nothing proved the read side at all. A write path with an untested
read path is the shape most of this codebase's bugs have taken -- a
setting that is stored, documented, and never arrives.

The second rule here is the one that looks like a bug and is not. On the
evening this was asked, `voice set tts miso` left Kokoro running and
`simorgh.toml` unchanged, because the engine could not open (a numpy 2
ABI break in its venv). That is deliberate: `voice/service.py` reopens
the engines on a `tts` change, restores the previous engine if the new
one will not open, and calls `persist()` only after that guard -- so a
broken pick is never written into the file, and the next `voice on` does
not fail on it. A setting that cannot work must not be remembered.
"""

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from simorgh.contracts import settings as contract_settings
from simorgh.voice import settings
from simorgh.voice.config import Config


class TheEngineChoiceRoundTripsTestCase(unittest.TestCase):
    def _restart(self, path: Path) -> Config:
        """What boot does: read the file, build the config from it."""
        return Config.from_mapping(tomllib.loads(path.read_text()).get("voice") or {})

    def test_the_engine_is_written_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simorgh.toml"
            settings.persist(path, "tts", "miso")
            self.assertEqual(self._restart(path).tts, "miso")

    def test_every_engine_survives_the_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simorgh.toml"
            for engine in ("kokoro", "chatterbox", "miso", "piper"):
                with self.subTest(engine=engine):
                    settings.persist(path, "tts", engine)
                    self.assertEqual(self._restart(path).tts, engine)

    def test_the_lane_rule_survives_too(self):
        """Choosing the engine is half of hearing it: with the default
        `auto` lane a spoken turn still goes to the fast engine, so the
        setting that actually changes what the room hears must persist
        as well."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simorgh.toml"
            settings.persist(path, "tts", "miso")
            settings.persist(path, "expressive_lane", "always")
            after = self._restart(path)
            self.assertEqual((after.tts, after.expressive_lane), ("miso", "always"))

    def test_miso_settings_persist_beside_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simorgh.toml"
            settings.persist(path, "miso_device", "mps")
            self.assertEqual(self._restart(path).miso_device, "mps")

    def test_choosing_an_engine_disturbs_no_other_setting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "simorgh.toml"
            path.write_text('[runtime]\ndata_dir = "/x/y"\n\n[voice]\ntts_voice = "af_bella"\n'
                            'speak_replies = true\n\n[interface]\nhttp_host = "0.0.0.0"\n')
            settings.persist(path, "tts", "miso")
            data = tomllib.loads(path.read_text())
        self.assertEqual(data["runtime"]["data_dir"], "/x/y")
        self.assertEqual(data["interface"]["http_host"], "0.0.0.0")
        self.assertEqual(data["voice"]["tts_voice"], "af_bella")
        self.assertTrue(data["voice"]["speak_replies"])
        self.assertEqual(data["voice"]["tts"], "miso")


class TheEngineIsACheckedChoiceTestCase(unittest.TestCase):
    def test_a_real_engine_is_accepted(self):
        for engine in ("kokoro", "chatterbox", "miso", "piper", "say", "auto"):
            with self.subTest(engine=engine):
                value, problem = settings.parse("tts", engine)
                self.assertEqual(problem, "")
                self.assertEqual(value, engine)

    def test_an_engine_that_does_not_exist_is_refused_before_it_is_stored(self):
        """A typo must not be written into the file and then fail every
        boot afterwards."""
        value, problem = settings.parse("tts", "elevenlabs")
        self.assertIsNone(value)
        self.assertIn("one of", problem)

    def test_miso_is_offered_as_a_choice_at_all(self):
        """The creator's ask: Miso must be one of the engines Sim will
        accept, not just a module on disk."""
        self.assertIn("miso", contract_settings.VOICE_SAFE_KEYS["tts"][1])

    def test_the_engine_key_is_a_real_config_field(self):
        from dataclasses import fields

        self.assertIn("tts", {f.name for f in fields(Config)})


if __name__ == "__main__":
    unittest.main()
