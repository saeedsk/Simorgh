"""The Sim loader: known-good tags, gated boots, bounded rollback.

`simloader.py` is deliberately stdlib-only and never imports `simorgh`,
so these tests drive it as a module against a throwaway git repo, with
the gate stubbed -- the gate is a subprocess of pytest and the trial
suite, which is not something a unit test should spawn.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
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

    def test_full_still_runs_the_gate_on_an_already_tagged_commit(self):
        """`bless --full` used to return 0 immediately for a commit that
        already carried a tag, printing "is already sim-good-0003" and
        exiting green. On screen that is indistinguishable from the full
        gate passing -- and it had not run. The tag came from the unit
        suite alone, so the trial suite, the gate that has caught every
        real blocker in this project, was skipped in silence
        (2026-09-08)."""
        calls = []

        def _gate(*a, **k):
            calls.append(k.get("full"))
            return True, "unit suite green; trials 3/3"

        with mock.patch.object(simloader, "run_gate", side_effect=_gate):
            simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
            rc = simloader.cmd_bless(self.repo.path, self.notes, full=True, timeout_s=10)

        self.assertEqual(rc, 0)
        self.assertEqual(calls, [False, True], "the second bless must actually run the full gate")
        self.assertEqual(len(simloader.good_tags(self.repo.path)), 1, "and must not add a second tag")
        self.assertIn("full_gate_passed", (self.notes / "decisions.jsonl").read_text())

    def test_a_failed_full_gate_reports_but_leaves_the_tag_standing(self):
        """The tag was earned by the unit suite and the unit suite still
        passes. Removing it would roll the system back for a failure in
        a gate it was never granted for; saying nothing would hide a
        real failure. So: exit 1, and say both things."""
        with self._gate([(True, "green"), (False, "trial 2/3 failed")]):
            simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
            rc = simloader.cmd_bless(self.repo.path, self.notes, full=True, timeout_s=10)

        self.assertEqual(rc, 1)
        self.assertEqual(len(simloader.good_tags(self.repo.path)), 1)
        self.assertIn("full_gate_failed", (self.notes / "decisions.jsonl").read_text())

    def test_a_plain_bless_of_a_tagged_commit_is_still_a_no_op(self):
        """The cheap path must stay cheap: `bless` with no flag on an
        already-good commit still runs nothing."""
        calls = []

        def _gate(*a, **k):
            calls.append(k.get("full"))
            return True, "green"

        with mock.patch.object(simloader, "run_gate", side_effect=_gate):
            simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
            rc = simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)

        self.assertEqual(rc, 0)
        self.assertEqual(calls, [False], "a plain re-bless must not run the gate again")

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

    def test_a_restart_exit_code_re_gates_and_hands_off_again(self):
        """The `restart` REPL command, end to end at this layer: Sim
        exits `RESTART_EXIT_CODE` once (asking to come back up on
        whatever is on disk now, not to be done for good), and `cmd_run`
        gates the checkout again and launches it again, rather than
        returning to `sim.sh` the way every other non-zero exit does."""
        commits = []

        def fake_sim(repo, notes, args):
            commits.append(simloader.head(repo))
            return simloader.RESTART_EXIT_CODE if len(commits) == 1 else 0

        with self._gate([(True, "green"), (True, "green")]), \
             mock.patch.object(simloader, "launch_sim", side_effect=fake_sim):
            rc = simloader.cmd_run(
                self.repo.path, self.notes, full=False, timeout_s=10, max_rollbacks=3,
                watchdog_s=60, sim_args=[],
            )
        self.assertEqual(rc, 0)
        self.assertEqual(len(commits), 2, "Sim should have been handed off to twice")
        self.assertIn("restart", (self.notes / "decisions.jsonl").read_text())

    def test_a_restart_is_not_treated_as_a_bad_boot(self):
        """`RESTART_EXIT_CODE` is non-zero, but it must never trip the
        watchdog's "bad boot, roll back" path -- it means the opposite of
        a crash."""
        with self._gate([(True, "green"), (True, "green")]), \
             mock.patch.object(simloader, "launch_sim",
                                side_effect=[simloader.RESTART_EXIT_CODE, 0]):
            rc = simloader.cmd_run(
                self.repo.path, self.notes, full=False, timeout_s=10, max_rollbacks=3,
                watchdog_s=9999, sim_args=[],  # a long watchdog: a real crash here would trip it
            )
        self.assertEqual(rc, 0)
        self.assertNotIn("watchdog", (self.notes / "decisions.jsonl").read_text())


    # -- the gate is not re-run for source it already passed -----------------
    def _run(self, **kw):
        return simloader.cmd_run(self.repo.path, self.notes, full=kw.pop("full", False), timeout_s=10,
                                 max_rollbacks=3, watchdog_s=60, sim_args=[], **kw)

    def _green_once(self, **kw):
        with self._gate([(True, "green")]), mock.patch.object(simloader, "launch_sim", return_value=0):
            self.assertEqual(self._run(**kw), 0)

    def test_an_unchanged_clean_checkout_boots_without_rerunning_the_gate(self):
        """The creator, 2026-09-14: the gate took seven minutes on a boot
        of source it had already judged."""
        self._green_once()
        with mock.patch.object(simloader, "run_gate") as gate, \
             mock.patch.object(simloader, "launch_sim", return_value=0) as sim:
            self.assertEqual(self._run(), 0)
        gate.assert_not_called()
        sim.assert_called_once()
        self.assertIn("gate_reused", (self.notes / "decisions.jsonl").read_text())

    def test_a_new_commit_runs_the_gate_again(self):
        self._green_once()
        self.repo.commit("two")
        with mock.patch.object(simloader, "run_gate", return_value=(True, "green")) as gate, \
             mock.patch.object(simloader, "launch_sim", return_value=0):
            self._run()
        gate.assert_called_once()

    def test_an_uncommitted_change_runs_the_gate_again(self):
        self._green_once()
        (self.repo.path / "one.txt").write_text("edited, not committed")
        with mock.patch.object(simloader, "run_gate", return_value=(True, "green")) as gate, \
             mock.patch.object(simloader, "launch_sim", return_value=0):
            self._run()
        gate.assert_called_once()

    def test_untracked_code_runs_the_gate_again(self):
        self._green_once()
        (self.repo.path / "helper.py").write_text("x = 1\n")
        with mock.patch.object(simloader, "run_gate", return_value=(True, "green")) as gate, \
             mock.patch.object(simloader, "launch_sim", return_value=0):
            self._run()
        gate.assert_called_once()

    def test_a_unit_only_pass_does_not_stand_in_for_full(self):
        self._green_once()
        with mock.patch.object(simloader, "run_gate", return_value=(True, "green")) as gate, \
             mock.patch.object(simloader, "launch_sim", return_value=0):
            self._run(full=True)
        gate.assert_called_once()

    def test_force_gate_runs_it_anyway(self):
        self._green_once()
        with mock.patch.object(simloader, "run_gate", return_value=(True, "green")) as gate, \
             mock.patch.object(simloader, "launch_sim", return_value=0):
            self._run(force_gate=True)
        gate.assert_called_once()

    def test_a_failed_gate_is_never_remembered_as_green(self):
        with self._gate([(False, "red")] * 5), mock.patch.object(simloader, "launch_sim", return_value=0):
            self._run()
        self.assertFalse((self.notes / simloader.GREEN_FILE).exists())

    # -- the gate runs the core tests, not every feature's --------------------
    def _gate_argv(self, **kw) -> list[str]:
        seen = {}

        def _stream(argv, **_):
            seen["argv"] = argv
            return 0, "12 passed in 1.0s"

        with mock.patch.object(simloader, "stream", side_effect=_stream):
            simloader.run_gate(self.repo.path, full=False, timeout_s=10, notes=self.notes, **kw)
        return seen["argv"]

    def test_the_gate_runs_the_core_tests_without_live_ones(self):
        """The creator, 2026-09-14: the gate ran all 5,969 tests in eight
        minutes, cameras and TV included, and would fail a boot with the
        network down."""
        (self.repo.path / "tests" / "simorgh" / "kernel").mkdir(parents=True)
        (self.repo.path / "tests" / "simorgh" / "execution" / "home").mkdir(parents=True)
        argv = self._gate_argv()
        self.assertIn("tests/simorgh/kernel", argv)
        self.assertNotIn("tests", argv)
        self.assertEqual(argv[argv.index("not live") - 1], "-m", "the marker filter, not python's -m")
        self.assertIn("--ignore=tests/simorgh/execution/home", argv)
        self.assertNotIn("tests/simorgh/voice", argv, "a path the checkout lacks is not passed")

    def test_all_tests_runs_every_test(self):
        (self.repo.path / "tests" / "simorgh" / "kernel").mkdir(parents=True)
        self.assertEqual(self._gate_argv(all_tests=True)[-1], "tests")

    def test_a_checkout_without_the_core_paths_still_runs_something(self):
        self.assertEqual(self._gate_argv()[-1], "tests")

    def test_a_whole_suite_count_is_not_the_core_gates_baseline(self):
        simloader.write_baseline(self.notes, 5969, "all")
        self.assertIsNone(simloader.read_baseline(self.notes, "core"))
        simloader.write_baseline(self.notes, 2958, "core", seconds=41.0)
        self.assertEqual(simloader.read_baseline(self.notes, "core"), 2958)
        self.assertEqual(simloader.read_baseline(self.notes, "all"), 5969)

    def test_a_core_pass_does_not_stand_in_for_all_tests(self):
        self._green_once()
        with mock.patch.object(simloader, "run_gate", return_value=(True, "green")) as gate, \
             mock.patch.object(simloader, "launch_sim", return_value=0):
            self._run(all_tests=True)
        gate.assert_called_once()

    # -- a restart reloads the loader itself ----------------------------------
    def test_a_restart_reloads_the_loader_before_gating_again(self):
        """The loader in memory is the one that started; without this a
        `restart` gated with old loader code."""
        class _Execd(Exception):
            pass

        def _reload():
            raise _Execd()

        with self._gate([(True, "green")]), \
             mock.patch.object(simloader, "launch_sim", return_value=simloader.RESTART_EXIT_CODE) as sim:
            with self.assertRaises(_Execd):
                self._run(reload_loader=_reload)
        sim.assert_called_once()

    def test_a_failed_reload_falls_back_to_gating_in_this_process(self):
        with self._gate([(True, "green")]), \
             mock.patch.object(simloader, "launch_sim", side_effect=[simloader.RESTART_EXIT_CODE, 0]) as sim:
            self.assertEqual(self._run(reload_loader=lambda: None), 0)
        self.assertEqual(sim.call_count, 2)

    def test_main_reloads_with_the_same_arguments(self):
        calls = []

        class _Execd(Exception):
            pass

        def _execv(executable, command):
            calls.append((executable, command))
            raise _Execd()

        argv = ["run", "--repo", str(self.repo.path), "--notes", str(self.notes)]
        with self._gate([(True, "green")]), \
             mock.patch.object(simloader, "launch_sim", return_value=simloader.RESTART_EXIT_CODE), \
             mock.patch.object(simloader.os, "execv", side_effect=_execv):
            with self.assertRaises(_Execd):
                simloader.main(argv)
        executable, command = calls[0]
        self.assertEqual(executable, sys.executable, "no sim.sh in this repo: the loader itself")
        self.assertEqual(command[2:], argv)

class TheLookTestCase(unittest.TestCase):
    """A terminal gets the card, icons and a moving bar; a log or a pipe
    gets the plain `[simloader]` lines it always had (2026-09-14)."""

    def test_plain_output_is_unchanged(self):
        self.assertEqual(simloader.format_say("gate passed", "ok", fancy=False), "[simloader] gate passed")
        self.assertIn("[simloader] ── gate: core tests ", simloader.format_rule("gate: core tests", fancy=False))
        self.assertEqual(simloader.format_card([("repo", "/r")], fancy=False), "[simloader] repo /r")

    def test_a_terminal_gets_an_icon_per_outcome(self):
        self.assertIn("✓", simloader.format_say("gate passed", "ok", fancy=True))
        self.assertIn("✗", simloader.format_say("gate FAILED", "fail", fancy=True))
        self.assertIn("↺", simloader.format_say("rolled back", "warn", fancy=True))
        self.assertIn("⏺", simloader.format_rule("gate: core tests", fancy=True))

    def test_the_card_is_a_closed_box(self):
        import re

        card = simloader.format_card([("repo", "~/ws/Simorgh"), ("HEAD", "d5703da  main"), ("gate", "core tests")],
                                     fancy=True)
        lines = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in card.splitlines()]
        self.assertTrue(lines[0].startswith("╭") and lines[0].endswith("╮"))
        self.assertTrue(lines[-1].startswith("╰") and lines[-1].endswith("╯"))
        self.assertEqual(len({len(line) for line in lines}), 1, f"a ragged edge: {[len(l) for l in lines]}")

    def test_the_bar_says_how_long_is_left_when_it_knows(self):
        line = simloader.format_progress(label="tests", fraction=0.5, elapsed=20, expected_s=50, fancy=True)
        self.assertIn("50%", line)
        self.assertIn("~0:30 left", line)
        plain = simloader.format_progress(label="tests", fraction=0.5, elapsed=20, expected_s=50, fancy=False)
        self.assertTrue(plain.startswith("[simloader] "))
        self.assertNotIn("\\x1b", plain)

class LoaderIsIndependentTestCase(unittest.TestCase):
    def test_it_never_imports_the_package_it_boots(self):
        """The one property a bootloader must have."""
        source = _LOADER.read_text()
        self.assertNotIn("import simorgh", source)
        self.assertNotIn("from simorgh", source)


class NotesPathTestCase(unittest.TestCase):
    """The default `--notes` directory must be scoped to the repo being
    gated, never to the invoking process's real `$HOME`.

    Was `DEFAULT_NOTES = Path("~/.simorgh/loader").expanduser()`: a
    sandbox copy of this repo has the operator's real home too, so an
    unqualified `bless`/`run` there wrote straight into that person's
    actual `~/.simorgh/loader/decisions.jsonl` -- corrupting the real
    audit trail with sandbox-only decisions (observer, 2026-09-08,
    reproduced live). `--repo` already resolves correctly per-checkout,
    so the default must be anchored there instead, making the escape
    structurally impossible rather than merely unlikely.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _Repo(Path(self._tmp.name))

    def _resolved_notes(self, *, home: Path) -> Path:
        captured: dict[str, Path] = {}

        def _fake_status(repo, notes):
            captured["notes"] = notes
            return 0

        env = dict(os.environ, HOME=str(home))
        with mock.patch.object(simloader, "cmd_status", side_effect=_fake_status), \
             mock.patch.dict(simloader.os.environ, env, clear=False):
            rc = simloader.main(["status", "--repo", str(self.repo.path)])
        self.assertEqual(rc, 0)
        return captured["notes"]

    def test_default_notes_live_under_the_repo_not_home(self):
        real_home = Path(self._tmp.name) / "definitely-not-the-repo"
        real_home.mkdir()
        notes = self._resolved_notes(home=real_home)
        self.assertEqual(notes, self.repo.path.resolve() / simloader.NOTES_DIRNAME)
        self.assertFalse(str(notes).startswith(str(real_home.resolve())))

    def test_default_notes_are_unaffected_by_which_home_is_set(self):
        """However `$HOME` is set at invocation time, the default must
        resolve identically -- it must not consult `$HOME`/`Path.home()`
        at all."""
        home_a = Path(self._tmp.name) / "home-a"
        home_b = Path(self._tmp.name) / "home-b"
        home_a.mkdir()
        home_b.mkdir()
        self.assertEqual(self._resolved_notes(home=home_a), self._resolved_notes(home=home_b))

    def test_an_explicit_notes_flag_still_wins(self):
        explicit = Path(self._tmp.name) / "explicit-notes"
        captured: dict[str, Path] = {}

        def _fake_status(repo, notes):
            captured["notes"] = notes
            return 0

        with mock.patch.object(simloader, "cmd_status", side_effect=_fake_status):
            simloader.main(["status", "--repo", str(self.repo.path), "--notes", str(explicit)])
        self.assertEqual(captured["notes"], explicit)

    def test_a_real_bless_writes_notes_only_under_the_repo(self):
        """End-to-end, through `write_note`: no file lands under `$HOME`."""
        home = Path(self._tmp.name) / "home-for-real-bless"
        home.mkdir()
        env = dict(os.environ, HOME=str(home))
        with mock.patch.object(simloader, "run_gate", return_value=(False, "unit suite failed: boom")), \
             mock.patch.dict(simloader.os.environ, env, clear=False):
            rc = simloader.main(["bless", "--repo", str(self.repo.path)])
        self.assertEqual(rc, 1)
        self.assertTrue((self.repo.path / simloader.NOTES_DIRNAME / "decisions.jsonl").exists())
        self.assertEqual(list(home.rglob("*")), [], "bless must never write under $HOME")


