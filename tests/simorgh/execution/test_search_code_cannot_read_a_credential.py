"""`search_code`'s ripgrep backend asked the right question about the
wrong path.

28003d9 routed both backends through `pathsafety.hides_a_credential`,
which is the right shape -- but the ripgrep backend still had to work
out which part of `path:lineno:text` was the path, and it split on the
first colon. A colon is a legal filename character on every filesystem
this runs on, so `workspace/notes:1.env:1:SECRET=hunter2` was checked as
`workspace/notes`: not credential-shaped, not a real file, every check
passed, and the secret came back -- while `read_file` on the very same
path answered `refused: ... looks like a credentials path`. That is the
exact reader/searcher drift the shared helper was introduced to end.

Reproduced against the real `rg` on 2026-09-10 before the fix.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from simorgh.execution import pathsafety
from simorgh.execution.config import Config
from simorgh.execution.tools import SearchCodeTool

ROOTS = ("simorgh", "workspace", "docs")


class ACredentialNameWithAColonTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="colonleak-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for name in ROOTS:
            (self.root / name).mkdir()
        (self.root / "workspace" / "notes:1.env").write_text("SECRET=hunter2\n")
        (self.root / "workspace" / "ordinary.py").write_text("VALUE = 'hunter2-lookalike'\n")
        self.config = Config(repo_root=self.root, readable_roots=ROOTS)

    def _search(self, rg: str | None):
        tool = SearchCodeTool(self.config, ripgrep_path=rg)
        if rg is None:
            tool._rg = None
        return asyncio.run(tool.run({"query": "hunter2"}, ctx=None))

    def test_read_file_refuses_the_same_path(self):
        """The premise: the two readers must agree about this file."""
        refusal = pathsafety.safe_read_file(
            self.root, "workspace/notes:1.env", readable_roots=ROOTS)
        self.assertIn("credentials path", refusal)
        self.assertNotIn("hunter2", refusal)

    def test_the_ripgrep_backend_does_not_leak_it(self):
        rg = shutil.which("rg")
        if not rg:
            self.skipTest("no ripgrep on PATH")
        result = self._search(rg)
        self.assertEqual(result.metadata["via"], "ripgrep")
        self.assertNotIn("SECRET=hunter2", result.output)
        self.assertNotIn("notes:1.env", result.output)

    def test_the_pure_python_backend_does_not_leak_it(self):
        result = self._search(None)
        self.assertEqual(result.metadata["via"], "python")
        self.assertNotIn("SECRET=hunter2", result.output)

    def test_an_ordinary_file_is_still_found_and_still_named(self):
        """Fail-closed must not mean fail-everything: the legitimate
        match still comes back, and still as `path:lineno:text`."""
        rg = shutil.which("rg")
        for backend in ([rg] if rg else []) + [None]:
            with self.subTest(backend=backend or "python"):
                result = self._search(backend)
                self.assertIn("workspace/ordinary.py:1:", result.output)


class TheParseIsUnambiguousTestCase(unittest.TestCase):
    def test_a_null_separated_line_splits_on_the_null(self):
        from simorgh.execution.tools import _rg_display, _rg_split

        line = "workspace/notes:1.env\x001:SECRET=hunter2"
        self.assertEqual(_rg_split(line), ("workspace/notes:1.env", "1:SECRET=hunter2"))
        self.assertEqual(_rg_display(line), "workspace/notes:1.env:1:SECRET=hunter2")

    def test_a_line_without_a_null_still_parses(self):
        """An `rg` too old for `--null` degrades to the old guess rather
        than to nothing; the `is_file` check catches what it gets wrong."""
        from simorgh.execution.tools import _rg_split

        self.assertEqual(_rg_split("simorgh/x.py:3:foo"), ("simorgh/x.py", "3:foo"))


if __name__ == "__main__":
    unittest.main()
