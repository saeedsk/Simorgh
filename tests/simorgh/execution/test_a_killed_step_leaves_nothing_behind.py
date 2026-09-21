"""Stage 7 item 8: a heavy step that is cancelled or times out takes its
children with it. A thread cannot be cancelled and neither can the child
inside it, so a cancelled task used to leave pytest compiling against a
tree it was about to discard."""

from __future__ import annotations

import asyncio
import time
import unittest
import uuid

from simorgh.execution.procs import alive, run_child

SLEEPER = ["python3", "-c", "import time; print('here', flush=True); time.sleep(30)"]


class AKilledStep(unittest.IsolatedAsyncioTestCase):
    async def test_a_timeout_kills_the_child_and_keeps_what_it_said(self):
        done = await run_child(SLEEPER, timeout=0.6)
        self.assertTrue(done.timed_out)
        self.assertTrue(done.killed)
        self.assertIn("here", done.stdout, "half a run tells you more than nothing")
        self.assertLess(done.seconds, 5.0)

    async def test_a_cancelled_step_is_gone_within_two_seconds(self):
        pids: list[int] = []

        async def _run():
            # The pid is captured through the same call the tool makes, so
            # the test proves the child is gone rather than trusting it.
            proc = await asyncio.create_subprocess_exec(
                *SLEEPER, stdout=asyncio.subprocess.PIPE, start_new_session=True)
            pids.append(proc.pid)
            from simorgh.execution.procs import _end

            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                await _end(proc, [])
                raise

        task = asyncio.ensure_future(_run())
        await asyncio.sleep(0.2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        deadline = time.monotonic() + 2.0
        while alive(pids[0]) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        self.assertFalse(alive(pids[0]), "the child outlived the step that started it")

    async def test_an_ordinary_run_still_returns_what_it_printed(self):
        done = await run_child(["python3", "-c", "print('two'); import sys; sys.stderr.write('note')"])
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout.strip(), "two")
        self.assertEqual(done.stderr.strip(), "note")
        self.assertFalse(done.timed_out)


class TheTestRunnerLeavesNoWorkers(unittest.IsolatedAsyncioTestCase):
    """The acceptance of stage 7 item 8, against the tool itself.

    This used to read `tools.py` and assert the words
    `start_new_session=True` and `_kill_group(exc)` appeared in it,
    which is a test of a source file rather than of a behaviour --
    and it passed for the whole time `procs.py` existed and nothing
    imported it. `run_tests` really does run through `run_child` now,
    so the thing to assert is that cancelling the step leaves no
    pytest behind.
    """

    async def test_cancelling_run_tests_takes_pytest_with_it(self):
        import subprocess
        import tempfile
        from pathlib import Path

        from simorgh.contracts.protocols import ToolContext
        from simorgh.execution.config import Config
        from simorgh.execution.tools import RunTestsTool

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            # A suite that will not finish on its own.
            # A name generated at run time: the child's command line
            # carries the target, which is how the check below finds it
            # in `ps` (the temp directory is only the cwd, and `ps` does
            # not show that). Generated rather than fixed because a
            # literal marker also matches the shell that happens to be
            # editing this file -- which it did, once.
            marker = f"test_outlives_{uuid.uuid4().hex[:8]}"
            (root / "tests" / f"{marker}.py").write_text(
                "import time\n\ndef test_slow():\n    time.sleep(30)\n")
            config = Config(repo_root=root)
            ctx = ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                              data_dir=root, clock=None, logger=None, ledger=None)

            task = asyncio.ensure_future(
                RunTestsTool(config).run({"target": f"tests/{marker}.py"}, ctx=ctx))
            # Long enough for the copy and for pytest to be running.
            for _ in range(200):
                await asyncio.sleep(0.05)
                if _pytest_children(marker):
                    break
            started = _pytest_children(marker)
            if not started:
                self.skipTest("pytest never got far enough to be worth killing on this machine")
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            deadline = time.monotonic() + 2.0
            while _pytest_children(marker) and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            self.assertEqual(_pytest_children(marker), [],
                             "pytest outlived the step that started it")
            assert subprocess  # the import documents how the check below works


def _pytest_children(marker: str) -> list:
    """Live processes whose command line mentions `marker`.

    The target path is in the child's argv, which is what makes this
    findable; the temporary directory is only its cwd, and `ps` does
    not show that.
    """
    import subprocess

    try:
        out = subprocess.run(["ps", "-eo", "pid,command"], capture_output=True, text=True, timeout=5.0).stdout
    except Exception:  # noqa: BLE001 -- no `ps` is not a failing assertion
        return []
    # `-m pytest`, not just "pytest": the marker also appears in the
    # command line of whatever shell is running this test, and matching
    # that made the check fail on its own reflection.
    return [line for line in out.splitlines() if marker in line and "-m pytest" in line]


if __name__ == "__main__":
    unittest.main()
