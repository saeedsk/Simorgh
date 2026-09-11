"""What a command actually wrote (execution/writewatch.py).

`apply_source_patch` declares the path it touched; `run_shell` and
`run_script` did not, so a task that wrote its page with a heredoc
produced an empty `written_paths` and every file-reading verification
check reported "skipped" -- the checks were built the same day and were
inert for exactly the tasks most likely to need them (wave-21 observer
W21-03, proved against a real bus).
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution import writewatch
from simorgh.execution.config import Config
from simorgh.execution.script import RunScriptTool
from simorgh.execution.shell import RunShellTool


def _ctx(root, action_id="a1"):
    return ToolContext(action_id=action_id, task_id=None, scope={}, constraints={},
                       data_dir=root, clock=None, logger=None, ledger=None)


class _Repo(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        (self.root / "docs").mkdir()


class SnapshotTestCase(_Repo):
    def test_a_new_file_is_seen_as_created(self):
        before = writewatch.snapshot(self.root)
        (self.root / "docs" / "a.html").write_text("<html></html>")
        after = writewatch.snapshot(self.root)
        written = writewatch.written_between(before, after)
        self.assertEqual(written, ["docs/a.html"])
        self.assertEqual(writewatch.side_effects_for(written, before, after), ("file_create:docs/a.html",))

    def test_an_edit_to_a_tracked_file_is_seen_as_a_write(self):
        target = self.root / "docs" / "b.html"
        target.write_text("one")
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qm", "init"], cwd=self.root, check=True)
        before = writewatch.snapshot(self.root)
        target.write_text("two")
        after = writewatch.snapshot(self.root)
        written = writewatch.written_between(before, after)
        self.assertEqual(written, ["docs/b.html"])
        # NOT file_create: cleanup deletes a created file outright, so
        # mislabelling an edit would destroy the original.
        self.assertEqual(writewatch.side_effects_for(written, before, after), ("file_write:docs/b.html",))

    def test_a_command_that_writes_nothing_reports_nothing(self):
        before = writewatch.snapshot(self.root)
        self.assertEqual(writewatch.written_between(before, writewatch.snapshot(self.root)), [])

    def test_outside_a_git_repo_it_reports_nothing_rather_than_guessing(self):
        # "I could not tell" must be distinguishable from "nothing was
        # written" only in that both are safe: the checks downstream skip.
        with tempfile.TemporaryDirectory() as plain:
            self.assertIsNone(writewatch.snapshot(Path(plain)))
            self.assertEqual(writewatch.written_between(None, {}), [])
            self.assertEqual(writewatch.written_between({}, None), [])

    def test_a_rename_reports_the_new_name(self):
        entries = writewatch.written_between({}, {"docs/new.html": "R "})
        self.assertEqual(entries, ["docs/new.html"])

    def test_a_sweeping_change_is_capped(self):
        after = {f"f{i}.txt": "??" for i in range(200)}
        self.assertLessEqual(len(writewatch.written_between({}, after)), 40)


class ToolsReportTheirWritesTestCase(_Repo):
    async def test_run_shell_reports_a_heredoc_write(self):
        config = Config(repo_root=self.root, shell=True)
        result = await RunShellTool(config).run(
            {"command": "printf '<html></html>' > docs/page.html"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.error)
        self.assertIn("file_create:docs/page.html", result.side_effects)
        self.assertEqual(result.metadata["written_paths"], ["docs/page.html"])

    async def test_run_shell_still_reports_the_command_itself(self):
        config = Config(repo_root=self.root, shell=True)
        result = await RunShellTool(config).run({"command": "echo hi"}, ctx=_ctx(self.root))
        self.assertTrue(any(s.startswith("run_shell:") for s in result.side_effects))

    async def test_run_shell_does_not_hold_the_event_loop(self):
        """Live-caught through the terminal (observer swe-01, 2026-09-10):
        a model's `find / -name ...` ran inline on the event loop's own
        thread, so for two minutes nothing else in the process moved --
        `cancel <task>` typed at the prompt was answered only when the
        command's own timeout expired. A ticker on the same loop counts
        its turns while a one-second command runs: 0 with the old
        inline call."""
        config = Config(repo_root=self.root, shell=True)
        turns = 0

        async def _tick() -> None:
            nonlocal turns
            while True:
                await asyncio.sleep(0.05)
                turns += 1

        ticker = asyncio.create_task(_tick())
        try:
            result = await RunShellTool(config).run({"command": "sleep 1"}, ctx=_ctx(self.root))
        finally:
            ticker.cancel()
        self.assertTrue(result.ok, result.error)
        self.assertGreaterEqual(turns, 8, f"the loop got only {turns} turn(s) during `sleep 1`")

    async def test_run_script_reports_what_the_script_wrote(self):
        config = Config(repo_root=self.root, script_timeout_s=30.0)
        result = await RunScriptTool(config).run(
            {"code": 'open("docs/out.txt", "w").write("hi")'}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.metadata.get("stderr"))
        self.assertIn("file_create:docs/out.txt", result.side_effects)

    async def test_the_staged_script_itself_is_not_reported_as_a_write(self):
        # `run_script` writes its own program into the repo before
        # running it; reporting that would put a transient file in front
        # of every verification check.
        config = Config(repo_root=self.root, script_timeout_s=30.0)
        result = await RunScriptTool(config).run({"code": "pass"}, ctx=_ctx(self.root))
        self.assertTrue(result.ok, result.metadata.get("stderr"))
        self.assertEqual(result.metadata["written_paths"], [])
