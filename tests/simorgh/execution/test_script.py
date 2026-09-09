"""`run_script` (execution/script.py): real Python, repo importable,
network reachable -- the narrow alternative to `run_shell` for using an
installed library.

These run the real interpreter. The Guardian half of the contract (a
hand-written `requests.get(` in this payload is refused exactly as it is
in the sandbox) is asserted in tests/simorgh/guardian/test_rules.py,
where the rules live -- `code` is the key both read.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.script import RunScriptTool


def _ctx(config, constraints=None, action_id="a1"):
    from simorgh.contracts.protocols import ToolContext

    return ToolContext(action_id=action_id, task_id=None, scope={}, constraints=constraints or {},
                       data_dir=config.repo_root, clock=None, logger=None, ledger=None)


class RunScriptTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.config = Config(repo_root=self.root, script_timeout_s=30.0)

    async def test_it_runs_and_returns_stdout(self):
        result = await RunScriptTool(self.config).run(
            {"code": "print(2 + 2)"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.metadata.get("stderr"))
        self.assertIn("4", result.output)

    async def test_a_failing_script_reports_its_traceback(self):
        result = await RunScriptTool(self.config).run(
            {"code": "raise ValueError('boom')"}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        self.assertIn("exit_code", result.error)
        self.assertIn("boom", result.metadata["stderr"])

    async def test_the_repo_is_importable(self):
        # The difference from run_python_sandboxed, which has no repo
        # access at all: a script here can use the project's own code.
        (self.root / "mypkg").mkdir()
        (self.root / "mypkg" / "__init__.py").write_text("VALUE = 41\n")
        result = await RunScriptTool(self.config).run(
            {"code": "import mypkg; print(mypkg.VALUE + 1)"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.metadata.get("stderr"))
        self.assertIn("42", result.output)

    async def test_an_empty_payload_is_refused(self):
        result = await RunScriptTool(self.config).run({"code": "  "}, ctx=_ctx(self.config))
        self.assertFalse(result.ok)
        self.assertIn("no code given", result.error)

    async def test_a_timeout_is_reported_not_hung(self):
        config = Config(repo_root=self.root, script_timeout_s=1.0)
        result = await RunScriptTool(config).run(
            {"code": "import time; time.sleep(30)"}, ctx=_ctx(config))
        self.assertFalse(result.ok)
        self.assertEqual(result.error, "timeout")

    async def test_the_environment_is_curated_not_inherited_wholesale(self):
        # A subprocess should not inherit every credential in the
        # session just because it needs PATH to reach the network.
        import os

        os.environ["SIMORGH_TEST_SECRET_XYZ"] = "should-not-leak"
        self.addCleanup(os.environ.pop, "SIMORGH_TEST_SECRET_XYZ", None)
        result = await RunScriptTool(self.config).run(
            {"code": "import os; print(os.environ.get('SIMORGH_TEST_SECRET_XYZ', 'absent'))"},
            ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.metadata.get("stderr"))
        self.assertIn("absent", result.output)
        self.assertNotIn("should-not-leak", result.output)

    async def test_path_is_passed_through_so_a_library_can_reach_the_network(self):
        result = await RunScriptTool(self.config).run(
            {"code": "import os; print('PATH' in os.environ)"}, ctx=_ctx(self.config))
        self.assertIn("True", result.output)

    async def test_scripts_are_staged_and_pruned(self):
        config = Config(repo_root=self.root, script_keep_files=2, script_timeout_s=30.0)
        for i in range(4):
            await RunScriptTool(config).run({"code": "pass"}, ctx=_ctx(config, action_id=f"a{i}"))
        staged = list((self.root / config.script_dir).glob("*.py"))
        self.assertEqual(len(staged), 2)

    async def test_stdin_is_never_the_terminal(self):
        # Same rule as every other subprocess in this package: a tool
        # that inherits the creator's stdin can wedge their terminal.
        result = await RunScriptTool(self.config).run(
            {"code": "import sys; print(sys.stdin.read())"}, ctx=_ctx(self.config))
        self.assertTrue(result.ok, result.metadata.get("stderr"))
        self.assertEqual(result.output.strip(), "")
