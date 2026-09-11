"""A sandbox's Sim must keep its data in the sandbox, whoever boots it.

On 2026-09-10 an observer's claim-race experiment booted stores with no
data dir of their own and wrote 325 synthetic tasks into the creator's
LIVE ledger. The instruction to export `SIMORGH_RUNTIME_DATA_DIR` was in
the brief; a brief is one forgotten line from this. A `simorgh.toml` in
the sandbox is what every boot path reads first.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from observer_wave import pin_data_dir  # noqa: E402

from simorgh.kernel.config import _read_toml, find_config_path, load_runtime_config  # noqa: E402


class PinDataDirTestCase(unittest.TestCase):
    def test_a_kernel_booted_in_the_sandbox_lands_in_the_sandbox(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            repo = workspace / "repo"
            repo.mkdir()
            pin_data_dir(repo, workspace / "data")
            before = os.getcwd()
            os.chdir(repo)
            try:
                path = find_config_path(None)
                self.assertIsNotNone(path)
                runtime = load_runtime_config(_read_toml(path).get("runtime"))
            finally:
                os.chdir(before)
            self.assertEqual(runtime.data_dir.resolve(), (workspace / "data").resolve())
            self.assertNotEqual(runtime.data_dir.expanduser(), Path("~/.simorgh").expanduser())


if __name__ == "__main__":
    unittest.main()
