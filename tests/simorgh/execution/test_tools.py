"""Per-tool tests for `execution.tools` (08-execution.md section 5.2),
each a port of a v1 tool. Uses throwaway temp directories/git repos --
never the real project repository."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.tools import (
    ApplySkillTool,
    ApplySourcePatchTool,
    GitCommitTool,
    GitRevertTool,
    ListDirTool,
    ReadFileTool,
    RunPythonSandboxedTool,
    SkillTool,
    builtin_tools,
)


def _ctx(config: Config, constraints: dict | None = None):
    from simorgh.contracts.protocols import ToolContext

    return ToolContext(
        action_id="a1", task_id=None, scope={}, constraints=constraints or {},
        data_dir=config.repo_root, clock=None, logger=None, ledger=None,
    )


class TestReadFileTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("hello")
        self.config = Config(repo_root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_reads_a_file_in_a_readable_root(self):
        result = await ReadFileTool(self.config).run({"path": "src/a.py"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "hello")

    async def test_refuses_a_path_outside_readable_roots(self):
        result = await ReadFileTool(self.config).run({"path": "../outside.py"}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)


class TestListDirTool(unittest.IsolatedAsyncioTestCase):
    async def test_lists_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("x")
            config = Config(repo_root=root)
            result = await ListDirTool(config).run({"path": "src"}, ctx=_ctx(config))
            self.assertTrue(result.ok)
            self.assertIn("a.py", result.output)


class TestRunPythonSandboxedTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = Config(repo_root=Path.cwd(), sandbox_timeout_s=5.0)

    async def test_successful_code_returns_stdout(self):
        result = await RunPythonSandboxedTool(self.config).run(
            {"code": "print('hi from sandbox')"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok, result.metadata)
        self.assertIn("hi from sandbox", result.output)

    async def test_a_raising_script_returns_ok_false_with_exit_code(self):
        result = await RunPythonSandboxedTool(self.config).run(
            {"code": "raise ValueError('boom')"}, ctx=_ctx(self.config),
        )
        self.assertFalse(result.ok)
        self.assertIn("exit_code", result.error)

    async def test_the_sandbox_has_no_repo_access(self):
        # empty env + `python -I` -- importing this very package must fail,
        # proving there's no PYTHONPATH/repo access (milestone 84).
        result = await RunPythonSandboxedTool(self.config).run(
            {"code": "import simorgh.execution"}, ctx=_ctx(self.config),
        )
        self.assertFalse(result.ok)


class TestApplySourcePatchTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = Config(repo_root=self.root, write_scopes_source=("src/",))

    def tearDown(self):
        self._tmp.cleanup()

    async def test_writes_a_file_inside_the_write_scope(self):
        result = await ApplySourcePatchTool(self.config).run(
            {"subject": "src/new_module.py", "code": "x = 1\n"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok)
        self.assertEqual((self.root / "src" / "new_module.py").read_text(), "x = 1\n")

    async def test_refuses_a_subject_outside_the_write_scope(self):
        result = await ApplySourcePatchTool(self.config).run(
            {"subject": "docs/SOUL.md", "code": "tampered"}, ctx=_ctx(self.config),
        )
        self.assertFalse(result.ok)
        self.assertFalse((self.root / "docs").exists())

    async def test_refuses_traversal_even_with_a_matching_prefix(self):
        result = await ApplySourcePatchTool(self.config).run(
            {"subject": "src/../../../etc/passwd", "code": "x"}, ctx=_ctx(self.config),
        )
        self.assertFalse(result.ok)


class TestApplySkillTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = Config(repo_root=self.root, write_scopes_skills=("simorgh_skills/",))

    def tearDown(self):
        self._tmp.cleanup()

    async def test_writes_a_file_inside_the_skill_scope(self):
        result = await ApplySkillTool(self.config).run(
            {"subject": "simorgh_skills/greet.py", "code": "def run():\n    return 'hi'\n"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok, result.error)
        self.assertEqual((self.root / "simorgh_skills" / "greet.py").read_text(), "def run():\n    return 'hi'\n")

    async def test_refuses_a_subject_outside_the_skill_scope(self):
        result = await ApplySkillTool(self.config).run(
            {"subject": "src/not_a_skill.py", "code": "x = 1"}, ctx=_ctx(self.config),
        )
        self.assertFalse(result.ok)
        self.assertFalse((self.root / "src").exists())

    async def test_refuses_traversal_even_with_a_matching_prefix(self):
        result = await ApplySkillTool(self.config).run(
            {"subject": "simorgh_skills/../../etc/passwd", "code": "x"}, ctx=_ctx(self.config),
        )
        self.assertFalse(result.ok)


class TestSkillTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = Config(repo_root=Path.cwd(), sandbox_timeout_s=5.0)

    async def test_runs_the_skills_own_entrypoint_with_forwarded_args(self):
        tool = SkillTool(
            self.config, skill_name="greet", description="greets someone",
            source='def run(name="world"):\n    return f"hello {name}"\n',
        )
        self.assertEqual(tool.name, "skill:greet")
        result = await tool.run({"name": "simorgh"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.metadata)
        self.assertIn("hello simorgh", result.output)

    async def test_the_skills_own_main_guard_does_not_double_fire(self):
        tool = SkillTool(
            self.config, skill_name="once", description="prints once",
            source="def run():\n    return 'once'\n\nif __name__ == '__main__':\n    print(run())\n",
        )
        result = await tool.run({}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.metadata)
        self.assertEqual(result.output.strip().count("once"), 1)

    async def test_a_raising_skill_returns_ok_false(self):
        tool = SkillTool(
            self.config, skill_name="broken", description="always fails",
            source="def run():\n    raise ValueError('boom')\n",
        )
        result = await tool.run({}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        self.assertIn("exit_code", result.error)

    async def test_a_missing_run_entrypoint_returns_ok_false(self):
        tool = SkillTool(self.config, skill_name="empty", description="no entrypoint", source="x = 1\n")
        result = await tool.run({}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)

    async def test_the_sandbox_has_no_repo_access(self):
        tool = SkillTool(
            self.config, skill_name="nosy", description="tries to import the repo",
            source="def run():\n    import simorgh.execution\n    return 'should not get here'\n",
        )
        result = await tool.run({}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


class TestGitCommitTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-q", "-m", "init")
        self.config = Config(repo_root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_nothing_to_commit_precheck_returns_evidenced_failure(self):
        (self.root / "unchanged.txt").write_text("same")
        _git(self.root, "add", "unchanged.txt")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "seed")

        result = await GitCommitTool(self.config).run(
            {"path": "unchanged.txt", "message": "no-op"}, ctx=_ctx(self.config),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "nothing_to_commit")
        self.assertIn("head_sha", result.metadata)
        self.assertIn("path_sha", result.metadata)

    async def test_commits_a_real_change_attributed_to_simorgh(self):
        (self.root / "changed.txt").write_text("v1")
        result = await GitCommitTool(self.config).run(
            {"path": "changed.txt", "message": "add changed.txt"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok, result.error)
        log = _git(self.root, "log", "-1", "--format=%an <%ae>")
        self.assertEqual(log.stdout.strip(), "Simorgh <simorgh@localhost>")

    async def test_never_pushes(self):
        import inspect

        from simorgh.execution import tools as tools_module

        source = inspect.getsource(tools_module.GitCommitTool.run)
        self.assertNotIn('"push"', source)
        self.assertNotIn("'push'", source)


class TestGitRevertTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _git(self.root, "init", "-q")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-q", "-m", "init")
        (self.root / "a.txt").write_text("v1")
        _git(self.root, "add", "a.txt")
        _git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "add a.txt")
        self.config = Config(repo_root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_reverts_the_last_commit_as_a_new_commit(self):
        before = _git(self.root, "rev-parse", "HEAD").stdout.strip()
        result = await GitRevertTool(self.config).run({}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.error)
        after = _git(self.root, "rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(before, after)
        self.assertFalse((self.root / "a.txt").exists())
        log = _git(self.root, "log", "-1", "--format=%an <%ae>")
        self.assertEqual(log.stdout.strip(), "Simorgh <simorgh@localhost>")


class TestBuiltinTools(unittest.TestCase):
    def test_registers_exactly_the_scoped_set(self):
        names = {tool.name for tool in builtin_tools(Config(repo_root=Path.cwd()))}
        self.assertEqual(names, {
            "read_file", "list_dir", "run_python_sandboxed",
            "apply_source_patch", "git_commit", "git_revert", "apply_skill",
        })


if __name__ == "__main__":
    unittest.main()
