"""Two `run_tests` in flight on one checkout must not fight over its
index.

Measured 2026-09-10 against a real astropy checkout: two concurrent
`RunTestsTool` calls, and one came back `could not read the checkout's
changes: could not stage the checkout` -- both `_checkout_patch` calls
ran `git add -A` in the same `.git/index` and the second lost the race
for `index.lock`. A second worker, or the verifier reading the same
checkout, is the same collision. The diff is now read through a private
index, so a held lock is not this reader's problem.
"""

from __future__ import annotations

import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from simorgh.benchmark.swebench import diff_of
from simorgh.contracts.checkout import ContainerCheckout
from simorgh.execution.tools import _checkout_patch


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True)


class SharedCheckoutTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.checkout = Path(self._tmp.name) / "co"
        (self.checkout / "pkg").mkdir(parents=True)
        (self.checkout / "pkg" / "mod.py").write_text("X = 1\n")
        _git(self.checkout, "init", "-q")
        _git(self.checkout, "add", "-A")
        _git(self.checkout, "commit", "-qm", "base")
        self.base = _git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        ContainerCheckout(image="img:1", platform="linux/amd64", workdir="/testbed",
                          base_commit=self.base, setup="", test_command="pytest").write(self.checkout)
        (self.checkout / "pkg" / "mod.py").write_text("X = 2\n")

    def test_a_held_index_lock_does_not_stop_the_container_patch(self):
        (self.checkout / ".git" / "index.lock").write_text("")
        patch, problem = _checkout_patch(self.checkout, self.base)
        self.assertEqual(problem, "")
        self.assertIn("+X = 2", patch)

    def test_a_held_index_lock_does_not_stop_the_scored_patch(self):
        (self.checkout / ".git" / "index.lock").write_text("")
        patch, problem = diff_of(self.checkout, base=self.base)
        self.assertEqual(problem, "")
        self.assertIn("+X = 2", patch)

    def test_the_checkouts_own_index_is_left_alone(self):
        _checkout_patch(self.checkout, self.base)
        staged = _git(self.checkout, "diff", "--cached", "--name-only").stdout.strip()
        self.assertEqual(staged, "", "reading the diff must not stage anything in the real index")

    def test_many_readers_at_once_all_succeed(self):
        problems: list[str] = []

        def reader():
            for _ in range(5):
                _, problem = _checkout_patch(self.checkout, self.base)
                if problem:
                    problems.append(problem)

        threads = [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