if __name__ == "__main__":
    unittest.main()


class ProgressTestCase(unittest.TestCase):
    """The gate is minutes of someone else's silence. The creator,
    watching a real run: "simloader is now not showing any activity for
    past 60 seconds ... user doesn't understand what is happening"."""

    def test_the_bar_fills_and_is_bounded(self):
        self.assertEqual(simloader.bar(0.0, width=4), "░░░░")
        self.assertEqual(simloader.bar(0.5, width=4), "██░░")
        self.assertEqual(simloader.bar(1.0, width=4), "████")
        self.assertEqual(simloader.bar(9.0, width=4), "████")
        self.assertEqual(simloader.bar(-1.0, width=4), "░░░░")

    def test_pytest_progress_reads_the_percentage_and_counts(self):
        p = simloader.PytestProgress(started=0.0)
        p.feed("........................ [  8%]\n")
        self.assertAlmostEqual(p.fraction, 0.08)
        self.assertEqual(p.tests, 24)
        self.assertIn("24 tests", p.detail)
        p.feed("....F... [ 50%]\n")
        self.assertAlmostEqual(p.fraction, 0.5)
        self.assertIn("failing", p.detail)

    def test_trial_progress_counts_finished_trials(self):
        p = simloader.TrialProgress(started=0.0, total=4)
        p.feed("  → read_file: something  ok\n")
        self.assertIn("trial 1/4", p.detail)
        p.feed("  PASS  create-a-file  completed  20s\n")
        self.assertEqual(p.done, 1)
        self.assertAlmostEqual(p.fraction, 0.25)

    def test_the_trial_count_is_read_from_the_suite_source(self):
        repo = Path(__file__).resolve().parents[2]
        self.assertGreaterEqual(simloader.trial_count(repo), 6)
        self.assertEqual(simloader.trial_count(Path("/nonexistent")), 6)

    def test_stream_returns_the_childs_output_and_code(self):
        progress = simloader.PytestProgress(started=0.0)
        code, out = simloader.stream(
            [sys.executable, "-c", "print('hello'); raise SystemExit(3)"],
            cwd=Path.cwd(), timeout_s=30, progress=progress,
        )
        self.assertEqual(code, 3)
        self.assertIn("hello", out)

    def test_stream_kills_a_child_that_overruns(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            simloader.stream(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=Path.cwd(), timeout_s=1, progress=simloader.PytestProgress(started=0.0),
            )


class SkipKeyTestCase(unittest.TestCase):
    """The creator: "in simloader allow user to bypass the test by
    pressing key and let sim to load". A skip boots anyway, is
    announced, and must never produce a known-good tag."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _Repo(Path(self._tmp.name))
        self.notes = Path(self._tmp.name) / "notes"

    def test_a_skip_is_not_a_pass_and_tags_nothing(self):
        with mock.patch.object(simloader, "run_gate", return_value=(True, f"{simloader.SKIP_SENTINEL} during the unit suite")), \
             mock.patch.object(simloader, "launch_sim", return_value=0):
            rc = simloader.cmd_run(self.repo.path, self.notes, full=False, timeout_s=10,
                                   max_rollbacks=1, watchdog_s=1, sim_args=[])
        self.assertEqual(rc, 0)
        self.assertEqual(simloader.good_tags(self.repo.path), [])
        self.assertIn("gate_skipped", (self.notes / "decisions.jsonl").read_text())

    def test_a_real_pass_still_tags(self):
        with mock.patch.object(simloader, "run_gate", return_value=(True, "unit suite green")), \
             mock.patch.object(simloader, "launch_sim", return_value=0):
            simloader.cmd_run(self.repo.path, self.notes, full=False, timeout_s=10,
                              max_rollbacks=1, watchdog_s=1, sim_args=[])
        self.assertEqual([t for _n, t in simloader.good_tags(self.repo.path)], ["sim-good-0001"])

    def test_bless_never_offers_a_skip(self):
        source = _LOADER.read_text()
        self.assertIn("allow_skip=True", source)
        self.assertEqual(source.count("allow_skip=True"), 1, "only `run` may allow a skip")
        self.assertIn("run_gate(repo, full=full, timeout_s=timeout_s, notes=notes)", source)

    def test_the_watch_is_inert_without_a_terminal(self):
        watch = simloader.SkipWatch(enabled=True)
        with mock.patch.object(simloader.sys, "stdin", None):
            self.assertFalse(simloader.SkipWatch(enabled=True).enabled)
        with watch:
            pass
        self.assertFalse(simloader.SkipWatch(enabled=False).enabled)

    def test_a_pressed_key_stops_the_stream(self):
        class _AlwaysPressed:
            enabled = True

            def pressed(self):
                return True

        with self.assertRaises(simloader.GateSkipped):
            simloader.stream(
                [sys.executable, "-c", "import time; time.sleep(20)"],
                cwd=Path.cwd(), timeout_s=30, progress=simloader.PytestProgress(started=0.0),
                skip=_AlwaysPressed(),
            )


class TheGateCannotBeTalkedIntoPassingTestCase(unittest.TestCase):
    """What a change is allowed to do to the suite that judges it.

    Every transcript below was captured from a real `simloader.py bless`
    against a throwaway repo (observer, 2026-09-10). Each one ended, before
    the fix, with `[simloader] blessed <sha> as sim-good-000N  (unit suite
    green)` -- the cheapest way to pass this gate was to break the tests
    rather than fix the code.
    """

    def verdict(self, code, text, baseline=None):
        return simloader.unit_verdict(code, text, baseline=baseline)

    def test_an_honest_green_run_still_passes(self):
        ok, why, ran = self.verdict(0, "..\n2 passed in 0.65s\n")
        self.assertTrue(ok, why)
        self.assertEqual(ran, 2)

    def test_deleting_every_test_is_not_a_pass(self):
        """`git rm tests/test_*.py` -> pytest exit 5, "no tests ran"."""
        ok, why, ran = self.verdict(5, "no tests ran in 0.61s\n")
        self.assertFalse(ok)
        self.assertEqual(ran, 0)
        self.assertIn("no tests actually ran", why)

    def test_a_conftest_that_collects_nothing_is_not_a_pass(self):
        """`collect_ignore_glob = ["*"]`, or `addopts = -k nomatch`."""
        self.assertFalse(self.verdict(5, "no tests ran in 0.64s\n")[0])

    def test_a_blanket_skip_is_not_a_pass(self):
        """`pytest_collection_modifyitems` adding `pytest.mark.skip`:
        exit 0, and not one assertion was evaluated."""
        ok, why, _ran = self.verdict(0, "ss\n2 skipped in 0.62s\n")
        self.assertFalse(ok)
        self.assertIn("no tests actually ran", why)

    def test_a_forced_exit_code_does_not_beat_the_transcript(self):
        """`def pytest_sessionfinish(session, exitstatus):
        session.exitstatus = 0`. The loader printed "unit suite: 1
        failed, 1 passed" and blessed the commit on the very next line."""
        ok, why, _ran = self.verdict(0, ".F\nFAILED tests/test_real.py::test_bad\n1 failed, 1 passed in 0.62s\n")
        self.assertFalse(ok)
        self.assertIn("reported 1 failed", why)

    def test_a_collection_error_is_not_a_pass(self):
        ok, why, _ran = self.verdict(2, "ERROR tests/test_x.py\n1 error in 0.32s\n")
        self.assertFalse(ok)

    def test_the_suite_may_not_quietly_shrink(self):
        """A ratchet against the last green run, so removing most of the
        suite is refused even though what is left passes."""
        self.assertFalse(self.verdict(0, "..\n2 passed in 1.1s\n", baseline=3)[0])
        self.assertTrue(self.verdict(0, "." * 95 + "\n95 passed in 1.1s\n", baseline=100)[0])

    def test_the_summary_is_read_from_the_last_line_that_has_counts(self):
        text = "1 passed in prose that mentions 9 failed earlier\n\n7 passed, 2 skipped in 3.4s\n"
        self.assertEqual(simloader.unit_summary(text), {"passed": 7, "skipped": 2})

    def test_the_baseline_round_trips_and_survives_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "notes"
            self.assertIsNone(simloader.read_baseline(notes))
            simloader.write_baseline(notes, 2865)
            self.assertEqual(simloader.read_baseline(notes), 2865)
            (notes / simloader.BASELINE_FILES["core"]).write_text("{not json")
            self.assertIsNone(simloader.read_baseline(notes))


class TheTagMustMeanTheCommitTestCase(LoaderTestCase):
    """A tag is the loader's statement that it verified *that commit*."""

    def test_untracked_code_blocks_a_bless(self):
        """Live (2026-09-10): a commit whose test imported an untracked
        `helper.py`. `bless` ran the working tree -- "1 passed" -- and
        tagged the commit. A clean checkout of that tag cannot even
        collect: `ERROR tests/test_x.py ... 1 error`."""
        (self.repo.path / "helper.py").write_text("VALUE = 1\n")
        self.assertFalse(simloader.is_dirty(self.repo.path))
        self.assertEqual(simloader.untracked_code(self.repo.path), ["helper.py"])
        with self._gate([(True, "green")]):
            rc = simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10)
        self.assertEqual(rc, 2)
        self.assertEqual(simloader.good_tags(self.repo.path), [])

    def test_untracked_code_lets_sim_boot_but_earns_no_tag(self):
        """Refusing the boot would be worse than the disease: this tree
        did pass. Only the tag is withheld."""
        (self.repo.path / "helper.py").write_text("VALUE = 1\n")
        with self._gate([(True, "green")]), \
             mock.patch.object(simloader, "launch_sim", return_value=0) as launched:
            rc = simloader.cmd_run(
                self.repo.path, self.notes, full=False, timeout_s=10, max_rollbacks=3,
                watchdog_s=60, sim_args=[],
            )
        self.assertEqual(rc, 0)
        self.assertTrue(launched.called)
        self.assertEqual(simloader.good_tags(self.repo.path), [])
        self.assertIn("tag_withheld", (self.notes / "decisions.jsonl").read_text())

    def test_untracked_data_still_does_not_block_a_tag(self):
        (self.repo.path / "papers").mkdir()
        (self.repo.path / "papers" / "a.pdf").write_bytes(b"%PDF")
        (self.repo.path / "notes.txt").write_text("scratch")
        self.assertEqual(simloader.untracked_code(self.repo.path), [])
        with self._gate([(True, "green")]):
            self.assertEqual(simloader.cmd_bless(self.repo.path, self.notes, full=False, timeout_s=10), 0)


