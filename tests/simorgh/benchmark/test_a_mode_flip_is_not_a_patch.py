"""The second live SWE-bench run scored astropy-14995 with a 1,110-file
patch: `old mode 100644 / new mode 100755` for every file in the tree,
the one real hunk buried past the 4,000 characters the record keeps.
The image checks its tree out 755 against an index of 644; `git add -A`
on the host then records an executable bit on every file, and every
diff after that carries it (2026-09-10). The dataset's own eval script
runs `git -c core.fileMode=false diff` for exactly this reason.

Three readers of that checkout diff, one rule each: the scored patch
(`swebench.diff_of`), the patch carried into the test container
(`execution.tools._checkout_patch`), and what the verifier treats as
changed (`contracts.checkout.changed_sources`).
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.benchmark.swebench import diff_of
from simorgh.contracts.checkout import ContainerCheckout, changed_sources
from simorgh.execution.tools import _checkout_patch


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True)


class ModeFlipTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.checkout = Path(self._tmp.name) / "co"
        (self.checkout / "pkg").mkdir(parents=True)
        (self.checkout / "pkg" / "mod.py").write_text("X = 1\n")
        (self.checkout / "README").write_text("hi\n")
        _git(self.checkout, "init", "-q")
        _git(self.checkout, "config", "core.fileMode", "true")
        _git(self.checkout, "add", "-A")
        _git(self.checkout, "commit", "-qm", "base")
        self.base = _git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        ContainerCheckout(image="img:1", platform="linux/amd64", workdir="/testbed",
                          base_commit=self.base, setup="", test_command="pytest").write(self.checkout)
        # What `docker cp` of the image's tree looks like on the host.
        for path in (self.checkout / "pkg" / "mod.py", self.checkout / "README"):
            os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def test_the_scored_patch_is_empty(self):
        patch, problem = diff_of(self.checkout, base=self.base)
        self.assertEqual(problem, "")
        self.assertEqual(patch, "")

    def test_the_patch_carried_into_the_container_is_empty(self):
        patch, problem = _checkout_patch(self.checkout, self.base)
        self.assertEqual(problem, "")
        self.assertEqual(patch, "")

    def test_nothing_counts_as_changed(self):
        self.assertEqual(changed_sources(self.checkout, self.base), ())

    def test_an_executable_file_keeps_its_bit(self):
        """The other direction, measured against the real django image:
        `tests/runtests.py` is 100755 in the index and 755 on disk, and a
        diff read through an EMPTY private index re-added it as 100644 --
        so the patch carried into the container stripped its executable
        bit and every run died `Permission denied` (2026-09-10)."""
        script = self.checkout / "run.py"
        script.write_text("#!/usr/bin/env python\n")
        os.chmod(script, 0o755)
        _git(self.checkout, "add", "run.py")
        _git(self.checkout, "commit", "-qm", "an executable")
        base = _git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        for reader in (lambda: diff_of(self.checkout, base=base), lambda: _checkout_patch(self.checkout, base)):
            patch, problem = reader()
            self.assertEqual(problem, "")
            self.assertNotIn("run.py", patch, "a file that was executable in the index must not lose its bit")

    def test_a_real_edit_still_shows_and_only_it(self):
        (self.checkout / "pkg" / "mod.py").write_text("X = 2\n")
        patch, _ = diff_of(self.checkout, base=self.base)
        self.assertIn("+X = 2", patch)
        self.assertNotIn("new mode", patch)
        self.assertNotIn("README", patch)
        self.assertEqual(changed_sources(self.checkout, self.base), ("pkg/mod.py",))


if __name__ == "__main__":
    unittest.main()
