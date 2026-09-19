"""At a terminal, log lines go to a file, not under the TUI (2026-09-19:
INFO lines on stderr scrambled the prompt and the breathing line)."""

import logging
import logging.handlers
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.kernel import cli
from simorgh.kernel.config import LoadedConfig


class LogsStayOffTheTui(unittest.TestCase):
    def _handler(self, tty: bool, tmp: str):
        config = LoadedConfig({"runtime": {"data_dir": tmp}}, None)
        with mock.patch.object(cli.sys.stderr, "isatty", return_value=tty):
            return cli._log_handler(config)

    def test_at_a_terminal_the_log_is_a_file_under_the_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = self._handler(True, tmp)
            try:
                self.assertIsInstance(handler, logging.handlers.RotatingFileHandler)
                self.assertEqual(Path(handler.baseFilename).resolve(), (Path(tmp) / "logs" / "sim.log").resolve())
            finally:
                handler.close()

    def test_without_one_it_is_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            handler = self._handler(False, tmp)
            self.assertIsInstance(handler, logging.StreamHandler)
            self.assertNotIsInstance(handler, logging.FileHandler)
