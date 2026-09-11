"""`run_tests` must not freeze the Kernel, and must be given its own
budget by the execution service.

Measured live, 2026-09-10, in a sandbox boot of the real CLI: a host
`run_tests` of 271.7s left a 272.4s hole in the task's lease heartbeats
and a 280.8s hole in `metrics:history` -- the coroutine called
`subprocess.run` directly and the event loop did not turn once. The
same freeze hid a second fault: `execution/service.py` bounds every
tool with `default_timeout_s` (60s) unless the approval carries a
`timeout_s` constraint, which nothing ever sets. A host run could not
be cut (the loop was frozen); an in-container run, which runs in a
thread, could -- at 60s, against the tool's own 300s budget.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts.protocols import ToolContext
from simorgh.execution import tools as tools_module
from simorgh.execution.config import Config
from simorgh.execution.service import timeout_for
from simorgh.execution.tools import RunTestsTool


def _ctx(config: Config) -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=config.repo_root, clock=None, logger=None, ledger=None)


class TheLoopKeepsTurning(unittest.IsolatedAsyncioTestCase):
    async def test_a_host_run_does_not_block_other_coroutines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_x.py").write_text("def test_x():\n    assert True\n")
            config = Config(repo_root=root)

            def slow_pytest(*args, **kwargs):
                import time
                time.sleep(0.6)
                return subprocess.CompletedProcess(args[0], 0, stdout="1 passed\n", stderr="")

            ticks = 0

            async def ticker():
                nonlocal ticks
                while True:
                    await asyncio.sleep(0.05)
                    ticks += 1

            task = asyncio.create_task(ticker())
            try:
                with mock.patch.object(tools_module.subprocess, "run", side_effect=slow_pytest):
                    result = await RunTestsTool(config).run({"target": "tests"}, ctx=_ctx(config))
            finally:
                task.cancel()
            self.assertTrue(result.ok, result.error)
            # A frozen loop gives the ticker nothing; a live one gives it
            # most of the 0.6s.
            self.assertGreaterEqual(ticks, 5, f"the event loop turned only {ticks} times during run_tests")


class TheServiceHonoursTheToolsBudget(unittest.TestCase):
    def test_run_tests_declares_more_than_its_own_subprocess_timeout(self):
        config = Config(repo_root=Path("."), test_timeout_s=300.0)
        self.assertGreater(RunTestsTool(config).timeout_s, 300.0)

    def test_a_declared_budget_beats_the_default(self):
        config = Config(repo_root=Path("."), test_timeout_s=300.0)
        self.assertEqual(timeout_for(RunTestsTool(config), {}, 60.0), 330.0)

    def test_a_constraint_on_the_approval_still_wins(self):
        config = Config(repo_root=Path("."), test_timeout_s=300.0)
        self.assertEqual(timeout_for(RunTestsTool(config), {"timeout_s": 5}, 60.0), 5.0)

    def test_a_tool_with_no_opinion_gets_the_default(self):
        self.assertEqual(timeout_for(object(), {}, 60.0), 60.0)


if __name__ == "__main__":
    unittest.main()
