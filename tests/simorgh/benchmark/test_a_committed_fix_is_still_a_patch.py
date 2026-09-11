"""A fix Sim COMMITTED is still the patch it produced.

The SWE-bench checkout is a copy of the image's `/testbed`, `.git` and
all, sitting at the instance's `base_commit`. `diff_of` read
`git diff --cached` -- the index against HEAD -- so a change that was
committed moved HEAD and disappeared from the diff entirely.

Live, 2026-09-10, two of three cases in one run:

    step 12  run_shell: [main e2aef5e39] Fix NDDataRef mask propagation
                        when one operand has no mask  1 file changed
    ...
    astropy__astropy-14995  ->  "the system produced no patch"

And it was not bad luck. `did_anything`'s revise hint says "apply the
change with apply_source_patch, then commit it", so the verifier was
telling Sim to do the exact thing that made its work invisible to the
scorer -- and the result read as the system producing nothing rather
than as a harness that could not see what it produced. That is the
honesty rule failing in the direction that flatters nobody: a real fix
scored as no fix at all.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.benchmark.swebench import diff_of


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return done.stdout


class CommittedFixTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "testbed"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@local")
        _git(self.repo, "config", "user.name", "T")
        (self.repo / "mod.py").write_text("def f():\n    return 1\n")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "test_mod.py").write_text("def test_f():\n    assert f() == 2\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        self.base = _git(self.repo, "rev-parse", "HEAD").strip()

    def _edit(self):
        (self.repo / "mod.py").write_text("def f():\n    return 2\n")

    def test_an_uncommitted_fix_is_read(self):
        self._edit()
        patch, problem = diff_of(self.repo, base=self.base)
        self.assertEqual(problem, "")
        self.assertIn("return 2", patch)

    def test_a_committed_fix_is_read_too(self):
        self._edit()
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "Fix f")
        patch, problem = diff_of(self.repo, base=self.base)
        self.assertEqual(problem, "")
        self.assertIn("return 2", patch, "a committed fix must still be the patch")

    def test_a_fix_half_committed_is_read_whole(self):
        # One hunk committed, one still in the working tree: the scorer
        # has to see both, because the container is given one patch.
        self._edit()
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "Fix f")
        (self.repo / "other.py").write_text("X = 1\n")
        patch, problem = diff_of(self.repo, base=self.base)
        self.assertEqual(problem, "")
        self.assertIn("return 2", patch)
        self.assertIn("other.py", patch)

    def test_test_files_are_still_dropped(self):
        (self.repo / "tests" / "test_mod.py").write_text("def test_f():\n    assert True\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "cheat")
        patch, _ = diff_of(self.repo, base=self.base)
        self.assertNotIn("test_mod.py", patch)

    def test_the_manifest_is_never_part_of_the_patch(self):
        # `materialize` writes it into the checkout; `git add -A` stages
        # it; run five's scored patches all began with it (2026-09-10).
        from simorgh.contracts.checkout import ContainerCheckout

        ContainerCheckout(image="i", platform="", workdir="/testbed", base_commit=self.base,
                          setup="", test_command="pytest").write(self.repo)
        self._edit()
        patch, problem = diff_of(self.repo, base=self.base)
        self.assertEqual(problem, "")
        self.assertIn("return 2", patch)
        self.assertNotIn("simorgh-checkout", patch)

    def test_no_change_is_no_patch(self):
        patch, problem = diff_of(self.repo, base=self.base)
        self.assertEqual(problem, "")
        self.assertEqual(patch.strip(), "")

    def test_a_base_the_checkout_does_not_carry_falls_back(self):
        # A shallow image, or a rewritten history: an uncommitted change
        # is still worth scoring. Saying "no patch" because of our own
        # bookkeeping is the mistake this file exists for.
        self._edit()
        patch, problem = diff_of(self.repo, base="0" * 40)
        self.assertEqual(problem, "")
        self.assertIn("return 2", patch)

    def test_no_base_given_behaves_as_before(self):
        self._edit()
        patch, problem = diff_of(self.repo)
        self.assertEqual(problem, "")
        self.assertIn("return 2", patch)


if __name__ == "__main__":
    unittest.main()
