"""A passing container run only counts if it could have seen the change.

Observed live, 2026-09-10 (two runs of `benchmark run swebench-verified`):
`full_suite_ran` accepted ANY passing `run_tests` inside the checkout's
image. In one case Sim changed `astropy/io/registry/base.py`, ran
`astropy/io/registry/tests/test_registries.py`... no -- it ran an
unrelated file, that file passed, and a change that broke 28 tests in
the module it actually edited was accepted and committed. "The
project's own tests ran and passed" was true and meant nothing.

The bar now: every source file the checkout differs from its base by
must be covered by at least one passing container run -- a target that
is the file's own package tests directory (or an ancestor package's), a
directory above the file, or a test file that imports the changed
module. What changed is read from the checkout's own git, not from
`written_paths`: an edit made with `run_shell` and `sed` is a change
the scorer will see, so it is one the verifier must see too.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts.checkout import ContainerCheckout, changed_sources, covers
from simorgh.verification.api import VerifyRequest
from simorgh.verification.checks import FullSuiteRanCheck
from simorgh.verification.checks import fullsuiteran


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True)


def _step(tool: str, ok: bool = True, summary: str = "") -> dict:
    return {"tool": tool, "ok": ok, "phase": "act", "summary": summary}


def _request(steps: list[dict], written: list[str] | None = None) -> VerifyRequest:
    subject = {"kind": "patch", "description": "d", "result": "done", "steps": steps, "complete_log": True}
    if written is not None:
        subject["written_paths"] = written
    return VerifyRequest(verification_id="v1", task_id="t1", kind="task", subject=subject)


CASE = "workspace/swebench/case-1"


def _ran(target: str, tail: str = "3 passed") -> str:
    """What `run_tests` really puts at the head of a container run."""
    return f"[ran target={CASE + '/' + target!r}]\n[ran {target!r} inside image img:1]\n{tail}"


class _Checkout:
    """`pkg/registry/base.py` with its own tests, and `pkg/fits/` next to
    it with tests of its own that never import registry -- the astropy
    layout the live failure happened in, small enough to read."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.checkout = self.root / CASE
        files = {
            "pkg/__init__.py": "",
            "pkg/registry/__init__.py": "from .base import identify\n",
            "pkg/registry/base.py": "def identify(args):\n    return args[0]\n",
            "pkg/registry/tests/test_registries.py": "from pkg.registry import base\n",
            "pkg/fits/__init__.py": "",
            "pkg/fits/connect.py": "def is_fits(*args):\n    return args[0]\n",
            "pkg/fits/tests/test_connect.py": "from pkg.fits import connect\n",
            "pkg/tests/test_all.py": "import pkg\n",
            "docs/index.rst": "",
        }
        for rel, text in files.items():
            path = self.checkout / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        _git(self.checkout, "init", "-q")
        _git(self.checkout, "add", "-A")
        _git(self.checkout, "commit", "-qm", "base")
        self.base = _git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        ContainerCheckout(image="img:1", platform="linux/amd64", workdir="/testbed",
                          base_commit=self.base, setup="", test_command="pytest").write(self.checkout)

    def edit(self, rel: str, text: str) -> None:
        (self.checkout / rel).write_text(text)


class ChangedSourcesTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.co = _Checkout(Path(self._tmp.name))

    def test_an_untouched_checkout_changed_nothing(self):
        self.assertEqual(changed_sources(self.co.checkout, self.co.base), ())

    def test_a_working_tree_edit_counts_without_any_git_add(self):
        self.co.edit("pkg/registry/base.py", "def identify(args):\n    return args[0] if args else None\n")
        self.assertEqual(changed_sources(self.co.checkout, self.co.base), ("pkg/registry/base.py",))

    def test_a_committed_edit_still_counts(self):
        self.co.edit("pkg/registry/base.py", "X = 1\n")
        _git(self.co.checkout, "commit", "-qam", "fix")
        self.assertEqual(changed_sources(self.co.checkout, self.co.base), ("pkg/registry/base.py",))

    def test_a_new_file_counts_and_tests_the_manifest_and_non_python_do_not(self):
        (self.co.checkout / "pkg" / "new.py").write_text("Y = 2\n")
        self.co.edit("pkg/registry/tests/test_registries.py", "changed\n")
        self.co.edit("docs/index.rst", "changed\n")
        self.assertEqual(changed_sources(self.co.checkout, self.co.base), ("pkg/new.py",))

    def test_not_a_repository_is_no_opinion(self):
        self.assertIsNone(changed_sources(Path(self._tmp.name) / "nowhere", self.co.base))


class CoversTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.co = _Checkout(Path(self._tmp.name))

    def _covers(self, target: str) -> bool:
        return covers(target, "pkg/registry/base.py", checkout=self.co.checkout)

    def test_the_packages_own_tests(self):
        self.assertTrue(self._covers("pkg/registry/tests/test_registries.py"))
        self.assertTrue(self._covers("pkg/registry/tests"))

    def test_an_ancestor_packages_tests(self):
        self.assertTrue(self._covers("pkg/tests/test_all.py"))

    def test_a_directory_above_the_file(self):
        self.assertTrue(self._covers("pkg/registry"))
        self.assertTrue(self._covers("pkg"))
        self.assertTrue(self._covers("."))

    def test_a_single_test_id_is_still_its_file(self):
        self.assertTrue(self._covers("pkg/registry/tests/test_registries.py::test_x"))

    def test_a_sibling_packages_tests_that_never_import_it_do_not(self):
        self.assertFalse(self._covers("pkg/fits/tests/test_connect.py"))
        self.assertFalse(self._covers("pkg/fits/tests"))
        self.assertFalse(self._covers("pkg/fits"))

    def test_a_test_anywhere_that_imports_the_module_does(self):
        self.co.edit("pkg/fits/tests/test_connect.py", "from pkg.registry.base import identify\n")
        self.assertTrue(self._covers("pkg/fits/tests/test_connect.py"))

    def test_importing_the_package_the_module_sits_in_counts_too(self):
        self.co.edit("pkg/fits/tests/test_connect.py", "from pkg import registry\n")
        self.assertTrue(self._covers("pkg/fits/tests/test_connect.py"))

    def test_importing_only_the_top_level_package_is_not_enough(self):
        # `import pkg` at the head of every test file would otherwise make
        # every file cover every change.
        self.co.edit("pkg/fits/tests/test_connect.py", "import pkg\n")
        self.assertFalse(self._covers("pkg/fits/tests/test_connect.py"))


