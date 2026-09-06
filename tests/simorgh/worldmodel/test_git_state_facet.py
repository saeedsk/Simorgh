"""`GitStateFacet` (worldmodel/facets/git_state.py) -- the facet's own
subprocess behavior in isolation, distinct from `test_service.py`'s
`test_git_state_degrades_honestly_outside_a_repo` (the facet wired
through a real Service)."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.worldmodel.facets.git_state import GitStateFacet


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)


class TestGitStateFacet(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-q", "-m", "init")

    def tearDown(self):
        self._tmp.cleanup()

    async def test_reports_the_real_branch_and_head(self):
        result = await GitStateFacet(self.root).get({})
        self.assertTrue(result["available"])
        self.assertIn("branch", result)

    async def test_never_inherits_the_real_terminal_stdin(self):
        """Live-caught (the creator's own real `sim.sh` use): this facet
        polls `git` on a real-time cadence -- without an explicit
        `stdin=`, each call inherits the parent's own stdin, the real
        terminal when the Kernel runs interactively. See
        `execution/tools.py`'s own module docstring for the full
        mechanism (a killed subprocess that had put a shared terminal
        into raw mode never gets to restore it)."""
        calls = []
        real_run = subprocess.run

        def _spy(*args, **kwargs):
            calls.append(kwargs)
            return real_run(*args, **kwargs)

        with unittest.mock.patch("simorgh.worldmodel.facets.git_state.subprocess.run", side_effect=_spy):
            await GitStateFacet(self.root).get({})
        self.assertTrue(calls)
        for kwargs in calls:
            self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
