"""One worktree per task (execution/worktree.py): opened from HEAD,
edited through the ordinary tools, landed on main by rebase, gate and
fast-forward -- against a real git repository in a temp directory."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult
from simorgh.execution.config import Config
from simorgh.execution.tools import ApplySourcePatchTool, GitCommitTool, ReadFileTool, tool_root
from simorgh.execution.worktree import (WorktreeCloseTool, WorktreeLandTool, WorktreeManager,
                                        WorktreeOpenTool)

_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *_ID, *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "simorgh").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "workspace").mkdir()
    (repo / "simorgh" / "x.py").write_text("VALUE = 1\n")
    (repo / "workspace" / "README.md").write_text("scratch\n")
    (repo / ".gitignore").write_text("workspace/*\n!workspace/README.md\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _ctx(config: Config, root: Path | None = None, task_id: str | None = "t1") -> ToolContext:
    return ToolContext(action_id="a1", task_id=task_id, scope={}, constraints={},
                       data_dir=config.repo_root, clock=None, logger=None, ledger=None, root=root)


class WorktreeCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="simorgh-wt-")
        self.root = Path(self._tmp.name)
        self.repo = _repo(self.root)
        self.config = Config(repo_root=self.repo)
        self.manager = WorktreeManager(self.repo, self.root / "home")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestOpen(WorktreeCase):
    async def test_open_branches_from_head_under_home_not_the_repo(self) -> None:
        opened = await self.manager.open("t1")
        self.assertTrue(opened.created)
        self.assertEqual(opened.head, _git(self.repo, "rev-parse", "HEAD"))
        self.assertTrue(str(opened.path).startswith(str(self.root / "home")))
        self.assertFalse(str(opened.path).startswith(str(self.repo)))
        self.assertEqual(_git(opened.path, "rev-parse", "--abbrev-ref", "HEAD"), "sim/task-t1")
        self.assertEqual(self.manager.root_for("t1"), opened.path)
        self.assertIsNone(self.manager.root_for("t2"))
        self.assertIsNone(self.manager.root_for(None))

    async def test_a_second_open_resumes_the_same_tree(self) -> None:
        first = await self.manager.open("t1")
        (first.path / "simorgh" / "x.py").write_text("VALUE = 2\n")
        again = await self.manager.open("t1")
        self.assertFalse(again.created)
        self.assertEqual(again.path, first.path)
        self.assertEqual((again.path / "simorgh" / "x.py").read_text(), "VALUE = 2\n")

    async def test_a_lost_worktree_resumes_its_branch(self) -> None:
        """The branch outlives a worktree directory that went missing
        (a pruned temp dir, a crash): its commits are real work."""
        first = await self.manager.open("t1")
        (first.path / "simorgh" / "x.py").write_text("VALUE = 3\n")
        _git(first.path, "commit", "-qam", "work")
        import shutil
        shutil.rmtree(first.path)
        again = await self.manager.open("t1")
        self.assertTrue(again.created)
        self.assertEqual((again.path / "simorgh" / "x.py").read_text(), "VALUE = 3\n")

    async def test_open_refuses_outside_a_git_repo(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()
        manager = WorktreeManager(plain, self.root / "home2")
        self.assertFalse(manager.available)
        with self.assertRaises(RuntimeError):
            await manager.open("t1")


class TestToolsFollowTheWorktree(WorktreeCase):
    async def test_a_patch_lands_in_the_worktree_and_leaves_main_alone(self) -> None:
        opened = await self.manager.open("t1")
        ctx = _ctx(self.config, root=opened.path)
        result = await ApplySourcePatchTool(self.config).run(
            {"subject": "simorgh/x.py", "code": "VALUE = 2\n"}, ctx=ctx)
        self.assertTrue(result.ok, result.error)
        self.assertEqual((opened.path / "simorgh" / "x.py").read_text(), "VALUE = 2\n")
        self.assertEqual((self.repo / "simorgh" / "x.py").read_text(), "VALUE = 1\n")
        read = await ReadFileTool(self.config).run({"path": "simorgh/x.py"}, ctx=ctx)
        self.assertIn("VALUE = 2", read.output)
        live = await ReadFileTool(self.config).run({"path": "simorgh/x.py"}, ctx=_ctx(self.config))
        self.assertIn("VALUE = 1", live.output)

    async def test_a_commit_goes_on_the_task_branch_not_main(self) -> None:
        opened = await self.manager.open("t1")
        ctx = _ctx(self.config, root=opened.path)
        before = _git(self.repo, "rev-parse", "HEAD")
        await ApplySourcePatchTool(self.config).run({"subject": "simorgh/x.py", "code": "VALUE = 2\n"}, ctx=ctx)
        commit = await GitCommitTool(self.config).run({"path": "simorgh/x.py", "message": "bump"}, ctx=ctx)
        self.assertTrue(commit.ok, commit.error)
        self.assertEqual(_git(self.repo, "rev-parse", "HEAD"), before)
        self.assertNotEqual(_git(opened.path, "rev-parse", "HEAD"), before)

    def test_scratch_stays_on_the_live_tree(self) -> None:
        ctx = _ctx(self.config, root=self.root / "somewhere")
        self.assertEqual(tool_root(self.config, ctx, "workspace/notes.md"), self.repo)
        self.assertEqual(tool_root(self.config, ctx, "simorgh/x.py"), self.root / "somewhere")
        self.assertEqual(tool_root(self.config, _ctx(self.config), "simorgh/x.py"), self.repo)
        self.assertEqual(tool_root(self.config, None), self.repo)


class TestLanding(WorktreeCase):
    async def _commit_in_worktree(self, task: str = "t1", value: str = "2") -> Path:
        opened = await self.manager.open(task)
        (opened.path / "simorgh" / "x.py").write_text(f"VALUE = {value}\n")
        _git(opened.path, "commit", "-qam", f"value {value}")
        return opened.path

    async def test_a_green_branch_fast_forwards_main_and_is_removed(self) -> None:
        seen: list[Path] = []

        def gate(root: Path) -> ToolResult:
            seen.append(root)
            return ToolResult(ok=True, output="all green")

        self.manager.gate = gate
        path = await self._commit_in_worktree()
        before = _git(self.repo, "rev-parse", "HEAD")
        landed = await self.manager.land("t1")
        self.assertTrue(landed.ok, landed.detail)
        self.assertEqual(landed.landed, 1)
        self.assertNotEqual(_git(self.repo, "rev-parse", "HEAD"), before)
        self.assertEqual((self.repo / "simorgh" / "x.py").read_text(), "VALUE = 2\n")
        self.assertEqual(seen, [path])
        self.assertFalse(path.exists())
        self.assertNotIn("sim/task-t1", _git(self.repo, "branch", "--list", "sim/task-t1"))
        self.assertIsNone(self.manager.root_for("t1"))

    async def test_a_dirty_worktree_is_refused_and_kept(self) -> None:
        path = await self._commit_in_worktree()
        (path / "simorgh" / "x.py").write_text("VALUE = 99\n")
        landed = await self.manager.land("t1")
        self.assertFalse(landed.ok)
        self.assertIn("uncommitted", landed.detail)
        self.assertIn("simorgh/x.py", landed.detail)
        self.assertTrue(path.exists())

    async def test_a_red_gate_is_refused_and_kept(self) -> None:
        self.manager.gate = lambda root: ToolResult(ok=False, output="FAILED tests/test_x.py::test_it", error="exit_code=1")
        path = await self._commit_in_worktree()
        before = _git(self.repo, "rev-parse", "HEAD")
        landed = await self.manager.land("t1")
        self.assertFalse(landed.ok)
        self.assertIn("red", landed.detail)
        self.assertIn("test_it", landed.gate_output)
        self.assertEqual(_git(self.repo, "rev-parse", "HEAD"), before)
        self.assertTrue(path.exists())

    async def test_a_rebase_conflict_is_refused_aborted_and_kept(self) -> None:
        path = await self._commit_in_worktree(value="2")
        (self.repo / "simorgh" / "x.py").write_text("VALUE = 3\n")
        _git(self.repo, "commit", "-qam", "main moved")
        landed = await self.manager.land("t1")
        self.assertFalse(landed.ok)
        self.assertIn("conflicts", landed.detail)
        self.assertEqual(landed.conflicts, ("simorgh/x.py",))
        self.assertTrue(path.exists())
        # No rebase left half-done in the worktree.
        status = subprocess.run(["git", "status"], cwd=path, capture_output=True, text=True).stdout
        self.assertNotIn("rebase in progress", status)
        self.assertEqual((path / "simorgh" / "x.py").read_text(), "VALUE = 2\n")

    async def test_a_rebase_that_applies_cleanly_lands_on_the_moved_main(self) -> None:
        path = await self._commit_in_worktree()
        (self.repo / "tests" / "test_new.py").write_text("def test_it():\n    pass\n")
        _git(self.repo, "add", "tests/test_new.py")
        _git(self.repo, "commit", "-qm", "main moved elsewhere")
        landed = await self.manager.land("t1")
        self.assertTrue(landed.ok, landed.detail)
        self.assertEqual((self.repo / "simorgh" / "x.py").read_text(), "VALUE = 2\n")
        self.assertTrue((self.repo / "tests" / "test_new.py").exists())
        self.assertFalse(path.exists())

    async def test_nothing_to_land_is_ok_and_closes(self) -> None:
        opened = await self.manager.open("t1")
        landed = await self.manager.land("t1")
        self.assertTrue(landed.ok)
        self.assertEqual(landed.landed, 0)
        self.assertIn("nothing to land", landed.detail)
        self.assertFalse(opened.path.exists())

    async def test_a_live_checkout_in_the_way_is_refused_honestly(self) -> None:
        path = await self._commit_in_worktree()
        (self.repo / "simorgh" / "x.py").write_text("VALUE = 7  # the creator's unsaved edit\n")
        landed = await self.manager.land("t1")
        self.assertFalse(landed.ok)
        self.assertIn("fast-forward", landed.detail)
        self.assertTrue(path.exists())
        self.assertEqual((self.repo / "simorgh" / "x.py").read_text(), "VALUE = 7  # the creator's unsaved edit\n")

    async def test_land_without_a_worktree_is_refused(self) -> None:
        landed = await self.manager.land("nope")
        self.assertFalse(landed.ok)
        self.assertIn("no worktree", landed.detail)


class TestCloseAndPrune(WorktreeCase):
    async def test_close_removes_tree_and_branch(self) -> None:
        opened = await self.manager.open("t1")
        detail = await self.manager.close("t1")
        self.assertIn("removed", detail)
        self.assertFalse(opened.path.exists())
        self.assertEqual(_git(self.repo, "branch", "--list", "sim/task-t1"), "")
        self.assertIn("no worktree", await self.manager.close("t1"))

    async def test_prune_removes_only_old_worktrees(self) -> None:
        old = await self.manager.open("old")
        fresh = await self.manager.open("fresh")
        stale = time.time() - 10 * 86400
        os.utime(old.path, (stale, stale))
        removed = self.manager.prune(7 * 86400)
        self.assertEqual(removed, ["old"])
        self.assertFalse(old.path.exists())
        self.assertTrue(fresh.path.exists())


class TestTheTools(WorktreeCase):
    async def test_open_land_close_through_the_tool_surface(self) -> None:
        self.manager.gate = lambda root: ToolResult(ok=True, output="green")
        opened = await WorktreeOpenTool(self.manager).run({}, ctx=_ctx(self.config, task_id="t9"))
        self.assertTrue(opened.ok, opened.error)
        lines = opened.output.splitlines()
        path = Path(lines[0])
        self.assertTrue(path.is_dir())
        self.assertEqual(lines[1], _git(self.repo, "rev-parse", "HEAD"))
        self.assertTrue(lines[2].startswith("created"))

        (path / "simorgh" / "x.py").write_text("VALUE = 5\n")
        _git(path, "commit", "-qam", "five")
        landed = await WorktreeLandTool(self.manager, timeout_s=10).run({}, ctx=_ctx(self.config, task_id="t9"))
        self.assertTrue(landed.ok, landed.error)
        self.assertIn("landed 1 commit", landed.output)
        self.assertEqual(landed.metadata["landed"], 1)
        self.assertEqual((self.repo / "simorgh" / "x.py").read_text(), "VALUE = 5\n")

        closed = await WorktreeCloseTool(self.manager).run({}, ctx=_ctx(self.config, task_id="t9"))
        self.assertTrue(closed.ok)

    async def test_the_task_id_comes_from_the_context_first(self) -> None:
        """The model's arguments never choose whose worktree a call
        touches: the service sets `task_id` from the recorded proposal."""
        result = await WorktreeOpenTool(self.manager).run({"task_id": "other"}, ctx=_ctx(self.config, task_id="mine"))
        self.assertTrue(result.ok)
        self.assertIsNotNone(self.manager.root_for("mine"))
        self.assertIsNone(self.manager.root_for("other"))
        no_task = await WorktreeOpenTool(self.manager).run({}, ctx=_ctx(self.config, task_id=None))
        self.assertFalse(no_task.ok)

    async def test_a_red_gate_reaches_the_caller_as_an_error_with_the_output(self) -> None:
        self.manager.gate = lambda root: ToolResult(ok=False, output="FAILED tests/t.py::test_a", error="exit_code=1")
        ctx = _ctx(self.config, task_id="t9")
        opened = await WorktreeOpenTool(self.manager).run({}, ctx=ctx)
        path = Path(opened.output.splitlines()[0])
        (path / "simorgh" / "x.py").write_text("VALUE = 5\n")
        _git(path, "commit", "-qam", "five")
        landed = await WorktreeLandTool(self.manager, timeout_s=10).run({}, ctx=ctx)
        self.assertFalse(landed.ok)
        self.assertIn("red", landed.error)
        self.assertIn("test_a", landed.output)


if __name__ == "__main__":
    unittest.main()
