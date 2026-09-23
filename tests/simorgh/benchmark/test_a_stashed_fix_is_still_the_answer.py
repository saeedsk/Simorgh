"""Work the model stashed is still the patch.

Live, 2026-09-22, astropy-13236: ten steps, a real six-line fix in
`astropy/table/table.py`, then

    run_shell: Saved working directory and index state WIP on main

The model stashed its own change -- to compare against a clean tree,
most likely -- never restored it, and the case scored "the system
produced no patch". This is the same failure as the committed-work one
`diff_of` already handles, in the one other place git can hold a change.

Real git, not a fake: the whole bug was about where git actually keeps
things.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import pytest

from simorgh.benchmark.swebench import diff_of

pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git is not installed")


def _git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                          check=True, stdin=subprocess.DEVNULL).stdout


class AStashedFixIsStillTheAnswer(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "mod.py").write_text("def f():\n    return 1\n")
        (self.repo / "test_mod.py").write_text("def test_f():\n    assert True\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        self.base = _git(self.repo, "rev-parse", "HEAD").strip()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_stashed_change_is_read_as_the_patch(self):
        (self.repo / "mod.py").write_text("def f():\n    return 2\n")
        _git(self.repo, "stash")
        self.assertEqual((self.repo / "mod.py").read_text(), "def f():\n    return 1\n",
                         "the fix really is out of the tree")
        patch, problem = diff_of(self.repo, base=self.base)
        self.assertEqual(problem, "")
        self.assertIn("mod.py", patch)
        self.assertIn("return 2", patch)

    def test_a_stashed_test_edit_is_still_not_the_answer(self):
        (self.repo / "test_mod.py").write_text("def test_f():\n    assert False\n")
        _git(self.repo, "stash")
        patch, _ = diff_of(self.repo, base=self.base)
        self.assertEqual(patch.strip(), "", "editing the tests is not fixing the bug, stashed or not")

    def test_a_change_in_the_tree_still_wins(self):
        (self.repo / "mod.py").write_text("def f():\n    return 3\n")
        _git(self.repo, "stash")
        (self.repo / "mod.py").write_text("def f():\n    return 4\n")
        patch, _ = diff_of(self.repo, base=self.base)
        self.assertIn("return 4", patch)
        self.assertNotIn("return 3", patch, "the stash is a fallback, not a second opinion")

    def test_no_stash_and_no_change_is_still_no_patch(self):
        patch, problem = diff_of(self.repo, base=self.base)
        self.assertEqual((patch.strip(), problem), ("", ""))


if __name__ == "__main__":
    unittest.main()
