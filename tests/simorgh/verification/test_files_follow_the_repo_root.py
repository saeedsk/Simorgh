"""`_files.read_repo_file` reads from the tree the session worked in
(`subject["repo_root"]`, a worktree) and not only from wherever this
package was imported from (observer, 2026-09-11)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.verification.api import CheckContext, VerifyRequest
from simorgh.verification.checks import _files
from simorgh.verification.checks.syntax import SyntaxCheck
from simorgh.verification.config import VerificationConfig


class TestRepoRoot(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "simorgh").mkdir()
        (self.root / "simorgh" / "new.py").write_text("def f(:\n")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _req(self, **extra) -> VerifyRequest:
        return VerifyRequest(
            verification_id="v1", task_id="t1", kind="task",
            subject={"kind": "patch", "description": "d", "result": "r",
                     "written_paths": ["simorgh/new.py"], **extra},
        )

    def test_the_subject_names_the_tree(self) -> None:
        self.assertEqual(_files.repo_root_of(self._req(repo_root=str(self.root))), self.root)
        self.assertEqual(_files.repo_root_of(self._req()), _files.REPO_ROOT)
        self.assertEqual(_files.repo_root_of(self._req(repo_root="")), _files.REPO_ROOT)
        self.assertEqual(_files.repo_root_of(self._req(repo_root="relative/path")), _files.REPO_ROOT)
        self.assertEqual(_files.repo_root_of(self._req(repo_root=str(self.root / "missing"))), _files.REPO_ROOT)

    def test_read_follows_the_root(self) -> None:
        self.assertEqual(_files.read_repo_file("simorgh/new.py", root=self.root), "def f(:\n")
        self.assertIsNone(_files.read_repo_file("simorgh/new.py"))  # not in the import tree
        self.assertIsNone(_files.read_repo_file("../etc/passwd", root=self.root))

    async def test_the_syntax_check_sees_a_file_written_in_a_worktree(self) -> None:
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        result = await SyntaxCheck().run(self._req(repo_root=str(self.root)), ctx)
        self.assertEqual(result.status, "failed", result.detail)
        blind = await SyntaxCheck().run(self._req(), ctx)
        self.assertNotEqual(blind.status, "failed")
