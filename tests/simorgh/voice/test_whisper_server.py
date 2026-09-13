"""whisper.cpp kept loaded (voice/stt/whisper_server.py) against a
stand-in server: it starts on first use on a free port, answers, is
cleaned of annotations, carries the language, restarts once, closes."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from simorgh.voice.api import Audio
from simorgh.voice.config import Config
from simorgh.voice.stt import open_recogniser
from simorgh.voice.stt.whisper_server import WhisperServerRecogniser

FIXTURE = Path(__file__).parent / "fixtures" / "fake_whisper_server.py"


class WhisperServerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        models = Path(self.tmp.name) / "models"
        models.mkdir()
        (models / "ggml-base.en.bin").write_bytes(b"\0" * 16)
        self.config = Config(stt="whisper_server", stt_model="base.en", model_dir=str(models))

    def tearDown(self):
        self.tmp.cleanup()

    def _engine(self, *extra):
        return WhisperServerRecogniser(self.config, command=[sys.executable, str(FIXTURE), *extra])

    async def test_it_starts_once_answers_and_cleans_the_words(self):
        eng = self._engine()
        try:
            self.assertFalse(eng.running)
            heard = await eng.transcribe(Audio(b"\0\0" * 16000, 16000))
            self.assertEqual(heard.text, "Hello there.")
            self.assertEqual(heard.engine, "whisper_server:base.en")
            self.assertAlmostEqual(heard.seconds, 1.0)
            self.assertTrue(eng.running)
            pid = eng._proc.pid
            farsi = await eng.transcribe(Audio(b"\0\0" * 1600, 16000), language="fa")
            self.assertEqual(farsi.text, "salam", "the language travels with the request")
            self.assertEqual(eng._proc.pid, pid, "one server for every turn")
        finally:
            await eng.close()
        self.assertFalse(eng.running)

    async def test_a_server_that_never_listens_is_an_error_not_a_hang(self):
        from simorgh.voice.stt import whisper_server

        eng = self._engine("--die")
        whisper_server.READY_TIMEOUT_S, saved = 3.0, whisper_server.READY_TIMEOUT_S
        try:
            with self.assertRaises(RuntimeError):
                await eng.transcribe(Audio(b"\0\0" * 1600, 16000))
            self.assertTrue(eng.problems, "the first failure is recorded as a restart")
        finally:
            whisper_server.READY_TIMEOUT_S = saved
            await eng.close()

    def test_auto_prefers_the_server_to_the_cli_when_both_are_installed(self):
        import shutil

        if not (shutil.which("whisper-server") and shutil.which("whisper-cli")):
            self.skipTest("whisper.cpp is not installed here")
        eng, why = open_recogniser(Config(stt="auto", stt_model="base.en", model_dir=self.config.model_dir))
        self.assertEqual(why, "")
        self.assertIsInstance(eng, WhisperServerRecogniser)

    def test_a_missing_binary_is_refused_by_name(self):
        import shutil
        from unittest import mock

        with mock.patch.object(shutil, "which", return_value=None):
            with self.assertRaises(ImportError) as caught:
                WhisperServerRecogniser(self.config)
        self.assertIn("whisper-server", str(caught.exception))