class ABrokenTagIsNotAKnownGoodImageTestCase(LoaderTestCase):
    def _break_a_tag(self) -> None:
        tree = _git(self.repo.path, "rev-parse", "HEAD^{tree}")
        _git(self.repo.path, "tag", "sim-good-0001", tree)

    def test_a_tag_that_is_not_a_commit_is_ignored(self):
        self._break_a_tag()
        self.assertEqual(simloader.good_tags(self.repo.path), [])
        self.assertEqual(simloader.broken_tags(self.repo.path), ["sim-good-0001"])

    def test_rollback_onto_a_broken_tag_reports_instead_of_crashing(self):
        """Before: `RuntimeError: git checkout -q sim-good-0001: fatal:
        Cannot switch branch to a non-commit`, an uncaught traceback out
        of the boot path with no note written."""
        self._break_a_tag()
        rc = simloader.cmd_rollback(self.repo.path, self.notes, reason="x")
        self.assertEqual(rc, 1)  # nothing older to roll back to

    def test_a_checkout_that_fails_is_reported_not_raised(self):
        _git(self.repo.path, "tag", "sim-good-0001")
        self.repo.commit("two")
        _git(self.repo.path, "tag", "sim-good-0002")
        with mock.patch.object(
            simloader, "git",
            side_effect=lambda *a, **k: (subprocess.CompletedProcess(a, 1, "", "fatal: nope")
                                         if a[0] == "checkout" else _real_git(*a, **k)),
        ):
            rc = simloader.cmd_rollback(self.repo.path, self.notes, reason="x")
        self.assertEqual(rc, 2)
        self.assertIn("rollback_failed", (self.notes / "decisions.jsonl").read_text())


