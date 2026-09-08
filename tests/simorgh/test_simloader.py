"""The Sim loader: known-good tags, gated boots, bounded rollback.

`simloader.py` is deliberately stdlib-only and never imports `simorgh`,
so these tests drive it as a module against a throwaway git repo, with
the gate stubbed -- the gate is a subprocess of pytest and the trial
suite, which is not something a unit test should spawn.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_LOADER = Path(__file__).resolve().parents[2] / "simloader.py"
_spec = importlib.util.spec_from_file_location("simloader", _LOADER)
simloader = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(simloader)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=T", *args],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()


class _Repo:
    def __init__(self, root: Path) -> None:
        self.path = root / "repo"
        self.path.mkdir()
        _git(self.path, "init", "-q")
        self.commit("one")

    def commit(self, name: str) -> str:
        (self.path / f"{name}.txt").write_text(name)
        _git(self.path, "add", "-A")
        _git(self.path, "commit", "-qm", name)
        return _git(self.path, "rev-parse", "--short", "HEAD")


class LoaderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.repo = _Repo(self.root)
        self.notes = self.root / "notes"

    def _gate(self, verdicts):
        """Stub the gate with a scripted sequence of (ok, why)."""
        it = iter(verdicts)
        return mock.patch.object(simloader, "run_gate", side_effect=lambda *a, **k: next(it))

    # -- tags ---------------------------------------------------------------
    def test_no_tags_means_no_known_good(self):
        self.assertEqual(simloader.good_tags(self.repo.path), [])

    def test_tags_are_numbered_and_ordered(self):
        for n in (3, 1, 2):
            _git(self.repo.path, "tag", f"sim-good-{n:04d}")
        self.assertEqual([n for n, _ in simloader.good_tags(self.repo.path)], [1, 2, 3])
        self.assertEqual(simloader.next_tag(self.repo.path), "sim-good-0004")

    def test_unrelated_tags_are_ignored(self):
        _git(self.repo.path, "tag", "v1.0")
        _git(self.repo.path, "tag", "sim-good-junk")
        self.assertEqual(simloader.good_tags(self.repo.path), [])

    # -- bless --------------------------------------------------------------
    def test_a_green_gate_tags_head(self):
        with self._gate([(True, "green")]):
            rc = simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
        self.assertEqual(rc, 0)
        self.assertEqual([t for _, t in simloader.good_tags(self.repo.path)], ["sim-good-0001"])

    def test_a_red_gate_does_not_tag(self):
        with self._gate([(False, "unit suite failed")]):
            rc = simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
        self.assertEqual(rc, 1)
        self.assertEqual(simloader.good_tags(self.repo.path), [])
        notes = (self.notes / "decisions.jsonl").read_text()
        self.assertIn("bless_refused", notes)

    def test_bless_refuses_a_dirty_tree(self):
        """Sim commits and the loader tags: a tag must name a commit, so
        an uncommitted change can never be blessed by accident."""
        (self.repo.path / "one.txt").write_text("edited, not committed")
        with self._gate([(True, "green")]):
            rc = simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
        self.assertEqual(rc, 2)
        self.assertEqual(simloader.good_tags(self.repo.path), [])

    def test_blessing_the_same_commit_twice_is_a_no_op(self):
        with self._gate([(True, "green"), (True, "green")]):
            simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
            simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
        self.assertEqual(len(simloader.good_tags(self.repo.path)), 1)

    # -- rollback -----------------------------------------------------------
    def test_rollback_steps_to_the_previous_good_tag(self):
        first = self.repo.commit("two")
        _git(self.repo.path, "tag", "sim-good-0001")
        self.repo.commit("three")
        _git(self.repo.path, "tag", "sim-good-0002")
        rc = simloader.cmd_rollback(self.repo.path, self.notes, reason="tests red")
        self.assertEqual(rc, 0)
        self.assertEqual(simloader.head(self.repo.path), first)
        last = json.loads((self.notes / "last_rollback.json").read_text())
        self.assertEqual(last["to"], "sim-good-0001")
        self.assertEqual(last["reason"], "tests red")

    def test_an_untracked_file_does_not_block_a_bless(self):
        """Dirty means tracked changes. A paper the creator dropped in
        `papers/`, or a scratch script, is nothing a rollback can lose
        and nothing Sim committed (live: the first real bless was
        refused for exactly such a PDF, 2026-09-07)."""
        (self.repo.path / "papers").mkdir()
        (self.repo.path / "papers" / "a.pdf").write_bytes(b"%PDF")
        self.assertFalse(simloader.is_dirty(self.repo.path))
        self.assertEqual(simloader.untracked(self.repo.path), ["papers/a.pdf"])
        with self._gate([(True, "green")]):
            rc = simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
        self.assertEqual(rc, 0)
        self.assertEqual([t for _n, t in simloader.good_tags(self.repo.path)], ["sim-good-0001"])

    def test_rollback_refuses_a_dirty_tree(self):
        """A rollback checks out another commit; it must never discard a
        human's uncommitted work to do it."""
        _git(self.repo.path, "tag", "sim-good-0001")
        self.repo.commit("two")
        _git(self.repo.path, "tag", "sim-good-0002")
        (self.repo.path / "one.txt").write_text("edited, not committed")
        self.assertEqual(simloader.cmd_rollback(self.repo.path, self.notes, reason="x"), 2)

    def test_rollback_with_nothing_older_says_so(self):
        _git(self.repo.path, "tag", "sim-good-0001")
        self.assertEqual(simloader.cmd_rollback(self.repo.path, self.notes, reason="x"), 1)

    # -- run ----------------------------------------------------------------
    def test_run_rolls_back_until_the_gate_passes_then_hands_off(self):
        good = self.repo.commit("two")
        _git(self.repo.path, "tag", "sim-good-0001")
        self.repo.commit("three-broken")
        _git(self.repo.path, "tag", "sim-good-0002")
        handed_off = {}

        def fake_sim(repo, notes, args):
            handed_off["at"] = simloader.head(repo)
            return 0

        with self._gate([(False, "unit suite failed"), (True, "green")]), \
             mock.patch.object(simloader, "launch_sim", side_effect=fake_sim):
            rc = simloader.cmd_run(
                self.repo.path, self.notes, full=False, timeout_s=10, max_rollbacks=3,
                watchdog_s=60, sim_args=[],
            )
        self.assertEqual(rc, 0)
        self.assertEqual(handed_off["at"], good, "Sim ran from the wrong commit")

    def test_run_gives_up_after_max_rollbacks(self):
        """Bounded, as asked: an endless walk backwards is not recovery."""
        for name in ("two", "three", "four"):
            self.repo.commit(name)
            _git(self.repo.path, "tag", simloader.next_tag(self.repo.path))
        with self._gate([(False, "red")] * 10), \
             mock.patch.object(simloader, "launch_sim") as sim:
            rc = simloader.cmd_run(
                self.repo.path, self.notes, full=False, timeout_s=10, max_rollbacks=2,
                watchdog_s=60, sim_args=[],
            )
        self.assertEqual(rc, 3)
        sim.assert_not_called()
        decisions = (self.notes / "decisions.jsonl").read_text()
        self.assertEqual(decisions.count('"rollback"'), 2)

    def test_a_green_gate_on_an_untagged_head_tags_it(self):
        with self._gate([(True, "green")]), \
             mock.patch.object(simloader, "launch_sim", return_value=0):
            simloader.cmd_run(
                self.repo.path, self.notes, full=False, timeout_s=10, max_rollbacks=3,
                watchdog_s=60, sim_args=[],
            )
        self.assertEqual(len(simloader.good_tags(self.repo.path)), 1)

    def test_a_crash_inside_the_watchdog_is_a_bad_boot(self):
        _git(self.repo.path, "tag", "sim-good-0001")
        self.repo.commit("two")
        _git(self.repo.path, "tag", "sim-good-0002")
        with self._gate([(True, "green")]), \
             mock.patch.object(simloader, "launch_sim", return_value=1):
            rc = simloader.cmd_run(
                self.repo.path, self.notes, full=False, timeout_s=10, max_rollbacks=3,
                watchdog_s=60, sim_args=[],
            )
        self.assertEqual(rc, 4)
        self.assertIn("watchdog", (self.notes / "decisions.jsonl").read_text())
        self.assertEqual(simloader.head(self.repo.path), simloader.tag_of(self.repo.path, "sim-good-0001"))


class LoaderIsIndependentTestCase(unittest.TestCase):
    def test_it_never_imports_the_package_it_boots(self):
        """The one property a bootloader must have."""
        source = _LOADER.read_text()
        self.assertNotIn("import simorgh", source)
        self.assertNotIn("from simorgh", source)


if __name__ == "__main__":
    unittest.main()
