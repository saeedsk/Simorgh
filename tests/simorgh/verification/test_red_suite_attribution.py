"""The objection a task cannot answer.

Watched live twice, by two different observers, and left unfixed both
times: a patch task edited one file, ran the tests for it, they passed,
it committed. `full_suite_ran` failed it for running a narrower target
than the whole suite. It complied and ran the whole suite. The suite
was red for an unrelated reason. The check failed it again, and again,
and the task blocked having burned its whole revision budget with a
correct, committed change in the tree.

`full_suite_ran` could not attribute a suite failure to the change
under review, so once the suite was red for ANY reason its objection
was unanswerable.

These tests fix the two halves of the guarantee in place at once, with
a real git repo and a real pytest run rather than a stub, because the
whole question is whether a *measurement* can tell the two cases apart:

- an unrelated red suite no longer traps the task
- a real regression still fails, and still fails when it hides among
  unrelated failures
- "it was already red" is no excuse for a test the task itself owns,
  which is the false pass a naive "no new failures" rule would ship
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.verification.api import CheckContext, VerifyRequest
from simorgh.verification.checks import FullSuiteRanCheck
from simorgh.verification.config import VerificationConfig

_PASS = "def test_it():\n    assert True\n"
_FAIL = "def test_it():\n    assert False, 'red'\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)


class _Lab:
    """A tiny real repo whose base commit is already red.

    `tests_fake/test_unrelated.py` fails at the base commit and keeps
    failing -- someone else's problem, exactly the situation both
    observers watched trap a correct task. `tests_fake/test_subject.py`
    passes at the base commit; a test can break it in the working tree
    to play the part of a regression the change introduced.
    """

    def __enter__(self) -> "_Lab":
        self._tmp = tempfile.TemporaryDirectory(prefix="simorgh-attrib-test-")
        self.repo = Path(self._tmp.name) / "repo"
        (self.repo / "tests_fake").mkdir(parents=True)
        (self.repo / "tests_fake" / "test_unrelated.py").write_text(_FAIL)
        (self.repo / "tests_fake" / "test_subject.py").write_text(_PASS)
        (self.repo / "subject.py").write_text("VALUE = 1\n")
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "lab@local")
        _git(self.repo, "config", "user.name", "Lab")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        self.base_ref = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        self._cwd = os.getcwd()
        # `_baseline._repo_for` asks the current directory first, the way
        # a trial lab and a real run both put Sim's own repo there.
        os.chdir(self.repo)
        return self

    def __exit__(self, *exc: object) -> None:
        os.chdir(self._cwd)
        self._tmp.cleanup()


def _request(base_ref: str, failing: tuple[str, ...], written: list[str]) -> VerifyRequest:
    marker = f"[failed {len(failing)}: {' '.join(failing)}]"
    steps = [
        {"tool": "apply_source_patch", "ok": True, "phase": "act", "summary": "wrote it"},
        {"tool": "run_tests", "ok": False, "phase": "act",
         "summary": f"[ran target='tests']\n{marker}\n1 failed, 1 passed"},
        {"tool": "git_commit", "ok": True, "phase": "act", "summary": "committed"},
    ]
    return VerifyRequest(
        verification_id="v1", task_id="t1", kind="task",
        subject={"kind": "patch", "description": "d", "result": "done", "steps": steps,
                 "complete_log": True, "written_paths": written, "base_ref": base_ref},
    )


class TestRedSuiteAttribution(unittest.IsolatedAsyncioTestCase):
    async def _run(self, req: VerifyRequest):
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        check = FullSuiteRanCheck()
        self.assertTrue(check.applies(req))
        return await check.run(req, ctx)

    async def test_a_suite_red_before_the_session_no_longer_traps_the_task(self) -> None:
        with _Lab() as lab:
            result = await self._run(_request(
                lab.base_ref,
                ("tests_fake/test_unrelated.py::test_it",),
                ["subject.py"],
            ))
        self.assertEqual(result.status, "passed", result.detail)
        self.assertIn("introduced none of them", result.detail)
        self.assertEqual(result.evidence["introduced"], [])

    async def test_a_real_regression_still_fails(self) -> None:
        with _Lab() as lab:
            # Red on the tree, not only in the marker: a failure the
            # quiet re-run cannot reproduce is load, not a regression.
            (lab.repo / "tests_fake" / "test_subject.py").write_text(_FAIL)
            result = await self._run(_request(
                lab.base_ref,
                ("tests_fake/test_subject.py::test_it",),
                ["subject.py"],
            ))
        self.assertEqual(result.status, "failed")
        self.assertIn("tests_fake/test_subject.py::test_it", result.detail)
        self.assertEqual(result.evidence["introduced"], ["tests_fake/test_subject.py::test_it"])

    async def test_a_regression_hiding_among_unrelated_failures_still_fails(self) -> None:
        """The case the whole design has to survive: the suite really was
        red before, AND this change really did break something."""
        with _Lab() as lab:
            (lab.repo / "tests_fake" / "test_subject.py").write_text(_FAIL)
            result = await self._run(_request(
                lab.base_ref,
                ("tests_fake/test_unrelated.py::test_it", "tests_fake/test_subject.py::test_it"),
                ["subject.py"],
            ))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.evidence["introduced"], ["tests_fake/test_subject.py::test_it"])

    async def test_a_task_that_fixed_nothing_is_not_excused_by_the_red_suite(self) -> None:
        """The second forbidden outcome. The failing test was already
        failing, so "no new failures" is true -- and it is a test of the
        very file this task wrote, so it is the work, not noise."""
        with _Lab() as lab:
            result = await self._run(_request(
                lab.base_ref,
                ("tests_fake/test_unrelated.py::test_it",),
                ["unrelated.py"],
            ))
        self.assertEqual(result.status, "failed")
        self.assertIn("still failing", result.detail)
        self.assertEqual(result.evidence["already_failing_and_owned"],
                         ["tests_fake/test_unrelated.py::test_it"])

    async def test_a_test_the_change_itself_added_counts_as_introduced(self) -> None:
        """A node id that does not exist at the base revision cannot have
        been failing there. It must not read as "already red"."""
        with _Lab() as lab:
            result = await self._run(_request(
                lab.base_ref,
                ("tests_fake/test_brand_new.py::test_it",),
                ["subject.py"],
            ))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.evidence["introduced"], ["tests_fake/test_brand_new.py::test_it"])


class TestEveryUnknownBlamesTheChange(unittest.IsolatedAsyncioTestCase):
    """No opinion means the check behaves exactly as it did before any of
    this existed. Each of these used to be the ONLY behaviour; none of
    them may now become a pass."""

    async def _run(self, req: VerifyRequest):
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        return await FullSuiteRanCheck().run(req, ctx)

    async def test_no_base_ref_falls_back_to_the_old_objection(self) -> None:
        req = _request("", ("tests_fake/test_unrelated.py::test_it",), ["subject.py"])
        result = await self._run(req)
        self.assertEqual(result.status, "failed")
        self.assertIn("FAILED", result.detail)

    async def test_an_unknown_base_ref_falls_back(self) -> None:
        with _Lab():
            result = await self._run(_request(
                "0" * 40, ("tests_fake/test_unrelated.py::test_it",), ["subject.py"]))
        self.assertEqual(result.status, "failed")
        self.assertIn("FAILED", result.detail)

    async def test_a_run_that_named_no_failing_tests_falls_back(self) -> None:
        with _Lab() as lab:
            req = _request(lab.base_ref, (), ["subject.py"])
            # No marker survives: the run failed without a short summary.
            req.subject["steps"][1]["summary"] = "[ran target='tests']\nINTERNALERROR"
            result = await self._run(req)
        self.assertEqual(result.status, "failed")
        self.assertIn("FAILED", result.detail)

    async def test_a_capped_failure_list_is_not_a_short_list(self) -> None:
        """A marker that says 200 failed and names 40 is not evidence
        about 200 tests. It has to read as unavailable."""
        with _Lab() as lab:
            req = _request(lab.base_ref, ("tests_fake/test_unrelated.py::test_it",), ["subject.py"])
            req.subject["steps"][1]["summary"] = (
                "[ran target='tests']\n[failed 200: tests_fake/test_unrelated.py::test_it]\n")
            result = await self._run(req)
        self.assertEqual(result.status, "failed")
        self.assertIn("FAILED", result.detail)


class TestOneUnrunnableIdDoesNotBlindTheWholeRun(unittest.IsolatedAsyncioTestCase):
    """A test the change ADDED must not carry every other failure with it.

    pytest treats a node id it cannot resolve as a USAGE error: exit 4,
    and nothing runs -- not the other arguments either. So a baseline
    run asked about `[an old failure, a test this change added]` ran
    neither, came back with no failures named, and every failure was
    scored as introduced. Since this project asks for a regression test
    with every fix, "the change added a test" is the ordinary case, and
    the escape hatch was therefore shut almost exactly when it was
    needed -- the same budget burn against a red suite, one layer down
    (observer, 2026-09-10).
    """

    async def _run(self, req: VerifyRequest):
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        return await FullSuiteRanCheck().run(req, ctx)

    async def test_an_added_test_does_not_make_an_old_failure_the_changes_fault(self) -> None:
        with _Lab() as lab:
            (lab.repo / "tests_fake" / "test_brand_new.py").write_text(_FAIL)
            result = await self._run(_request(
                lab.base_ref,
                ("tests_fake/test_unrelated.py::test_it", "tests_fake/test_brand_new.py::test_it"),
                ["subject.py"],
            ))
        self.assertEqual(result.status, "failed")
        # The added test is this change's own; the pre-existing failure
        # is not, and used to be blamed alongside it.
        self.assertEqual(result.evidence["introduced"], ["tests_fake/test_brand_new.py::test_it"])

    async def test_a_test_added_to_an_existing_file_is_the_same_case(self) -> None:
        with _Lab() as lab:
            (lab.repo / "tests_fake" / "test_subject.py").write_text(
                _PASS + "\ndef test_added_by_this_change():\n    assert False\n")
            result = await self._run(_request(
                lab.base_ref,
                ("tests_fake/test_unrelated.py::test_it",
                 "tests_fake/test_subject.py::test_added_by_this_change"),
                ["subject.py"],
            ))
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.evidence["introduced"],
                         ["tests_fake/test_subject.py::test_added_by_this_change"])


class TestAFailureThatCannotBeNamedIsNotExcused(unittest.IsolatedAsyncioTestCase):
    """The marker is the only thing this check knows about a red suite.

    A parametrized node id with a space in it -- `test_p[hello world]` --
    did not match the summary-line pattern at all, so the marker named
    the failures beside it and not that one, and said its count was the
    whole truth. Attribution then excused every id it was given, found
    nothing introduced, and PASSED a change that had broken a test:
    the exact false pass this check exists to make impossible. The
    marker now carries pytest's own count, so a list that lost an id
    reads back as unattributable (`contracts/pytestfailures.py`).
    """

    async def _run(self, req: VerifyRequest):
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        return await FullSuiteRanCheck().run(req, ctx)

    async def test_a_lost_node_id_is_not_a_pass(self) -> None:
        from simorgh.contracts.pytestfailures import marker_for

        output = ("FAILED tests_fake/test_unrelated.py::test_it - assert False\n"
                  "FAILED tests_fake/test_subject.py::test_p[hello world] - assert False\n"
                  "2 failed in 0.05s\n")
        with _Lab() as lab:
            req = _request(lab.base_ref, ("tests_fake/test_unrelated.py::test_it",), ["subject.py"])
            req.subject["steps"][1]["summary"] = f"[ran target='tests']\n{marker_for(output)}"
            result = await self._run(req)
        self.assertEqual(result.status, "failed", result.detail)
        self.assertIn("FAILED", result.detail)


if __name__ == "__main__":
    unittest.main()


class TestAFailureThatPassesAlone(unittest.IsolatedAsyncioTestCase):
    """Live, twice on 2026-09-11: a whole-suite run under heavy load
    failed a known-flaky interface test and two real-browser tests; the
    base run, a few tests alone, passed them; and a change that added
    one standalone module was told it "made tests fail that pass
    without it". The changed tree gets the same quiet re-run now."""

    async def _run(self, req: VerifyRequest):
        ctx = CheckContext(act=None, think=None, review=None, clock=None, config=VerificationConfig())
        return await FullSuiteRanCheck().run(req, ctx)

    async def test_a_test_green_on_the_quiet_rerun_is_flaky_not_introduced(self) -> None:
        with _Lab() as lab:
            # `test_subject.py` passes at base AND in the working tree; the
            # suite run claims it failed. That is load, not the change.
            req = _request(lab.base_ref, ("tests_fake/test_subject.py::test_it",), ["subject.py"])
            result = await self._run(req)
        self.assertEqual(result.status, "passed", result.detail)
        self.assertEqual(result.evidence["introduced"], [])
        self.assertEqual(result.evidence["flaky"], ["tests_fake/test_subject.py::test_it"])
        self.assertIn("passed when run again alone", result.detail)

    async def test_a_test_still_red_on_the_quiet_rerun_is_introduced(self) -> None:
        with _Lab() as lab:
            (lab.repo / "tests_fake" / "test_subject.py").write_text(_FAIL)
            req = _request(lab.base_ref, ("tests_fake/test_subject.py::test_it",), ["subject.py"])
            result = await self._run(req)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.evidence["introduced"], ["tests_fake/test_subject.py::test_it"])
        self.assertEqual(result.evidence["flaky"], [])

    async def test_the_rerun_happens_on_the_tree_the_subject_names(self) -> None:
        """A worktree session names its tree; the quiet re-run must look
        there, not at the process's cwd."""
        with _Lab() as lab:
            other = Path(lab._tmp.name) / "worktree"
            shutil.copytree(lab.repo, other, ignore=shutil.ignore_patterns(".git"))
            (other / "tests_fake" / "test_subject.py").write_text(_FAIL)
            req = _request(lab.base_ref, ("tests_fake/test_subject.py::test_it",), ["subject.py"])
            req.subject["repo_root"] = str(other)
            result = await self._run(req)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.evidence["introduced"], ["tests_fake/test_subject.py::test_it"])
