"""`persist`: changing one setting must not lose the others.

There was no test here, which is how a two-level TOML writer survived in
a file that holds three-level tables. `persist` rewrites the whole file
to change one key, so anything the writer cannot express is destroyed by
an unrelated setting change.
"""

from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path

from simorgh.contracts.settings import persist

NESTED = """\
[voice]
tts = "chatterbox"

[execution]
secrets = ["vault:*", "SIM_API_TOKEN"]

[cognition.providers.ollama]
model = "qwen3:4b-instruct"
only_purposes = ["chat"]
num_ctx = 8192
timeout_seconds = 60.0
vision_model = "qwen2.5vl:3b"
"""


class PersistKeepsTheRest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "simorgh.toml"
        self.path.write_text(NESTED, encoding="utf-8")
        self.addCleanup(self._tmp.cleanup)

    def _reread(self) -> dict:
        with self.path.open("rb") as handle:
            return tomllib.load(handle)

    def test_a_three_level_table_survives_an_unrelated_setting(self):
        """The creator's cameras went blind twice this way: a `voice set`
        rewrote `[cognition.providers.ollama]` as a quoted Python dict,
        the provider vanished from the order, and nothing could look at a
        picture."""
        persist(self.path, "tts_voice", "af_bella")
        ollama = self._reread()["cognition"]["providers"]["ollama"]
        self.assertIsInstance(ollama, dict, f"the table became {type(ollama).__name__}")
        self.assertEqual(ollama["model"], "qwen3:4b-instruct")
        self.assertEqual(ollama["vision_model"], "qwen2.5vl:3b")
        self.assertEqual(ollama["num_ctx"], 8192)
        self.assertEqual(ollama["only_purposes"], ["chat"])

    def test_the_setting_it_was_asked_to_write_is_written(self):
        persist(self.path, "tts_voice", "af_bella")
        self.assertEqual(self._reread()["voice"]["tts_voice"], "af_bella")
        self.assertEqual(self._reread()["voice"]["tts"], "chatterbox", "and the neighbours stay")

    def test_lists_and_other_sections_are_kept(self):
        persist(self.path, "cast_device", "Family Room TV", section="execution")
        data = self._reread()
        self.assertEqual(data["execution"]["secrets"], ["vault:*", "SIM_API_TOKEN"])
        self.assertEqual(data["execution"]["cast_device"], "Family Room TV")

    def test_types_come_back_as_themselves(self):
        persist(self.path, "speak_replies", True)
        persist(self.path, "barge_in_speech_ms", 350)
        data = self._reread()["voice"]
        self.assertIs(data["speak_replies"], True)
        self.assertEqual(data["barge_in_speech_ms"], 350)
        self.assertEqual(self._reread()["cognition"]["providers"]["ollama"]["timeout_seconds"], 60.0)

    def test_persisting_into_a_file_that_does_not_exist_yet(self):
        fresh = self.path.parent / "new.toml"
        persist(fresh, "tts", "kokoro")
        with fresh.open("rb") as handle:
            self.assertEqual(tomllib.load(handle)["voice"]["tts"], "kokoro")

    def test_repeated_writes_do_not_drift(self):
        for voice in ("a", "b", "c"):
            persist(self.path, "tts_voice", voice)
        data = self._reread()
        self.assertEqual(data["voice"]["tts_voice"], "c")
        self.assertEqual(data["cognition"]["providers"]["ollama"]["vision_model"], "qwen2.5vl:3b")


if __name__ == "__main__":
    unittest.main()
