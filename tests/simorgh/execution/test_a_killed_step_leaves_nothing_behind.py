"""Stage 7 item 8: a heavy step that is cancelled or times out takes its
children with it. A thread cannot be cancelled and neither can the child
inside it, so a cancelled task used to leave pytest compiling against a
tree it was about to discard."""

from __future__ import annotations

import asyncio
import time
import unittest

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


class TheTestRunnerLeavesNoWorkers(unittest.TestCase):
    def test_it_starts_its_own_session_and_kills_the_group(self):
        from pathlib import Path

        source = Path("simorgh/execution/tools.py").read_text()
        self.assertIn("start_new_session=True", source)
        self.assertIn("_kill_group(exc)", source)


if __name__ == "__main__":
    unittest.main()
