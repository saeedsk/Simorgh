"""A task working in somebody else's checkout gets no worktree of THIS
repository.

Live, 2026-09-22, SWE-bench case astropy-12907: the task opened a
worktree of Simorgh, read the file through the checkout, never wrote it
(no patch tool ran at all), and `cd workspace/swebench/astropy__astropy-
12907` answered "No such file or directory" -- the worktree does not
contain `workspace/`. It reported a one-line fix it had never applied,
`git_commit` refused ("this task did not write ..."), and the case
scored "the system produced no patch".
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts.checkout import MANIFEST_NAME
from simorgh.orchestration import profiles
from simorgh.orchestration.api import Session
from simorgh.orchestration.session import SessionRunner


class ACheckout(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        checkout = self.root / "workspace" / "swebench" / "astropy__astropy-12907"
        (checkout / "astropy" / "modeling").mkdir(parents=True)
        (checkout / MANIFEST_NAME).write_text("{}")
        self.addCleanup(os.environ.pop, "SIMORGH_EXECUTION_REPO_ROOT", None)
        os.environ["SIMORGH_EXECUTION_REPO_ROOT"] = str(self.root)

    def _session(self, subject):
        return Session(task_id="t", kind="patch", mode="execute", profile=profiles.PATCH, subject=subject)

    def _runner(self):
        runner = SessionRunner.__new__(SessionRunner)
        runner._worktrees = True   # noqa: SLF001
        return runner

    def test_a_subject_inside_a_checkout_gets_none(self):
        session = self._session("workspace/swebench/astropy__astropy-12907/astropy/modeling/separable.py")
        with mock.patch("simorgh.orchestration.session.known_tools", return_value={"worktree_open"}):
            self.assertFalse(self._runner()._uses_worktree(session))   # noqa: SLF001

    def test_an_ordinary_patch_task_still_gets_one(self):
        session = self._session("simorgh/voice/session.py")
        with mock.patch("simorgh.orchestration.session.known_tools", return_value={"worktree_open"}):
            self.assertTrue(self._runner()._uses_worktree(session))    # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
