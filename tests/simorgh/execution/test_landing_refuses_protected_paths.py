"""`worktree_land` refuses a diff that touches a Guardian-protected path
(stage 18 item 12).

Guardian's ProtectedRule reads each proposal's TEXT; a file written by a
program that never names it (a shell script, Claude Code's own tools)
reached a commit unseen, and nothing looked at the diff that lands. These
pin the second lock: an ordinary patch task's branch that changes
`simorgh/guardian/` is refused before the gate runs, an ordinary branch
lands, and the one exemption Guardian makes -- a NEW `test_*.py` under a
protected package's `tests/` twin -- is made here too, and no other.

The list is Guardian's own (`guardian/config.py`), never a copy, and the
Service reads it from `guardian:protected`.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import ToolResult
from simorgh.execution.worktree import WorktreeManager, protected_hits
from simorgh.guardian.config import DEFAULT_PROTECTED_SUBJECTS

_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *_ID, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _repo(root: Path) -> Path:
    repo = root / "repo"
    for d in ("simorgh/guardian", "simorgh/memory", "tests/simorgh/execution", "docs"):
        (repo / d).mkdir(parents=True)
    (repo / "simorgh" / "guardian" / "rules.py").write_text("RULES = 1\n")
    (repo / "simorgh" / "memory" / "store.py").write_text("STORE = 1\n")
    (repo / "tests" / "simorgh" / "execution" / "test_old.py").write_text("def test_old():\n    assert True\n")
    (repo / "docs" / "SOUL.md").write_text("soul\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


class _Case(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="simorgh-protected-")
        self.root = Path(self._tmp.name)
        self.repo = _repo(self.root)
        self.gated: list[Path] = []

        def gate(path: Path) -> ToolResult:
            self.gated.append(path)
            return ToolResult(ok=True, output="green")

        async def guardian_list():
            return DEFAULT_PROTECTED_SUBJECTS

        self.manager = WorktreeManager(self.repo, self.root / "home", gate=gate, protected=guardian_list)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def _branch(self, edits: dict[str, str | None], task: str = "t1") -> Path:
        """An ordinary patch task: edit files in its worktree and commit."""
        opened = await self.manager.open(task)
        for rel, text in edits.items():
            target = opened.path / rel
            if text is None:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
        _git(opened.path, "add", "-A")
        _git(opened.path, "commit", "-qm", "work")
        return opened.path


class AProtectedDiffIsRefused(_Case):
    async def test_an_ordinary_patch_task_that_edits_guardian_is_refused_before_the_gate(self):
        before = _git(self.repo, "rev-parse", "HEAD")
        path = await self._branch({"simorgh/memory/store.py": "STORE = 2\n",
                                   "simorgh/guardian/rules.py": "RULES = 0\n"})
        landed = await self.manager.land("t1")
        self.assertFalse(landed.ok)
        self.assertIn("Guardian-protected", landed.detail)
        self.assertIn("simorgh/guardian/rules.py (simorgh/guardian/)", landed.detail)
        self.assertNotIn("store.py", landed.detail, "only the protected path is named")
        self.assertEqual(_git(self.repo, "rev-parse", "HEAD"), before, "main did not move")
        self.assertEqual(self.gated, [], "refused before minutes of suite")
        self.assertTrue(path.exists(), "the worktree is kept, so the task can undo it")

    async def test_case_and_dot_segments_do_not_hide_a_protected_path(self):
        await self._branch({"DOCS/SOUL.MD": "a second soul\n"})
        landed = await self.manager.land("t1")
        self.assertFalse(landed.ok)
        self.assertIn("docs/SOUL.md", landed.detail)

    async def test_deleting_a_protected_file_is_a_change_too(self):
        await self._branch({"docs/SOUL.md": None})
        self.assertFalse((await self.manager.land("t1")).ok)

    async def test_editing_an_existing_test_of_a_protected_package_is_refused(self):
        await self._branch({"tests/simorgh/execution/test_old.py": "def test_old():\n    pass\n"})
        landed = await self.manager.land("t1")
        self.assertFalse(landed.ok)
        self.assertIn("tests/simorgh/execution/test_old.py", landed.detail)

    async def test_a_conftest_beside_a_protected_package_is_refused(self):
        await self._branch({"tests/simorgh/execution/conftest.py": "x = 1\n"})
        self.assertFalse((await self.manager.land("t1")).ok)

    async def test_no_list_from_guardian_lands_nothing(self):
        async def silent():
            return None

        self.manager.protected = silent
        await self._branch({"simorgh/memory/store.py": "STORE = 2\n"})
        landed = await self.manager.land("t1")
        self.assertFalse(landed.ok)
        self.assertIn("guardian:protected", landed.detail)


class AnAllowedDiffLands(_Case):
    async def test_an_ordinary_diff_lands(self):
        await self._branch({"simorgh/memory/store.py": "STORE = 2\n"})
        landed = await self.manager.land("t1")
        self.assertTrue(landed.ok, landed.detail)
        self.assertEqual((self.repo / "simorgh" / "memory" / "store.py").read_text(), "STORE = 2\n")
        self.assertEqual(len(self.gated), 1)

    async def test_a_new_test_beside_a_protected_package_lands_as_guardian_allows_it(self):
        await self._branch({"tests/simorgh/execution/test_new_regression.py": "def test_it():\n    assert True\n"})
        landed = await self.manager.land("t1")
        self.assertTrue(landed.ok, landed.detail)


class TheMatchIsGuardians(unittest.TestCase):
    def test_hits(self):
        changes = [("M", "simorgh/memory/x.py"), ("A", "simorgh/kernel/new.py"), ("D", "sim.sh"),
                   ("A", "tests/simorgh/guardian/test_a.py"), ("M", "tests/simorgh/guardian/test_b.py"),
                   ("A", "tests/simorgh/guardian/__init__.py"), ("A", "agents/new.md")]
        hits = dict(protected_hits(changes, DEFAULT_PROTECTED_SUBJECTS))
        self.assertEqual(set(hits), {"simorgh/kernel/new.py", "sim.sh", "tests/simorgh/guardian/test_b.py",
                                     "tests/simorgh/guardian/__init__.py", "agents/new.md"})

    def test_the_same_exemption_as_guardians_rule(self):
        """For an added file under a protected package's tests, the landing
        check and Guardian's `_a_new_test_beside` agree."""
        import asyncio

        from simorgh.guardian.api import DecisionContext, Proposal, ToolInfo
        from simorgh.guardian.config import Config
        from simorgh.guardian.posture import Posture
        from simorgh.guardian.rules import ProtectedRule

        ctx = DecisionContext(now=0.0, system_state="running", posture=Posture(level="guarded", baseline="guarded"),
                              config=Config(), tool=ToolInfo("apply_source_patch", False, "reversible"))
        for path in ("tests/simorgh/execution/test_zz_never_exists.py", "tests/simorgh/execution/conftest.py",
                     "tests/simorgh/execution/helper_zz.py", "simorgh/execution/test_zz.py"):
            proposal = Proposal("a", "apply_source_patch", {"path": path, "content": "x"}, {}, "reversible", "t", "t")
            guardian_allows = asyncio.run(ProtectedRule().evaluate(proposal, ctx)).kind != "deny"
            landing_allows = not protected_hits([("A", path)], DEFAULT_PROTECTED_SUBJECTS)
            self.assertEqual(landing_allows, guardian_allows, path)


class TheServiceReadsGuardiansStream(unittest.IsolatedAsyncioTestCase):
    async def test_the_last_subjects_event_wins_and_none_means_unknown(self):
        from types import SimpleNamespace

        from simorgh.execution.service import GUARDIAN_PROTECTED_STREAM, Service

        events: list[Event] = []

        class _Ledger:
            async def read(self, stream, **kw):
                return [e for e in events if e.stream == stream]

        service = Service()
        service._ctx = SimpleNamespace(ledger=_Ledger())  # noqa: SLF001
        self.assertIsNone(await service._guardian_protected_subjects())  # noqa: SLF001
        for subjects in (["old/"], ["simorgh/guardian/", "docs/SOUL.md"]):
            events.append(Event(stream=GUARDIAN_PROTECTED_STREAM, type="subjects", ts=1.0, trace_id="",
                                causation_id=None, payload={"protected_subjects": subjects}))
        self.assertEqual(await service._guardian_protected_subjects(),  # noqa: SLF001
                         ("simorgh/guardian/", "docs/SOUL.md"))


if __name__ == "__main__":
    unittest.main()
