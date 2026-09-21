"""The kill drill counts commits where a task actually makes them.

A code task works in a git worktree (`execution/worktree.py`) and only
`worktree_land` moves the lab's own HEAD. The drill counted
`rev-list HEAD` in the lab root alone, so the first real run reported
`git_commit_steps_ok: 1, commits: 0` and it took reading three files
to be sure that was the landing gate doing its job rather than a tool
claiming an effect it never had (2026-09-20).

Confusing is the smaller half. The drill exists to catch an
irreversible action REPEATED after a resume, and a commit repeated
inside a worktree was not being counted at all.
"""

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "tools" / "kill_resume_trial.py"
_spec = importlib.util.spec_from_file_location("kill_resume_trial", _PATH)
drill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drill)


def _repo(where: str) -> None:
    run = lambda *a: subprocess.run(["git", "-C", where, *a], capture_output=True, text=True)
    run("init", "-q")
    Path(where, "a.txt").write_text("x")
    run("add", "-A")
    run("-c", "user.email=a@b", "-c", "user.name=A", "commit", "-qm", "baseline")


class WhichTreesAreCounted(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lab = str(Path(self.tmp.name) / "lab")
        os.makedirs(self.lab)
        _repo(self.lab)

    def test_a_lab_with_no_worktree_is_one_tree(self):
        """The main checkout appears in `git worktree list` under its
        resolved path -- /private/var where the lab is /var on macOS --
        so a naive comparison counts the same directory twice, and
        every commit in it twice with it."""
        self.assertEqual(len(drill._trees(self.lab)), 1)

    def test_a_worktree_is_found(self):
        tree = str(Path(self.tmp.name) / "wt")
        subprocess.run(["git", "-C", self.lab, "worktree", "add", "-q", "-b", "sim/task-1", tree, "HEAD"],
                       capture_output=True)
        found = drill._trees(self.lab)
        self.assertEqual(len(found), 2)
        self.assertEqual({os.path.realpath(p) for p in found},
                         {os.path.realpath(self.lab), os.path.realpath(tree)})

    def test_a_worktree_that_is_gone_is_not_counted(self):
        """`git worktree list` can name a directory that has been
        removed; reading its log would fail the whole verdict."""
        tree = str(Path(self.tmp.name) / "wt2")
        subprocess.run(["git", "-C", self.lab, "worktree", "add", "-q", "-b", "sim/task-2", tree, "HEAD"],
                       capture_output=True)
        subprocess.run(["rm", "-rf", tree], capture_output=True)
        self.assertEqual(drill._trees(self.lab), [self.lab])


if __name__ == "__main__":
    unittest.main()
