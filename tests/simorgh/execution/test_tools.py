"""Per-tool tests for `execution.tools` (08-execution.md section 5.2),
each a port of a v1 tool. Uses throwaway temp directories/git repos --
never the real project repository."""

import subprocess
import tempfile
import unittest
import unittest.mock
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
    WebFetchTool,
    builtin_tools,
)

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


class TestBuiltinTools(unittest.TestCase):
    def test_registers_exactly_the_scoped_set(self):
        names = {tool.name for tool in builtin_tools(Config(repo_root=Path.cwd()))}
        self.assertEqual(names, {
            "read_file", "list_dir", "run_python_sandboxed",
            "apply_source_patch", "git_commit", "git_revert", "apply_skill", "web_fetch",
        })


class _FakeFetchResponse:
    def __init__(self, data: bytes, status: int = 200) -> None:
        self._data = data
        self.status = status

    def read(self, n: int = -1) -> bytes:
        return self._data if n is None or n < 0 else self._data[:n]

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
