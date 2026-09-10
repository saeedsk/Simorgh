"""Per-tool tests for `execution.tools` (08-execution.md section 5.2),
each a port of a v1 tool. Uses throwaway temp directories/git repos --
never the real project repository."""

import json
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.tools import (
    MCP_PROPOSALS_STREAM,
    ApplySkillTool,
    ApplySourcePatchTool,
    GitCommitTool,
    GitRevertTool,
    ListDirTool,
    ProposeMcpServerTool,
    ReadFileTool,
    RunJsSandboxedTool,
    RunPythonSandboxedTool,
    RunTestsTool,
    SearchCodeTool,
    SkillTool,
    WebFetchTool,
    builtin_tools,
)
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock


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


class TestSearchCodeTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "a.py").write_text("def needle():\n    pass\n")
        (self.root / "src" / "b.py").write_text("no match here\n")
        (self.root / "docs").mkdir()
        (self.root / "docs" / "c.md").write_text("needle mentioned in docs too\n")
        self.config = Config(repo_root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_finds_matches_across_readable_roots_with_path_and_line(self):
        result = await SearchCodeTool(self.config).run({"query": "needle"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok)
        self.assertIn("src/a.py:1:", result.output)
        self.assertIn("docs/c.md:1:", result.output)
        self.assertEqual(result.metadata["matches"], 2)

    async def test_no_matches_is_still_ok(self):
        result = await SearchCodeTool(self.config).run({"query": "nothing_matches_this"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "(no matches)")
        self.assertEqual(result.metadata["matches"], 0)

    async def test_an_invalid_regex_is_refused_not_a_crash(self):
        result = await SearchCodeTool(self.config).run({"query": "("}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        self.assertIn("not a valid regex", result.error)

    async def test_matches_are_capped(self):
        config = Config(repo_root=self.root, search_max_matches=1)
        result = await SearchCodeTool(config).run({"query": "needle"}, ctx=_ctx(config))
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["matches"], 1)
        self.assertIn("capped", result.output)

    async def test_never_reaches_outside_readable_roots(self):
        (self.root / "secret.py").write_text("needle outside the readable tree\n")
        result = await SearchCodeTool(self.config).run({"query": "needle"}, ctx=_ctx(self.config))
        self.assertNotIn("secret.py", result.output)

    async def test_pure_python_fallback_forced_by_no_ripgrep_on_path(self):
        result = await SearchCodeTool(self.config, ripgrep_path="").run(
            {"query": "needle"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["via"], "python")
        self.assertIn("src/a.py:1:", result.output)

    @unittest.skipUnless(shutil.which("rg"), "ripgrep not installed on this machine")
    async def test_ripgrep_path_finds_the_same_matches_as_the_fallback(self):
        rg = shutil.which("rg")
        result = await SearchCodeTool(self.config, ripgrep_path=rg).run(
            {"query": "needle"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["via"], "ripgrep")
        self.assertIn("src/a.py:1:", result.output)
        self.assertIn("docs/c.md:1:", result.output)

    async def test_a_broken_ripgrep_path_degrades_to_the_fallback_not_a_crash(self):
        result = await SearchCodeTool(self.config, ripgrep_path="/not/a/real/binary").run(
            {"query": "needle"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["via"], "python")

    async def test_pure_python_backend_will_not_grep_a_credentials_file(self):
        # Live-caught, 2026-09-08: `read_file` refuses `tools/credentials.json`
        # by name (pathsafety._CREDENTIAL_LOOKING_NAMES), but search_code's
        # pure-Python file walk had no such filter and returned the secret
        # verbatim -- a policy bypass via a second read path.
        (self.root / "src" / "credentials.json").write_text("SECRET_TOKEN=sk-supersecrettoken12345\n")
        result = await SearchCodeTool(self.config, ripgrep_path="").run(
            {"query": "supersecrettoken"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok)
        self.assertNotIn("supersecrettoken", result.output)
        self.assertNotIn("credentials.json", result.output)

    @unittest.skipUnless(shutil.which("rg"), "ripgrep not installed on this machine")
    async def test_ripgrep_backend_will_not_grep_a_credentials_file(self):
        # Same bypass, ripgrep backend: `rg`'s default hidden-file skip
        # happens to hide a dotfile like `.env`, but a non-hidden name
        # like `credentials.json` was found and returned verbatim.
        (self.root / "src" / "credentials.json").write_text("SECRET_TOKEN=sk-supersecrettoken12345\n")
        rg = shutil.which("rg")
        result = await SearchCodeTool(self.config, ripgrep_path=rg).run(
            {"query": "supersecrettoken"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok)
        self.assertNotIn("supersecrettoken", result.output)
        self.assertNotIn("credentials.json", result.output)


class TestRunTestsTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_sample.py").write_text(
            "def test_pass():\n    assert 1 + 1 == 2\n"
        )
        (self.root / "tests" / "test_fails.py").write_text(
            "def test_fail():\n    assert False\n"
        )
        self.config = Config(repo_root=self.root, test_timeout_s=30.0)

    def tearDown(self):
        self._tmp.cleanup()

    async def test_a_passing_target_reports_ok(self):
        result = await RunTestsTool(self.config).run(
            {"target": "tests/test_sample.py"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok, result.output + result.metadata.get("stderr", ""))
        self.assertIn("1 passed", result.output)

    async def test_a_failing_target_reports_ok_false_with_exit_code(self):
        result = await RunTestsTool(self.config).run(
            {"target": "tests/test_fails.py"}, ctx=_ctx(self.config),
        )
        self.assertFalse(result.ok)
        self.assertIn("exit_code", result.error)

    async def test_a_non_python_target_reports_nothing_to_run_not_a_failure(self):
        """Live-caught 2026-09-09, second 95120 trial: told to run its
        tests, Sim called `run_tests` on the .html page it had just
        written. pytest exits 4 (usage error, not 5), the tool reported
        a failing suite, FullSuiteRanCheck then demanded the whole
        suite, and the task blocked with a correct page uncommitted."""
        (self.root / "docs").mkdir()
        (self.root / "docs" / "page.html").write_text("<html><body>hi</body></html>")
        result = await RunTestsTool(self.config).run(
            {"target": "docs/page.html"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok, result.error)
        self.assertIn("nothing was run", result.output)
        self.assertIn("run_tests with no target", result.output)
        self.assertTrue(result.metadata["no_tests_collected"])

    async def test_a_real_usage_error_on_a_python_target_is_still_a_failure(self):
        # Exit 4 only reads as "nothing to run" when the target really is
        # not Python. A broken conftest under a Python path must not be
        # laundered into a pass.
        (self.root / "tests" / "conftest.py").write_text("import nonexistent_module_xyz\n")
        result = await RunTestsTool(self.config).run(
            {"target": "tests/test_sample.py"}, ctx=_ctx(self.config),
        )
        self.assertFalse(result.ok)

    async def test_never_touches_the_real_working_tree(self):
        # A run that (hypothetically) tried to write into the repo would
        # write into the isolated copy, not `self.root` -- prove the
        # real tree is untouched by asserting no new file lands there.
        before = set(self.root.rglob("*"))
        await RunTestsTool(self.config).run({"target": "tests/test_sample.py"}, ctx=_ctx(self.config))
        after = set(self.root.rglob("*"))
        self.assertEqual(before, after)

    async def test_refuses_a_traversal_target(self):
        result = await RunTestsTool(self.config).run({"target": "../outside"}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        self.assertIn("refused", result.error)

    async def test_refuses_a_target_that_does_not_exist(self):
        result = await RunTestsTool(self.config).run({"target": "tests/nope"}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        self.assertIn("refused", result.error)

    async def test_empty_target_defaults_to_the_whole_tests_directory(self):
        result = await RunTestsTool(self.config).run({"target": ""}, ctx=_ctx(self.config))
        # both the passing and failing sample run -- overall exit is non-zero
        self.assertFalse(result.ok)
        self.assertIn("1 passed", result.output)
        self.assertIn("1 failed", result.output)


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

    async def test_a_new_file_has_no_diff(self):
        """Live-caught (the creator: "I'd like ... code diffs" --
        07-post-cutover-review.md §3.11): render.diff_block() existed but
        nothing ever produced a diff -- a real patch just silently
        replaced a file. A brand-new file has no "before" to diff
        against."""
        result = await ApplySourcePatchTool(self.config).run(
            {"subject": "src/new_module.py", "code": "x = 1\n"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["diff"], "")
        self.assertNotIn("---", result.output)

    async def test_overwriting_an_existing_file_produces_a_real_unified_diff(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "existing.py").write_text("VALUE = 1\n")
        result = await ApplySourcePatchTool(self.config).run(
            {"subject": "src/existing.py", "code": "VALUE = 2\n"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok)
        diff = result.metadata["diff"]
        self.assertIn("-VALUE = 1", diff)
        self.assertIn("+VALUE = 2", diff)
        self.assertIn("a/src/existing.py", diff)
        self.assertIn("b/src/existing.py", diff)
        self.assertIn(diff, result.output)  # the wire path (output -> stdout_preview/output_ref)

    async def test_rewriting_a_file_with_identical_content_has_no_diff(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "same.py").write_text("VALUE = 1\n")
        result = await ApplySourcePatchTool(self.config).run(
            {"subject": "src/same.py", "code": "VALUE = 1\n"}, ctx=_ctx(self.config),
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["diff"], "")


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

    async def test_an_async_run_entrypoint_is_awaited_not_left_as_a_coroutine(self):
        # Live-caught (observer, 2026-09-08): `skill_marker_arg_key`
        # already recognizes `async def run(...)` when inferring the
        # marker arg (it walks both `ast.FunctionDef` and
        # `ast.AsyncFunctionDef`), so nothing tells the model this shape
        # is unsupported -- but `_SKILL_DRIVER` called `_skill.run(**args)`
        # and printed the return value directly. For an async def that
        # return value is an un-awaited coroutine, which blew up
        # `json.dumps` with "Object of type coroutine is not JSON
        # serializable" plus a "coroutine 'run' was never awaited"
        # RuntimeWarning on every single invocation.
        tool = SkillTool(
            self.config, skill_name="async_greet", description="greets asynchronously",
            source=(
                "import asyncio\n"
                "async def run(name=\"world\"):\n"
                "    await asyncio.sleep(0)\n"
                "    return f\"hello {name}\"\n"
            ),
        )
        result = await tool.run({"name": "simorgh"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.metadata)
        self.assertIn("hello simorgh", result.output)

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


class TestSubprocessesNeverInheritTerminalStdin(unittest.IsolatedAsyncioTestCase):
    """Live-caught (the creator's own real `sim.sh` use): none of these
    subprocess.run calls ever need interactive input, but without an
    explicit `stdin=`, each inherits the parent's own stdin -- the real
    terminal, when the Kernel runs interactively. A sandboxed run (or a
    git call) that hits its own `timeout` gets killed; if the killed
    child had put that shared terminal into raw/cbreak mode, the kill
    skips its chance to restore it, and the terminal stays broken (Enter
    shows a literal ^M, no further input works) for the rest of the
    session -- exactly what got reported, and exactly what a piped-stdin
    test (every earlier verification of the REPL fix) could never catch.
    Wraps the real `subprocess.run` rather than faking it, so these stay
    real end-to-end behavior tests, just with `stdin` observed."""

    def _spy(self):
        calls = []
        real_run = subprocess.run

        def _wrapped(*args, **kwargs):
            calls.append(kwargs)
            return real_run(*args, **kwargs)

        return calls, _wrapped

    async def test_run_python_sandboxed(self):
        calls, spy = self._spy()
        config = Config(repo_root=Path.cwd(), sandbox_timeout_s=5.0)
        with unittest.mock.patch("simorgh.execution.tools.subprocess.run", side_effect=spy):
            await RunPythonSandboxedTool(config).run({"code": "print('hi')"}, ctx=_ctx(config))
        self.assertTrue(calls)
        for kwargs in calls:
            self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)

    async def test_run_js_sandboxed_uses_stdin_devnull(self):
        calls, spy = self._spy()
        config = Config(repo_root=Path.cwd(), sandbox_timeout_s=5.0)
        with unittest.mock.patch("simorgh.execution.tools.subprocess.run", side_effect=spy):
            await RunJsSandboxedTool(config, node_path="/usr/bin/env").run(
                {"code": "console.log('hi')"}, ctx=_ctx(config))
        self.assertTrue(calls)
        for kwargs in calls:
            self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)

    async def test_run_js_sandboxed_reports_real_output(self):
        import shutil as _shutil

        node = _shutil.which("node")
        if not node:
            self.skipTest("node not installed on this machine")
        config = Config(repo_root=Path.cwd(), sandbox_timeout_s=5.0)
        result = await RunJsSandboxedTool(config).run({"code": "console.log(2 + 2)"}, ctx=_ctx(config))
        self.assertTrue(result.ok, result.error)
        self.assertIn("4", result.output)

    async def test_run_js_sandboxed_is_refused_with_no_node_on_the_machine(self):
        config = Config(repo_root=Path.cwd())
        tool = RunJsSandboxedTool(config, node_path=None)
        result = await tool.run({"code": "console.log(1)"}, ctx=_ctx(config))
        self.assertFalse(result.ok)
        self.assertIn("node", result.error)

    async def test_run_js_sandboxed_reports_a_real_syntax_error(self):
        import shutil as _shutil

        node = _shutil.which("node")
        if not node:
            self.skipTest("node not installed on this machine")
        config = Config(repo_root=Path.cwd(), sandbox_timeout_s=5.0)
        result = await RunJsSandboxedTool(config).run({"code": "this is not js("}, ctx=_ctx(config))
        self.assertFalse(result.ok)
        self.assertIn("exit_code", result.error)

    async def test_skill_execution(self):
        calls, spy = self._spy()
        config = Config(repo_root=Path.cwd(), sandbox_timeout_s=5.0)
        tool = SkillTool(config, skill_name="greet", description="greets", source="def run():\n    return 'hi'\n")
        with unittest.mock.patch("simorgh.execution.tools.subprocess.run", side_effect=spy):
            await tool.run({}, ctx=_ctx(config))
        self.assertTrue(calls)
        for kwargs in calls:
            self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)

    async def test_git_commit(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _git(root, "init", "-q")
        _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-q", "-m", "init")
        (root / "changed.txt").write_text("v1")
        config = Config(repo_root=root)

        calls, spy = self._spy()
        with unittest.mock.patch("simorgh.execution.tools.subprocess.run", side_effect=spy):
            await GitCommitTool(config).run({"path": "changed.txt", "message": "m"}, ctx=_ctx(config))
        self.assertTrue(calls)
        for kwargs in calls:
            self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)

    async def test_git_revert(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        _git(root, "init", "-q")
        _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-q", "-m", "init")
        (root / "a.txt").write_text("v1")
        _git(root, "add", "a.txt")
        _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "add a.txt")
        config = Config(repo_root=root)

        calls, spy = self._spy()
        with unittest.mock.patch("simorgh.execution.tools.subprocess.run", side_effect=spy):
            await GitRevertTool(config).run({}, ctx=_ctx(config))
        self.assertTrue(calls)
        for kwargs in calls:
            self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL)


class TestProposeMcpServerTool(unittest.IsolatedAsyncioTestCase):
    """`ProposeMcpServerTool`'s own docstring: Sim's half of "propose a
    server, one human approval" -- validates and records, never touches
    `simorgh.toml` itself (`interface/dispatch.py`'s `mcp` command,
    tested separately, is the only code path that does)."""

    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()

    async def asyncTearDown(self):
        await self.ledger.stop()

    def _ctx(self):
        from simorgh.contracts.protocols import ToolContext
        return ToolContext(
            action_id="a1", task_id=None, scope={}, constraints={},
            data_dir=Path("."), clock=self.clock, logger=None, ledger=self.ledger,
        )

    async def test_records_a_valid_proposal_pending_in_the_ledger(self):
        proposal = (
            "name: ddg_search\n"
            "command: npx\n"
            "args: -y, ddg-search-mcp\n"
            "read_only_tools: ddg_search, ddg_get_answer\n"
            "reason: free web search, no API key needed"
        )
        result = await ProposeMcpServerTool().run({"proposal": proposal}, ctx=self._ctx())
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["name"], "ddg_search")
        events = await self.ledger.read(MCP_PROPOSALS_STREAM)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["status"], "pending")
        self.assertEqual(events[0].payload["command"], "npx")
        self.assertEqual(events[0].payload["args"], ["-y", "ddg-search-mcp"])
        self.assertEqual(events[0].payload["read_only_tools"], ["ddg_search", "ddg_get_answer"])
        self.assertEqual(events[0].payload["proposal_id"], result.metadata["proposal_id"])

    async def test_a_multiline_reason_is_kept_whole(self):
        proposal = "name: x\ncommand: npx\nreason: line one\nline two"
        result = await ProposeMcpServerTool().run({"proposal": proposal}, ctx=self._ctx())
        self.assertTrue(result.ok)
        events = await self.ledger.read(MCP_PROPOSALS_STREAM)
        self.assertEqual(events[0].payload["reason"], "line one\nline two")

    async def test_rejects_an_invalid_name(self):
        result = await ProposeMcpServerTool().run(
            {"proposal": "name: DDG Search\ncommand: npx\nreason: x"}, ctx=self._ctx(),
        )
        self.assertFalse(result.ok)
        self.assertIn("name", result.error)
        self.assertEqual(await self.ledger.read(MCP_PROPOSALS_STREAM), [])

    async def test_rejects_a_disallowed_command(self):
        result = await ProposeMcpServerTool().run(
            {"proposal": "name: x\ncommand: bash\nreason: y"}, ctx=self._ctx(),
        )
        self.assertFalse(result.ok)
        self.assertIn("command", result.error)

    async def test_requires_a_reason(self):
        result = await ProposeMcpServerTool().run({"proposal": "name: x\ncommand: npx"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("reason", result.error)

    async def test_rejects_a_malformed_env_key(self):
        result = await ProposeMcpServerTool().run(
            {"proposal": "name: x\ncommand: npx\nreason: y\nenv_keys: sk-abc123lowercase"}, ctx=self._ctx(),
        )
        self.assertFalse(result.ok)
        self.assertIn("env key", result.error)

    async def test_env_keys_never_carries_a_value_only_names(self):
        proposal = "name: x\ncommand: npx\nreason: y\nenv_keys: BRAVE_API_KEY, ANOTHER_KEY"
        result = await ProposeMcpServerTool().run({"proposal": proposal}, ctx=self._ctx())
        self.assertTrue(result.ok)
        events = await self.ledger.read(MCP_PROPOSALS_STREAM)
        self.assertEqual(events[0].payload["env_keys"], ["BRAVE_API_KEY", "ANOTHER_KEY"])

    async def test_a_json_object_argument_is_accepted_too(self):
        """Live-caught (the creator, real use): asked to use this tool,
        the model wrote `{"name": "web-search", "command": "npx", ...}`
        instead of the documented `key: value` lines -- a very natural
        pull toward JSON for structured data. Recognized keys are
        extracted the same as the line-based format."""
        proposal = json.dumps({
            "name": "web_search", "command": "npx", "args": ["-y", "some-mcp-package"],
            "reason": "real web search, no key needed",
        })
        result = await ProposeMcpServerTool().run({"proposal": proposal}, ctx=self._ctx())
        self.assertTrue(result.ok, result.error)
        events = await self.ledger.read(MCP_PROPOSALS_STREAM)
        self.assertEqual(events[0].payload["name"], "web_search")
        self.assertEqual(events[0].payload["args"], ["-y", "some-mcp-package"])

    async def test_a_json_objects_unrecognized_keys_are_dropped_not_guessed_at(self):
        # The live example used "description" instead of the real
        # "reason" field -- must not be silently accepted as an alias;
        # the resulting proposal should fail validation honestly.
        proposal = json.dumps({"name": "web_search", "description": "does a web search"})
        result = await ProposeMcpServerTool().run({"proposal": proposal}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("command", result.error)

    async def test_malformed_json_falls_back_to_line_parsing_not_a_crash(self):
        result = await ProposeMcpServerTool().run(
            {"proposal": '{"name": "x", not valid json'}, ctx=self._ctx(),
        )
        self.assertFalse(result.ok)  # falls through to line parsing, finds no real fields
        self.assertIn("name", result.error)


class TestBuiltinTools(unittest.TestCase):
    def test_registers_exactly_the_scoped_set(self):
        names = {tool.name for tool in builtin_tools(Config(repo_root=Path.cwd()))}
        self.assertEqual(names, {
            "read_file", "list_dir", "search_code", "self_map", "run_python_sandboxed",
            "run_js_sandboxed", "run_tests",
            "apply_source_patch", "replace_in_file", "start_task",
            "git_commit", "git_revert", "git_discard", "apply_skill",
            "web_fetch", "web_search", "render_page", "search_listings", "geocode",
            "find_package", "install_package", "run_script",
            "browse_page", "run_container", "notify",
            "kb_search", "kb_ask", "kb_open", "kb_sources", "kb_status",
            "cal_list", "mail_search", "mail_read", "remind",
            "sec_self", "sec_posture", "sec_findings", "sec_show", "sec_accept",
            "home_find", "home_state", "home_describe", "home_call", "home_undo",
            "energy_status", "energy_report", "energy_tariff",
            "media_now", "media_control", "media_play",
            "propose_mcp_server", "run_shell",
        })


class _FakeFetchResponse:
    """A stand-in for an HTTP response, and it CONSUMES what it hands
    out.

    It used to return the same bytes from the start on every `read(n)`,
    which no real stream does. The moment `web_fetch` read a header and
    then the body -- which it must, to tell a PDF from a web page before
    choosing how much to read -- the fake handed back the body twice and
    the test failed on code that was correct (2026-09-08). A double that
    is more forgiving than the real thing tests nothing."""

    def __init__(self, data: bytes, status: int = 200) -> None:
        self._data = data
        self._pos = 0
        self.status = status

    def read(self, n: int = -1) -> bytes:
        chunk = self._data[self._pos:] if n is None or n < 0 else self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> "_FakeFetchResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class TestWebFetchTool(unittest.IsolatedAsyncioTestCase):
    """08-execution.md section 5.2's `web_fetch` row: SSRF-guarded,
    size/rate-capped GET. `opener`/`resolver` are injected (v1's own
    testing seam, `src/tools/web_fetch.py`) so no real network call or
    DNS lookup happens here."""

    def setUp(self):
        self.config = Config()
        self.clock = FakeClock()

    def _ctx(self) -> "ToolContext":
        from simorgh.contracts.protocols import ToolContext
        return ToolContext(
            action_id="a1", task_id=None, scope={}, constraints={},
            data_dir=self.config.repo_root, clock=self.clock, logger=None, ledger=None,
        )

    def _public_resolver(self, host, port):
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    async def test_fetches_and_returns_the_body_with_metadata(self):
        tool = WebFetchTool(
            self.config, resolver=self._public_resolver,
            opener=lambda req, timeout: _FakeFetchResponse(b"hello world", status=200),
        )
        result = await tool.run({"url": "https://example.com/"}, ctx=self._ctx())
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "hello world")
        self.assertEqual(result.metadata["url"], "https://example.com/")
        self.assertEqual(result.metadata["status"], 200)
        self.assertEqual(result.metadata["fetched_at"], self.clock.now())
        self.assertEqual(len(result.metadata["sha256"]), 64)

    async def test_refuses_a_non_http_scheme(self):
        tool = WebFetchTool(self.config)
        result = await tool.run({"url": "ftp://example.com/file"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("only http/https", result.error)

    async def test_refuses_a_url_that_resolves_to_a_private_address(self):
        tool = WebFetchTool(self.config, resolver=lambda host, port: [(2, 1, 6, "", ("127.0.0.1", 0))])
        result = await tool.run({"url": "http://internal.example/"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("SSRF", result.error)

    async def test_refuses_a_url_that_resolves_to_a_metadata_endpoint(self):
        # 169.254.169.254 -- the cloud-metadata SSRF target the execution
        # spec calls out by name (08-execution.md section 5.2).
        tool = WebFetchTool(self.config, resolver=lambda host, port: [(2, 1, 6, "", ("169.254.169.254", 0))])
        result = await tool.run({"url": "http://169.254.169.254/"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("SSRF", result.error)

    async def test_a_dns_failure_is_refused_not_a_crash(self):
        import socket as socket_mod

        def _raise(host, port):
            raise socket_mod.gaierror("nodename nor servname provided")

        tool = WebFetchTool(self.config, resolver=_raise)
        result = await tool.run({"url": "http://does-not-resolve.invalid/"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("could not resolve", result.error)

    async def test_truncates_at_the_configured_max_bytes(self):
        config = Config(web_fetch_max_bytes=5)
        tool = WebFetchTool(
            config, resolver=self._public_resolver,
            opener=lambda req, timeout: _FakeFetchResponse(b"hello world", status=200),
        )
        result = await tool.run({"url": "https://example.com/"}, ctx=self._ctx())
        self.assertTrue(result.ok)
        self.assertEqual(result.output, "hello")
        self.assertTrue(result.metadata["truncated"])

    async def test_a_network_failure_becomes_a_result_not_a_crash(self):
        def _raise(req, timeout):
            raise OSError("connection refused")

        tool = WebFetchTool(self.config, resolver=self._public_resolver, opener=_raise)
        result = await tool.run({"url": "https://example.com/"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertIn("fetch failed", result.error)

    async def test_rate_limit_is_enforced_within_the_window(self):
        config = Config(web_fetch_max_calls=2, web_fetch_window_s=3600.0)
        tool = WebFetchTool(
            config, resolver=self._public_resolver,
            opener=lambda req, timeout: _FakeFetchResponse(b"ok"),
        )
        ctx = self._ctx()
        self.assertTrue((await tool.run({"url": "https://example.com/a"}, ctx=ctx)).ok)
        self.assertTrue((await tool.run({"url": "https://example.com/b"}, ctx=ctx)).ok)
        third = await tool.run({"url": "https://example.com/c"}, ctx=ctx)
        self.assertFalse(third.ok)
        self.assertIn("rate limit", third.error)

    async def test_rate_limit_window_rolls_off_old_calls(self):
        config = Config(web_fetch_max_calls=1, web_fetch_window_s=60.0)
        tool = WebFetchTool(
            config, resolver=self._public_resolver,
            opener=lambda req, timeout: _FakeFetchResponse(b"ok"),
        )
        ctx = self._ctx()
        self.assertTrue((await tool.run({"url": "https://example.com/a"}, ctx=ctx)).ok)
        self.assertFalse((await tool.run({"url": "https://example.com/b"}, ctx=ctx)).ok)
        self.clock.advance(61.0)
        self.assertTrue((await tool.run({"url": "https://example.com/c"}, ctx=ctx)).ok)

    async def test_one_site_does_not_use_up_every_other_site(self):
        """The limit is politeness to a host, not a research budget.

        It used to be one bucket for the whole internet, so a thorough
        piece of work locked the tool for everything that followed. A
        GAIA run on 2026-09-10 spent 103 of 682 steps on fetches this
        limiter refused, most of them for hosts never touched before."""
        config = Config(web_fetch_max_calls=2, web_fetch_window_s=3600.0)
        tool = WebFetchTool(
            config, resolver=self._public_resolver,
            opener=lambda req, timeout: _FakeFetchResponse(b"ok"),
        )
        ctx = self._ctx()
        self.assertTrue((await tool.run({"url": "https://example.com/a"}, ctx=ctx)).ok)
        self.assertTrue((await tool.run({"url": "https://example.com/b"}, ctx=ctx)).ok)
        self.assertFalse((await tool.run({"url": "https://example.com/c"}, ctx=ctx)).ok)
        # A different host has its own allowance.
        self.assertTrue((await tool.run({"url": "https://other.example.org/a"}, ctx=ctx)).ok)

    async def test_a_whole_tool_ceiling_still_bounds_a_runaway_loop(self):
        config = Config(web_fetch_max_calls=5, web_fetch_max_total_calls=3,
                        web_fetch_window_s=3600.0)
        tool = WebFetchTool(
            config, resolver=self._public_resolver,
            opener=lambda req, timeout: _FakeFetchResponse(b"ok"),
        )
        ctx = self._ctx()
        for index in range(3):
            self.assertTrue((await tool.run({"url": f"https://h{index}.example.com/"}, ctx=ctx)).ok)
        stopped = await tool.run({"url": "https://h9.example.com/"}, ctx=ctx)
        self.assertFalse(stopped.ok)
        self.assertIn("across every host", stopped.error)

    async def test_a_refusal_says_how_long_the_door_stays_shut(self):
        """A refusal that says only "30/30" reads as a transient failure,
        and the model answers it by trying the same fetch again."""
        config = Config(web_fetch_max_calls=1, web_fetch_window_s=3600.0)
        tool = WebFetchTool(
            config, resolver=self._public_resolver,
            opener=lambda req, timeout: _FakeFetchResponse(b"ok"),
        )
        ctx = self._ctx()
        await tool.run({"url": "https://example.com/a"}, ctx=ctx)
        refused = await tool.run({"url": "https://example.com/b"}, ctx=ctx)
        self.assertFalse(refused.ok)
        self.assertIn("60 minutes", refused.error)
        self.assertIn("refused the same way", refused.error)

    async def test_allow_private_networks_skips_the_ssrf_guard(self):
        config = Config(web_fetch_allow_private_networks=True)

        def _fail_if_called(host, port):
            raise AssertionError("resolver should not be consulted when private networks are allowed")

        tool = WebFetchTool(
            config, resolver=_fail_if_called,
            opener=lambda req, timeout: _FakeFetchResponse(b"local"),
        )
        result = await tool.run({"url": "http://127.0.0.1:8000/"}, ctx=self._ctx())
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()


class TestWebFetchOnAPdf(unittest.IsolatedAsyncioTestCase):
    """A fetched PDF used to come back as `%PDF-1.5` plus binary stream
    data under `ok=True`, and the model was told nothing was wrong."""

    def setUp(self):
        self.config = Config()
        self.clock = FakeClock()

    def _ctx(self) -> "ToolContext":
        from simorgh.contracts.protocols import ToolContext
        return ToolContext(
            action_id="a1", task_id=None, scope={}, constraints={},
            data_dir=self.config.repo_root, clock=self.clock, logger=None, ledger=None,
        )

    def _tool(self, body: bytes) -> WebFetchTool:
        return WebFetchTool(
            self.config, resolver=lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))],
            opener=lambda req, timeout: _FakeFetchResponse(body, status=200),
        )

    async def test_a_pdf_comes_back_as_readable_text(self):
        from tests.simorgh.execution.test_pdftext import make_pdf

        tool = self._tool(make_pdf("the answer is in this document"))
        result = await tool.run({"url": "https://example.com/paper.pdf"}, ctx=self._ctx())
        self.assertTrue(result.ok)
        self.assertIn("the answer is in this document", result.output)
        self.assertNotIn("endobj", result.output)
        self.assertEqual(result.metadata["kind"], "pdf")

    async def test_a_pdf_served_from_a_url_with_no_extension_is_still_read(self):
        from tests.simorgh.execution.test_pdftext import make_pdf

        tool = self._tool(make_pdf("served from a bare path"))
        result = await tool.run({"url": "https://example.com/download?id=7"}, ctx=self._ctx())
        self.assertIn("served from a bare path", result.output)

    async def test_an_unreadable_pdf_fails_loudly_instead_of_succeeding_empty(self):
        tool = self._tool(b"%PDF-1.4\ntruncated garbage")
        result = await tool.run({"url": "https://example.com/broken.pdf"}, ctx=self._ctx())
        self.assertFalse(result.ok)
        self.assertTrue(result.error)

    async def test_an_html_page_is_untouched_by_the_pdf_path(self):
        tool = self._tool(b"<html><body><p>ordinary page</p></body></html>")
        result = await tool.run({"url": "https://example.com/"}, ctx=self._ctx())
        self.assertTrue(result.ok)
        self.assertNotEqual(result.metadata.get("kind"), "pdf")


class TestWriteScopeRefusalNamesTheScopes(unittest.IsolatedAsyncioTestCase):
    """A bare "outside the writable scope" taught the model nothing, so
    when it guessed the scopes wrong it had no way to find out."""

    async def test_the_refusal_lists_where_it_could_have_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(repo_root=Path(tmp))
            result = await ApplySourcePatchTool(config).run(
                {"subject": "nowhere/x.py", "code": "x = 1\n"}, ctx=_ctx(config))
        self.assertFalse(result.ok)
        for scope in config.write_scopes_source:
            self.assertIn(scope, result.error)
