"""whisper.cpp models: which file is opened, and how one is fetched.

Homebrew ships `for-tests-ggml-tiny.bin`, a fixture that reads every
audio file as silence -- measured on the JFK sample it ships beside it
(2026-09-10). A lookup that fell through to it, silently, made
`voice listen` transcribe nothing on a fresh Mac. And `base.en` is a
bare model NAME: `Path.suffix` called `.en` a suffix, so the freshly
downloaded `ggml-base.en.bin` was never looked for.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.voice.stt import whisper_cli


class FindModelTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.models = Path(self._tmp.name)

    def test_a_bare_name_with_a_dot_finds_its_ggml_file(self):
        (self.models / "ggml-base.en.bin").write_bytes(b"x" * 10)
        self.assertEqual(whisper_cli.find_model("base.en", self.models), self.models / "ggml-base.en.bin")

    def test_a_file_name_is_taken_as_one(self):
        (self.models / "custom.bin").write_bytes(b"x")
        self.assertEqual(whisper_cli.find_model("custom.bin", self.models), self.models / "custom.bin")

    def test_a_downloaded_model_beats_the_test_fixture_whatever_the_name(self):
        (self.models / "ggml-base.en.bin").write_bytes(b"x" * 10)
        with mock.patch.object(whisper_cli, "_BREW_SHARES", (self.models / "brew",)):
            (self.models / "brew").mkdir()
            (self.models / "brew" / whisper_cli._TEST_MODEL).write_bytes(b"fixture")
            found = whisper_cli.find_model("large-v3-turbo", self.models)
        self.assertEqual(found, self.models / "ggml-base.en.bin")

    def test_nothing_anywhere_is_none(self):
        with mock.patch.object(whisper_cli, "_BREW_SHARES", ()):
            self.assertIsNone(whisper_cli.find_model("base.en", self.models))


class DownloadModelTestCase(unittest.TestCase):
    def test_an_unknown_name_is_refused_with_the_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, problem = whisper_cli.download_model("gpt-4", Path(tmp))
        self.assertIsNone(path)
        self.assertIn("base.en", problem)

    def test_a_model_already_present_is_not_fetched_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ggml-base.en.bin"
            target.write_bytes(b"x" * 2_000_000)
            with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network call expected")):
                path, problem = whisper_cli.download_model("base.en", Path(tmp))
        self.assertEqual(path, target)
        self.assertEqual(problem, "")

    def test_a_failed_fetch_leaves_no_half_model_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            import urllib.error
            with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
                path, problem = whisper_cli.download_model("base.en", Path(tmp))
            self.assertIsNone(path)
            self.assertIn("offline", problem)
            self.assertEqual(list(Path(tmp).iterdir()), [], "no .part, no partial .bin")


if __name__ == "__main__":
    unittest.main()
