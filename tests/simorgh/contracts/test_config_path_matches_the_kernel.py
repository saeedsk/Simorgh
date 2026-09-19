"""`contracts.settings.config_path()` finds the same simorgh.toml the Kernel
reads, including under SIMORGH_RUNTIME_DATA_DIR (found writing contracts'
CONTRACT.md, 2026-09-19)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts.settings import config_path
from simorgh.kernel.config import find_config_path


class TheSameFileBothWays(unittest.TestCase):
    def test_a_custom_data_dir_is_honoured(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as cwd:
            (Path(data) / "simorgh.toml").write_text("[voice]\n")
            old = os.getcwd()
            os.chdir(cwd)
            try:
                with mock.patch.dict(os.environ, {"SIMORGH_RUNTIME_DATA_DIR": data}, clear=False):
                    os.environ.pop("SIMORGH_CONFIG", None)
                    kernel = find_config_path(None, data_dir=Path(data))
                    ours = config_path()
            finally:
                os.chdir(old)
            self.assertEqual(ours.resolve(), kernel.resolve())
