"""The verifier's two trees must agree on what exists (2026-09-22).

The base run is a `git archive`, which has the tracked
`workspace/README.md`. The changed-tree copies (`run_tests`' isolated
run and landing gate, and the verifier's quiet re-run) dropped the whole
`workspace/` since 2026-09-20. Two tests that need the directory then
passed at base and failed "because of" every change, and every patch
task that ran the whole suite was blocked -- trial round 1 fell to 4/7.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from simorgh.execution.tools import isolated_copy_ignore
from simorgh.verification.checks._baseline import _copy_ignore


class BothCopies(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.root = self.tmp / "repo"
        (self.root / "workspace" / "voice" / "models").mkdir(parents=True)
        (self.root / "workspace" / "README.md").write_text("scratch\n")
        (self.root / "workspace" / "voice" / "models" / "big.onnx").write_bytes(b"x" * 1024)
        (self.root / "simorgh").mkdir()
        (self.root / "simorgh" / "a.py").write_text("A = 1\n")

    def _copy(self, ignore, name):
        dest = self.tmp / name
        shutil.copytree(self.root, dest, ignore=ignore(self.root))
        return dest

    def test_the_directory_and_its_readme_are_kept_and_nothing_else_of_it(self):
        for ignore, name in ((isolated_copy_ignore, "run_tests"), (_copy_ignore, "rerun")):
            with self.subTest(copy=name):
                dest = self._copy(ignore, name)
                self.assertTrue((dest / "workspace").is_dir())
                self.assertTrue((dest / "workspace" / "README.md").is_file())
                self.assertFalse((dest / "workspace" / "voice").exists(), "the gigabytes came along")
                self.assertTrue((dest / "simorgh" / "a.py").is_file())


if __name__ == "__main__":
    unittest.main()