class TheCheckDemandsCoverage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.co = _Checkout(Path(self._tmp.name))
        patcher = mock.patch.object(fullsuiteran, "REPO_ROOT", self.co.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _run(self, steps: list[dict], written: list[str] | None = None):
        return await FullSuiteRanCheck().run(_request(steps, written), None)

    async def test_the_live_failure_an_unrelated_file_passing_is_not_accepted(self):
        """The fail-before case: registry changed, fits' tests ran."""
        self.co.edit("pkg/registry/base.py", "def identify(args):\n    return None\n")
        result = await self._run([
            _step("apply_source_patch"),
            _step("run_tests", ok=True, summary=_ran("pkg/fits/tests/test_connect.py")),
        ], written=[f"{CASE}/pkg/registry/base.py"])
        self.assertEqual(result.status, "failed", result.detail)
        self.assertIn("pkg/registry/base.py", result.detail)
        self.assertIn("pkg/fits/tests/test_connect.py", result.detail)
        self.assertIn(f"{CASE}/pkg/registry/tests", result.feedback.revise_hint)
        self.assertTrue(result.feedback.retryable)

    async def test_an_edit_made_through_the_shell_is_judged_the_same(self):
        """`written_paths` is empty for a `sed -i`; the checkout's git is not."""
        self.co.edit("pkg/registry/base.py", "def identify(args):\n    return None\n")
        result = await self._run([
            _step("run_shell"),
            _step("run_tests", ok=True, summary=_ran("pkg/fits/tests/test_connect.py")),
        ], written=[])
        self.assertEqual(result.status, "failed", result.detail)
        self.assertIn("pkg/registry/base.py", result.detail)

    async def test_the_nearest_tests_passing_is_accepted(self):
        self.co.edit("pkg/registry/base.py", "def identify(args):\n    return None\n")
        result = await self._run([
            _step("apply_source_patch"),
            _step("run_tests", ok=True, summary=_ran("pkg/registry/tests/test_registries.py")),
        ])
        self.assertEqual(result.status, "passed", result.detail)
        self.assertIn("pkg/registry/base.py", result.detail)

    async def test_a_failing_covering_run_beside_a_passing_unrelated_one_is_still_a_failure(self):
        self.co.edit("pkg/registry/base.py", "def identify(args):\n    return None\n")
        result = await self._run([
            _step("apply_source_patch"),
            _step("run_tests", ok=False, summary=_ran("pkg/registry/tests/test_registries.py",
                                                     "[failed 1: pkg/registry/tests/test_registries.py::test_x]\n1 failed")),
            _step("run_tests", ok=True, summary=_ran("pkg/fits/tests/test_connect.py")),
        ])
        self.assertEqual(result.status, "failed", result.detail)

    async def test_every_changed_file_needs_a_run_not_just_one_of_them(self):
        self.co.edit("pkg/registry/base.py", "A = 1\n")
        self.co.edit("pkg/fits/connect.py", "B = 2\n")
        result = await self._run([
            _step("apply_source_patch"),
            _step("run_tests", ok=True, summary=_ran("pkg/registry/tests/test_registries.py")),
        ])
        self.assertEqual(result.status, "failed", result.detail)
        self.assertIn("pkg/fits/connect.py", result.detail)
        self.assertNotIn("pkg/registry/base.py", result.detail.split("--")[0])

    async def test_two_runs_together_can_cover_two_files(self):
        self.co.edit("pkg/registry/base.py", "A = 1\n")
        self.co.edit("pkg/fits/connect.py", "B = 2\n")
        result = await self._run([
            _step("apply_source_patch"),
            _step("run_tests", ok=True, summary=_ran("pkg/registry/tests/test_registries.py")),
            _step("run_tests", ok=True, summary=_ran("pkg/fits/tests")),
        ])
        self.assertEqual(result.status, "passed", result.detail)

    async def test_a_checkout_that_changed_nothing_has_nothing_to_cover(self):
        result = await self._run([
            _step("run_shell"),
            _step("run_tests", ok=True, summary=_ran("pkg/fits/tests/test_connect.py")),
        ])
        self.assertEqual(result.status, "passed", result.detail)

    async def test_a_checkout_that_is_gone_keeps_the_old_answer(self):
        """The tests in `test_full_suite_ran.py` name a checkout that never
        existed on disk; a run whose checkout cannot be read is judged the
        way it was before coverage existed, and says so."""
        result = await self._run([
            _step("apply_source_patch"),
            _step("run_tests", ok=True, summary=_ran("pkg/fits/tests/test_connect.py").replace("case-1", "case-9")),
        ])
        self.assertEqual(result.status, "passed", result.detail)
        self.assertIn("could not", result.detail)


if __name__ == "__main__":
    unittest.main()