_real_git = simloader.git


class CtrlCGivesSimTimeToStop(unittest.TestCase):
    """A Ctrl-C to the loader waits for Sim's orderly shutdown instead of
    SIGKILLing it 0.25 s in (2026-09-18 evaluation, B16)."""

    def test_the_child_finishes_its_shutdown_after_the_loader_gets_sigint(self):
        import os
        import signal
        import subprocess
        import sys
        import tempfile
        import time
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "clean-exit"
            child = (f"import time; time.sleep(1.2); open({str(marker)!r}, 'w').write('ok')")
            driver = (
                "import sys; sys.path.insert(0, {repo!r}); import simloader; from pathlib import Path; "
                "sys.exit(simloader.launch_sim(Path({tmp!r}), Path({tmp!r}), [], argv=[sys.executable, '-c', {child!r}], grace_s=10))"
            ).format(repo=str(Path(__file__).resolve().parents[2]), tmp=tmp, child=child)
            proc = subprocess.Popen([sys.executable, "-c", driver])
            time.sleep(0.5)
            os.kill(proc.pid, signal.SIGINT)  # the loader only; the child keeps shutting down
            code = proc.wait(timeout=20)
            self.assertTrue(marker.exists(), "the child was killed before it finished")
            self.assertEqual(code, 0)
