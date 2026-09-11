"""What Sim changed is measured against the tree it was handed, not the
dataset's base commit.

An image's `/testbed` is not its base commit: SWE-bench's environment
setup edits files (astropy's `pyproject.toml`). Diffing against the
base commit put that edit into the SCORED patch of astropy-14309 in the
second live run; the scorer's `git apply` refused the hunk, `patch
--fuzz=5` then printed "Reversed (or previously applied) patch
detected! Assuming -R" and silently reverted the image's own change in
the scoring container (2026-09-10). The same hunk rode into every
in-container `run_tests`. `record_pristine` commits the materialised
tree once, and every reader diffs against that.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.benchmark.swebench import diff_of
from simorgh.contracts.checkout import ContainerCheckout, changed_sources, django_label, record_pristine
from simorgh.contracts.protocols import ToolContext
from simorgh.execution import tools as tools_module
from simorgh.execution.config import Config
from simorgh.execution.tools import RunTestsTool


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True)


class PristineBaselineTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        _git(self.root, "init", "-q")
        (self.root / ".gitignore").write_text("workspace/\n")
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-qm", "outer")
        self.checkout = self.root / "workspace" / "swebench" / "case-1"
        (self.checkout / "pkg" / "tests").mkdir(parents=True)
        (self.checkout / "pkg" / "mod.py").write_text("X = 1\n")
        (self.checkout / "pkg" / "tests" / "test_mod.py").write_text("def test_x():\n    assert True\n")
        (self.checkout / "pyproject.toml").write_text('requires = ["setuptools"]\n')
        _git(self.checkout, "init", "-q")
        _git(self.checkout, "add", "-A")
        _git(self.checkout, "commit", "-qm", "base")
        self.base = _git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        # The image's environment setup, applied to the tree but never committed.
        (self.checkout / "pyproject.toml").write_text('requires = ["setuptools==68"]\n')
        self.pristine = record_pristine(self.checkout, self.base)
        ContainerCheckout(image="img:1", platform="linux/amd64", workdir="/testbed",
                          base_commit=self.base, setup="", test_command="pytest",
                          pristine=self.pristine).write(self.checkout)

    def test_the_pristine_commit_is_the_tree_as_handed_over(self):
        self.assertTrue(self.pristine)
        self.assertEqual(diff_of(self.checkout, base=self.pristine), ("", ""))
        self.assertEqual(changed_sources(self.checkout, self.pristine), ())
        # and it is reachable by name, on no branch
        self.assertEqual(_git(self.checkout, "rev-parse", "refs/simorgh/pristine").stdout.strip(), self.pristine)
        self.assertEqual(_git(self.checkout, "rev-parse", "HEAD").stdout.strip(), self.base, "HEAD did not move")

    def test_against_the_base_commit_the_environment_edit_was_the_answer(self):
        """The fail-before shape, kept as a statement of the difference."""
        patch, _ = diff_of(self.checkout, base=self.base)
        self.assertIn("setuptools==68", patch)

    def test_sims_edit_is_the_whole_answer(self):
        (self.checkout / "pkg" / "mod.py").write_text("X = 2\n")
        patch, _ = diff_of(self.checkout, base=self.pristine)
        self.assertIn("+X = 2", patch)
        self.assertNotIn("pyproject", patch)
        self.assertEqual(changed_sources(self.checkout, self.pristine), ("pkg/mod.py",))

    def test_the_manifest_carries_it_and_an_old_one_falls_back(self):
        manifest = ContainerCheckout.read(self.checkout)
        self.assertEqual(manifest.pristine, self.pristine)
        self.assertEqual(manifest.diff_base, self.pristine)
        (self.checkout / ".simorgh-checkout.json").write_text(
            (self.checkout / ".simorgh-checkout.json").read_text().replace(self.pristine, ""))
        self.assertEqual(ContainerCheckout.read(self.checkout).diff_base, self.base)

    async def test_the_container_run_carries_only_sims_edit(self):
        (self.checkout / "pkg" / "mod.py").write_text("X = 2\n")
        captured = {}

        def fake(args, *, timeout):
            stage = Path(args[args.index("-v") + 1].split(":")[0])
            captured["patch"] = (stage / "patch.diff").read_text()
            return 0, ">>>>> Start Test Output\n1 passed\n"

        real = tools_module.shutil.which
        config = Config(repo_root=self.root)
        ctx = ToolContext(action_id="a", task_id=None, scope={}, constraints={}, data_dir=self.root,
                          clock=None, logger=None, ledger=None)
        with mock.patch.object(tools_module.shutil, "which", side_effect=lambda n: "/usr/bin/docker" if n == "docker" else real(n)), \
                mock.patch.object(tools_module, "_docker_run", side_effect=fake):
            result = await RunTestsTool(config).run({"target": "workspace/swebench/case-1/pkg/tests/test_mod.py"}, ctx=ctx)
        self.assertTrue(result.ok, result.error)
        self.assertIn("+X = 2", captured["patch"])
        self.assertNotIn("pyproject", captured["patch"])


class DjangoLabelTestCase(unittest.TestCase):
    def test_a_node_id_becomes_a_dotted_label(self):
        self.assertEqual(django_label("tests/auth_tests/test_validators.py::UsernameValidatorsTests"),
                         "auth_tests.test_validators.UsernameValidatorsTests")
        self.assertEqual(django_label("tests/a/tests.py::Cls::test_x"), "a.tests.Cls.test_x")

    def test_plain_shapes_are_unchanged(self):
        self.assertEqual(django_label("tests/admin_checks/tests.py"), "admin_checks.tests")
        self.assertEqual(django_label("tests/admin_checks"), "admin_checks")
        self.assertEqual(django_label("admin_checks.tests"), "admin_checks.tests")


if __name__ == "__main__":
    unittest.main()
