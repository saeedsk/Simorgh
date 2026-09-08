"""A session never walks away from a change nobody committed.

Live-caught 2026-09-07 by a trial built to fail: asked to make a change
that breaks the suite, Sim applied it, ran the tests, saw red, and
correctly refused to commit -- exactly as instructed -- then left the
modified file sitting in the working tree.

Three things were wrong behind that.

1. It had nowhere to go. Its instructions said to use `git_revert`, which
   undoes a *commit*, and there was no commit. No tool could undo an
   applied-but-uncommitted change at all.
2. A failing tool told it nothing. The reason lives in `error`, and only
   `stdout_preview` was ever read, so a refusal arrived as an empty
   result: "that failed", and not a word about why.
3. Even with the tool and the instruction, the model spent its remaining
   steps investigating the failure rather than tidying up -- which is a
   reasonable thing to do. "Never leave a broken change in the tree" is a
   property the system should hold, not a request the model has to
   remember.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.tools import GitDiscardTool, builtin_tools
from simorgh.orchestration import profiles, scaffolds


def _ctx(root: Path) -> ToolContext:
    return ToolContext(
        action_id="a1", task_id=None, scope={}, constraints={},
        data_dir=root, clock=None, logger=None, ledger=None,
    )


class GitDiscardTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "simorgh").mkdir()
        self.target = self.root / "simorgh" / "x.py"
        self.target.write_text("original = 1\n")
        for cmd in (
            ["git", "init", "-q"],
            ["git", "add", "-A"],
            ["git", "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "base"],
        ):
            subprocess.run(cmd, cwd=self.root, capture_output=True)
        self.tool = GitDiscardTool(ExecutionConfig(repo_root=self.root))

    async def test_it_puts_a_modified_file_back(self):
        self.target.write_text("broken = (\n")
        result = await self.tool.run({"path": "simorgh/x.py"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.target.read_text(), "original = 1\n")

    async def test_it_refuses_a_file_git_has_never_seen(self):
        """An untracked file has no committed version to go back to, and
        deleting it would be a different, destructive act than the one
        this tool advertises."""
        (self.root / "simorgh" / "new.py").write_text("x = 1\n")
        result = await self.tool.run({"path": "simorgh/new.py"}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)
        self.assertIn("not tracked", result.error)
        self.assertTrue((self.root / "simorgh" / "new.py").exists())

    async def test_it_refuses_a_path_outside_the_writable_scope(self):
        result = await self.tool.run({"path": "../escape.py"}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)
        self.assertIn("scope", result.error)

    async def test_it_refuses_an_empty_path(self):
        result = await self.tool.run({"path": ""}, ctx=_ctx(self.root))
        self.assertFalse(result.ok)

    async def test_it_reports_what_it_undid(self):
        self.target.write_text("changed = 2\n")
        result = await self.tool.run({"path": "simorgh/x.py"}, ctx=_ctx(self.root))
        self.assertIn("git_discard:simorgh/x.py", result.side_effects)


class TheToolIsActuallyReachableTestCase(unittest.TestCase):
    """A tool nothing offers is a tool that does not exist -- the shape
    of most of the bugs found this week."""

    def test_execution_registers_it(self):
        names = {tool.name for tool in builtin_tools(ExecutionConfig(repo_root=Path.cwd()))}
        self.assertIn("git_discard", names)

    def test_the_writing_profiles_offer_it(self):
        self.assertIn("git_discard", profiles.PATCH.tools)
        self.assertIn("git_discard", profiles.SKILL.tools)

    def test_a_read_only_profile_does_not(self):
        self.assertNotIn("git_discard", profiles.RESEARCH.tools)
        self.assertNotIn("git_discard", profiles.PLAN.tools)

    def test_the_instruction_names_the_tool_that_can_do_the_job(self):
        """It used to say `git_revert`, which cannot undo an uncommitted
        change."""
        rules = scaffolds.render(profiles.PATCH)
        self.assertIn("git_discard", rules)
        self.assertIn("Never leave a broken change", rules)


if __name__ == "__main__":
    unittest.main()
