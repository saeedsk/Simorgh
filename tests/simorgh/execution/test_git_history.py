"""Sim can read its own git log.

The creator, 2026-09-16: "sim should be able to easily see its git
history, status and remember it has that skill." Hours earlier he had
asked Sim whether it had read its own git log to see what Claude Code
had changed, and Sim answered: "No -- I still can't run git from here,
so no log reading; I can only search and read files directly." Told that
git log is basic and that CLI permission had been granted, Sim said it
had started a background build to give itself shell access -- then later
said again that it had none.

Sim was right about the gap and wrong about the remedy. Three git tools
existed and all three were WRITES (`git_commit`, `git_revert`,
`git_discard`), all of them confined to the task profiles: `chat` and
`voice` had no git tool at all and no `run_shell`. The same drift that
had just cost the voice profile `remind`.

`run_shell` in a six-step spoken turn would be an unbounded blast radius
bought to answer a bounded question. This runs three git commands and
can write nothing.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.tools import GitHistoryTool


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)


class _Ctx:
    root = None


class GitHistoryTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        _git(self.root, "init", "-q")
        _git(self.root, "config", "user.email", "t@example.com")
        _git(self.root, "config", "user.name", "T")
        (self.root / "a.py").write_text("x = 1\n")
        _git(self.root, "add", "a.py")
        _git(self.root, "commit", "-qm", "first commit")
        self.tool = GitHistoryTool(Config(repo_root=self.root))

    async def _run(self, subject=""):
        return await self.tool.run({"subject": subject}, ctx=_Ctx())

    async def test_it_reads_the_branch_and_the_commits(self):
        result = await self._run()
        self.assertTrue(result.ok, result.error)
        self.assertIn("first commit", result.output)
        self.assertIn("branch", result.output)
        self.assertEqual(result.metadata["commits"], 1)

    async def test_a_clean_tree_says_so(self):
        result = await self._run()
        self.assertIn("working tree clean", result.output)
        self.assertEqual(result.metadata["uncommitted"], 0)

    async def test_an_uncommitted_change_is_visible(self):
        """The half of the question Sim could never answer: not what it
        committed, but what it has left lying around."""
        (self.root / "b.py").write_text("y = 2\n")
        result = await self._run()
        self.assertIn("uncommitted", result.output)
        self.assertEqual(result.metadata["uncommitted"], 1)
        self.assertNotIn("working tree clean", result.output)

    async def test_a_number_asks_for_more_commits(self):
        for n in range(2, 6):
            (self.root / "a.py").write_text(f"x = {n}\n")
            _git(self.root, "commit", "-qam", f"commit {n}")
        self.assertEqual((await self._run("3")).metadata["commits"], 3)
        self.assertEqual((await self._run()).metadata["commits"], 5)

    async def test_the_count_is_capped(self):
        """A spoken turn must not become a changelog."""
        result = await self._run("9999")
        self.assertLessEqual(result.metadata["commits"], GitHistoryTool.MAX_COUNT)

    async def test_a_path_narrows_the_history(self):
        (self.root / "other.py").write_text("z = 3\n")
        _git(self.root, "add", "other.py")
        _git(self.root, "commit", "-qm", "add other")
        result = await self._run("a.py")
        self.assertIn("first commit", result.output)
        self.assertNotIn("add other", result.output)

    async def test_a_path_that_does_not_exist_is_refused_clearly(self):
        """Never succeed while saying nothing true: "no history" and
        "no such file" are different answers."""
        result = await self._run("simorgh/not_here.py")
        self.assertFalse(result.ok)
        self.assertIn("no such path", result.error)

    async def test_it_cannot_write(self):
        self.assertTrue(GitHistoryTool.read_only)
        self.assertEqual(GitHistoryTool.reversibility, "read_only")

    async def test_a_directory_that_is_not_a_repository_is_refused(self):
        with tempfile.TemporaryDirectory() as plain:
            tool = GitHistoryTool(Config(repo_root=Path(plain)))
            result = await tool.run({"subject": ""}, ctx=_Ctx())
            self.assertFalse(result.ok)
            self.assertIn("not a git repository", result.error)


class ItIsReachableWhereItIsNeededTestCase(unittest.TestCase):
    """Registered in six places or it does not exist. The creator's
    words were "remember it has that skill" -- which means seeing it in
    its own catalogue, not being told about it."""

    def test_the_spoken_and_typed_profiles_both_have_it(self):
        from simorgh.orchestration import profiles

        self.assertIn("git_history", profiles.for_percept("voice").tools)
        self.assertIn("git_history", profiles.for_percept("chat").tools)

    def test_it_is_labelled_read_only_for_guardian(self):
        """Guardian trusts the declared label, so it must be the tool's
        worst capability -- and this tool's worst is a read."""
        from simorgh.orchestration.tools import _TOOL_POLICY

        self.assertEqual(_TOOL_POLICY["git_history"], ("read_only", False))

    def test_the_model_is_told_what_the_argument_is(self):
        from simorgh.contracts.toolargs import MARKER_ARG_KEY

        self.assertEqual(MARKER_ARG_KEY["git_history"], "subject")

    def test_the_write_tools_stay_out_of_a_spoken_turn(self):
        from simorgh.orchestration import profiles

        voice = profiles.for_percept("voice").tools
        for tool in ("git_commit", "git_revert", "git_discard", "run_shell"):
            self.assertNotIn(tool, voice)


if __name__ == "__main__":
    unittest.main()
