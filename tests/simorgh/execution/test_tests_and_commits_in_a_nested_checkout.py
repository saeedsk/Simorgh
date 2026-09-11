"""A path inside a materialised checkout belongs to that checkout.

First real SWE-bench Verified run, 2026-09-10. Sim edited the right
file, then:

    step 4  run_tests: [ran target='astropy/io/fits/tests/test_connect.py']
            refused: '...' does not exist in the repo
    step 5  run_tests: [ran target='astropy/io/fits/tests']  refused ...
    step 7  git_commit: nothing_to_commit

`run_tests` resolved the path against Simorgh's own repository and the
checkout's tests would not have run on the host anyway -- its
dependencies exist only inside its image. `git_commit` ran from
Simorgh's repository, where `workspace/` is gitignored, so the change
did not exist. Sim burned three steps and worked around both with
`run_shell`.

Now `run_tests` on a path under a manifest-bearing checkout runs the
project's own test command inside the project's own container, and the
git tools operate on the nested repository the path belongs to.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts.checkout import TARGET_DJANGO_LABEL, ContainerCheckout
from simorgh.contracts.protocols import ToolContext
from simorgh.execution import tools as tools_module
from simorgh.execution.config import Config
from simorgh.execution.tools import GitCommitTool, GitDiscardTool, RunTestsTool, nested_git_root


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          capture_output=True, text=True)


def _ctx(config: Config) -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=config.repo_root, clock=None, logger=None, ledger=None)


class _Repo:
    """An outer repository with `workspace/` ignored and a nested
    checkout inside it, the way the benchmark leaves things."""

    def __init__(self, root: Path):
        self.root = root.resolve()  # macOS: /var -> /private/var
        root = self.root
        _git(root, "init", "-q")
        (root / ".gitignore").write_text("workspace/\n")
        (root / "tests").mkdir()
        (root / "tests" / "test_own.py").write_text("def test_own():\n    assert True\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", "init")
        self.checkout = root / "workspace" / "swebench" / "case-1"
        (self.checkout / "pkg" / "tests").mkdir(parents=True)
        (self.checkout / "pkg" / "mod.py").write_text("X = 1\n")
        (self.checkout / "pkg" / "tests" / "test_mod.py").write_text("def test_x():\n    assert True\n")
        _git(self.checkout, "init", "-q")
        _git(self.checkout, "add", "-A")
        _git(self.checkout, "commit", "-qm", "base")
        self.base = _git(self.checkout, "rev-parse", "HEAD").stdout.strip()
        ContainerCheckout(image="img:latest", platform="linux/amd64", workdir="/testbed",
                          base_commit=self.base, setup="conda activate testbed\n",
                          test_command="pytest -rA --tb=no").write(self.checkout)


class NestedRootTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _Repo(Path(self._tmp.name))

    def test_a_path_in_the_checkout_maps_to_it(self):
        self.assertEqual(nested_git_root(self.repo.root, "workspace/swebench/case-1/pkg/mod.py"),
                         (self.repo.checkout, "pkg/mod.py"))

    def test_a_path_in_the_outer_repo_is_none(self):
        self.assertIsNone(nested_git_root(self.repo.root, "tests/test_own.py"))

    def test_escaping_the_root_is_none(self):
        self.assertIsNone(nested_git_root(self.repo.root, "../x"))


class GitToolsTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _Repo(Path(self._tmp.name))
        self.config = Config(repo_root=self.repo.root)

    async def test_git_commit_commits_inside_the_checkout(self):
        (self.repo.checkout / "pkg" / "mod.py").write_text("X = 2\n")
        result = await GitCommitTool(self.config).run(
            {"path": "workspace/swebench/case-1/pkg/mod.py", "message": "Fix X"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(_git(self.repo.checkout, "log", "-1", "--format=%s").stdout.strip(), "Fix X")
        self.assertEqual(_git(self.repo.root, "log", "-1", "--format=%s").stdout.strip(), "init",
                         "the outer repository must be untouched")
        self.assertIn("git_commit:workspace/swebench/case-1/pkg/mod.py", result.side_effects)
        self.assertEqual(result.metadata.get("repository"), str(self.repo.checkout))

    async def test_git_commit_in_the_outer_repo_is_unchanged(self):
        (self.repo.root / "tests" / "test_own.py").write_text("def test_own():\n    assert 1\n")
        result = await GitCommitTool(self.config).run(
            {"path": "tests/test_own.py", "message": "touch"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.metadata.get("repository"), "")

    async def test_git_discard_restores_inside_the_checkout(self):
        (self.repo.checkout / "pkg" / "mod.py").write_text("X = 999\n")
        result = await GitDiscardTool(self.config).run(
            {"path": "workspace/swebench/case-1/pkg/mod.py"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.error)
        self.assertEqual((self.repo.checkout / "pkg" / "mod.py").read_text(), "X = 1\n")


class TheSeamReallyRunsTestCase(unittest.TestCase):
    """Every other test here stubs `_docker_run`. This one executes it,
    because the first version raised `ValueError: stdout and stderr
    arguments may not be used with capture_output` on every call and no
    stubbed test could have noticed."""

    def test_the_seam_really_runs(self):
        import sys

        from simorgh.execution.tools import _docker_run

        code, out = _docker_run([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
                                timeout=30)
        self.assertEqual(code, 0)
        self.assertIn("out", out)
        self.assertIn("err", out, "stderr is merged into the one stream the caller reads")

    def test_a_missing_program_is_an_exit_code_not_a_crash(self):
        from simorgh.execution.tools import _docker_run

        code, out = _docker_run(["/definitely/not/a/program"], timeout=5)
        self.assertEqual(code, 127)
        self.assertTrue(out)

    def test_a_timeout_is_124(self):
        import sys

        from simorgh.execution.tools import _docker_run

        code, _ = _docker_run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)
        self.assertEqual(code, 124)


class RunTestsInContainerTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _Repo(Path(self._tmp.name))
        self.config = Config(repo_root=self.repo.root)
        self.calls: list[list[str]] = []

    def _docker(self, code: int, output: str):
        def fake(args, *, timeout):
            self.calls.append(args)
            return code, output
        return mock.patch.object(tools_module, "_docker_run", side_effect=fake)

    def _which(self):
        real = tools_module.shutil.which
        return mock.patch.object(tools_module.shutil, "which",
                                 side_effect=lambda n: "/usr/bin/docker" if n == "docker" else real(n))

    async def _run(self, target: str, code: int = 0, output: str = "") -> object:
        with self._which(), self._docker(code, output):
            return await RunTestsTool(self.config).run({"target": target}, ctx=_ctx(self.config))

    def _script(self) -> str:
        args = self.calls[-1]
        stage = Path(args[args.index("-v") + 1].split(":")[0])
        # The stage is gone by the time we look; the script is captured
        # through the fake instead.
        return self._captured

    async def test_the_projects_own_command_runs_in_its_image_with_the_changes(self):
        (self.repo.checkout / "pkg" / "mod.py").write_text("X = 2\n")
        captured = {}

        def fake(args, *, timeout):
            self.calls.append(args)
            stage = Path(args[args.index("-v") + 1].split(":")[0])
            captured["script"] = (stage / "run.sh").read_text()
            captured["patch"] = (stage / "patch.diff").read_text()
            return 0, ">>>>> Start Test Output\nPASSED pkg/tests/test_mod.py::test_x\n1 passed in 0.1s\n"

        with self._which(), mock.patch.object(tools_module, "_docker_run", side_effect=fake):
            result = await RunTestsTool(self.config).run(
                {"target": "workspace/swebench/case-1/pkg/tests/test_mod.py"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.error)
        args = self.calls[-1]
        self.assertIn("img:latest", args)
        self.assertIn("linux/amd64", args)
        self.assertIn("conda activate testbed", captured["script"])
        self.assertIn("cd /testbed", captured["script"])
        self.assertIn("pytest -rA --tb=no pkg/tests/test_mod.py", captured["script"])
        self.assertIn("X = 2", captured["patch"], "what Sim changed travels into the container")
        self.assertIn("[ran 'pkg/tests/test_mod.py' inside image img:latest]", result.output)
        self.assertEqual(result.metadata["container"], "img:latest")

    async def test_a_committed_change_still_travels(self):
        (self.repo.checkout / "pkg" / "mod.py").write_text("X = 3\n")
        _git(self.repo.checkout, "add", "-A")
        _git(self.repo.checkout, "commit", "-qm", "fix")
        captured = {}

        def fake(args, *, timeout):
            stage = Path(args[args.index("-v") + 1].split(":")[0])
            captured["patch"] = (stage / "patch.diff").read_text()
            return 0, "1 passed in 0.1s\n"

        with self._which(), mock.patch.object(tools_module, "_docker_run", side_effect=fake):
            await RunTestsTool(self.config).run(
                {"target": "workspace/swebench/case-1/pkg/tests"}, ctx=_ctx(self.config))
        self.assertIn("X = 3", captured["patch"])

    async def test_a_failure_is_named_and_colour_is_stripped(self):
        out = (">>>>> Start Test Output\n"
               "\x1b[31mFAILED\x1b[0m pkg/tests/test_mod.py::\x1b[1mtest_x\x1b[0m - assert\n"
               "\x1b[31m1 failed in 0.1s\x1b[0m\n")
        result = await self._run("workspace/swebench/case-1/pkg/tests/test_mod.py", code=1, output=out)
        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["failing_nodeids"], ["pkg/tests/test_mod.py::test_x"])
        self.assertTrue(result.output.startswith("[failed 1: pkg/tests/test_mod.py::test_x]"), result.output)
        self.assertNotIn("\x1b", result.output)

    async def test_django_targets_become_labels(self):
        ContainerCheckout(image="dj", platform="", workdir="/testbed", base_commit=self.repo.base,
                          setup="", test_command="./tests/runtests.py --parallel 1",
                          target_style=TARGET_DJANGO_LABEL).write(self.repo.checkout)
        captured = {}

        def fake(args, *, timeout):
            stage = Path(args[args.index("-v") + 1].split(":")[0])
            captured["script"] = (stage / "run.sh").read_text()
            return 0, "OK\n"

        with self._which(), mock.patch.object(tools_module, "_docker_run", side_effect=fake):
            result = await RunTestsTool(self.config).run(
                {"target": "workspace/swebench/case-1/tests/test_utils/tests.py"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.error)
        self.assertIn("./tests/runtests.py --parallel 1 test_utils.tests", captured["script"])
        self.assertEqual(result.metadata["target"], "test_utils.tests")

    async def test_a_patch_that_does_not_apply_says_so(self):
        result = await self._run("workspace/swebench/case-1/pkg/tests", code=90, output="SIMORGH_PATCH_FAILED\n")
        self.assertFalse(result.ok)
        self.assertIn("do not apply", result.error)

    async def test_a_timeout_is_a_timeout(self):
        result = await self._run("workspace/swebench/case-1/pkg/tests", code=124, output="")
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout")

    async def test_without_docker_the_refusal_says_why(self):
        real = tools_module.shutil.which
        with mock.patch.object(tools_module.shutil, "which",
                               side_effect=lambda n: None if n == "docker" else real(n)):
            result = await RunTestsTool(self.config).run(
                {"target": "workspace/swebench/case-1/pkg/tests"}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        self.assertIn("Docker is not installed", result.error)

    async def test_the_outer_repos_tests_still_run_on_the_host(self):
        with self._docker(0, "") as docker:
            result = await RunTestsTool(self.config).run({"target": "tests/test_own.py"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.error)
        docker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
