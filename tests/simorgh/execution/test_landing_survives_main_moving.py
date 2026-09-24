"""Main moving while the gate runs must not throw the suite away.

Live, 2026-09-24: Sim wrote a module, committed it, rebased onto main and
started the gate. The gate took 8.1 minutes -- and in those minutes a
human (me) landed five commits on main. The rebase had been onto the main
of eight minutes earlier, so `git merge --ff-only` refused, and the task
was told only git's own words:

    landing failed: refused: main could not fast-forward -- hint:
    Diverging branches can't be fast-forwarded ... fatal: Not possible
    to fast-forward, aborting.

Nothing was kept. Sim had done the work correctly and could not tell
that from having broken something, and the whole suite had been run for
nothing. The gate is the slow step by design, so this is not a rare
race: any commit landing on main during those minutes hits it.

So `land` now looks again after the gate, rebases onto where main
actually is, and lands -- and SAYS that the suite ran before those
commits arrived, rather than implying the tree that landed is the tree
that was tested.
"""

from __future__ import annotations

from pathlib import Path

from simorgh.contracts.protocols import ToolResult

from .test_worktree import WorktreeCase, _git


class LandingSurvivesMainMovingTestCase(WorktreeCase):
    async def _commit_in_worktree(self, value: str = "2") -> Path:
        opened = await self.manager.open("t1")
        (opened.path / "simorgh" / "x.py").write_text(f"VALUE = {value}\n")
        _git(opened.path, "commit", "-qam", f"value {value}")
        return opened.path

    def _gate_that_lands_on_main(self, *, files: tuple[str, ...] = ("simorgh/other.py",)):
        """A gate that, while it "runs", commits to main -- exactly what a
        human working the same checkout does during those minutes."""
        def gate(root: Path) -> ToolResult:
            for i, name in enumerate(files):
                target = self.repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"LANDED = {i}\n")
                _git(self.repo, "add", name)
                _git(self.repo, "commit", "-qm", f"meanwhile {name}")
            return ToolResult(ok=True, output="all green")
        return gate

    async def test_it_lands_anyway_and_says_main_moved(self) -> None:
        self.manager.gate = self._gate_that_lands_on_main(
            files=("simorgh/other.py", "simorgh/another.py"))
        await self._commit_in_worktree()
        landed = await self.manager.land("t1")

        self.assertTrue(landed.ok, landed.detail)
        self.assertIn("main moved on while the suite ran", landed.detail)
        self.assertIn("2 commit(s) arrived", landed.detail)
        # The branch's own change is on main, beside what arrived meanwhile.
        self.assertEqual((self.repo / "simorgh" / "x.py").read_text(), "VALUE = 2\n")
        self.assertTrue((self.repo / "simorgh" / "other.py").exists())
        self.assertTrue((self.repo / "simorgh" / "another.py").exists())

    async def test_a_real_conflict_still_refuses_and_names_the_file(self) -> None:
        """Rebasing after the gate is not a licence to guess: when the
        commits that arrived touch the same file, this is the model's to
        resolve, exactly as a conflict before the gate would have been."""
        self.manager.gate = self._gate_that_lands_on_main(files=("simorgh/x.py",))
        await self._commit_in_worktree()
        landed = await self.manager.land("t1")

        self.assertFalse(landed.ok)
        self.assertIn("main moved on while the suite ran", landed.detail)
        self.assertIn("simorgh/x.py", landed.detail)
        self.assertIn("simorgh/x.py", landed.conflicts)
        # Main keeps what arrived; nothing half-landed.
        self.assertEqual((self.repo / "simorgh" / "x.py").read_text(), "LANDED = 0\n")

    async def test_a_quiet_main_lands_without_the_note(self) -> None:
        """The ordinary case says nothing extra."""
        self.manager.gate = lambda root: ToolResult(ok=True, output="all green")
        await self._commit_in_worktree()
        landed = await self.manager.land("t1")

        self.assertTrue(landed.ok, landed.detail)
        self.assertNotIn("main moved", landed.detail)
