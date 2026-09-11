"""'Never started' and 'started and did not finish' are different facts.

The 18:37 run on 2026-09-10: both cases `steps 0`, `blocked_by: no
answer within 600s`, recorded as answers our own pipeline stopped. They
had sat on the queue behind 312 synthetic tasks for the whole allowance
and were never so much as read. Nothing had been asked.

And a run does not survive a restart, but its tasks did: four
`benchmark`-origin tasks from four dead runs sat ahead of the case a
fresh run created -- same weight, older -- so the fresh case's clock ran
while the single worker cleared ghosts against checkouts already
deleted. At boot the benchmark service now cancels every open
benchmark task; nothing can be waiting for one.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.benchmark import datasets as datasets_mod
from simorgh.benchmark import swebench
from simorgh.benchmark.api import Case, Suite
from simorgh.benchmark.runner import _AnswerWatch, _UNASKED
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel


class _Bus:
    """Just enough bus for the watch: subscribe, and a way to deliver."""

    def __init__(self):
        self.handlers: dict[str, list] = {}

    async def subscribe(self, topic, handler, **_):
        self.handlers.setdefault(topic, []).append(handler)

        class _Sub:
            async def unsubscribe(self_inner):
                pass
        return _Sub()

    async def deliver(self, topic, payload):
        for h in self.handlers.get(topic, []):
            await h(Message.new(topic, source="test", payload=payload))


class WaitStartedTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bus = _Bus()
        self.watch = _AnswerWatch(self.bus)
        await self.watch.start()

    async def test_nothing_started_is_false_after_the_timeout(self):
        self.assertFalse(await self.watch.wait_started("t1", 0.05))

    async def test_a_start_releases_the_wait(self):
        waiter = asyncio.create_task(self.watch.wait_started("t1", 2.0))
        await asyncio.sleep(0.01)
        await self.bus.deliver(topics.TASK_STARTED, {"task_id": "t1", "worker_id": "w"})
        self.assertTrue(await waiter)

    async def test_a_task_that_finished_counts_as_started(self):
        # The outcome can arrive before the start is observed.
        await self.bus.deliver(topics.TASK_COMPLETED, {"task_id": "t1", "result": "done"})
        self.assertTrue(await self.watch.wait_started("t1", 0.05))

    async def test_a_start_seen_before_the_wait_is_remembered(self):
        await self.bus.deliver(topics.TASK_STARTED, {"task_id": "t1", "worker_id": "w"})
        self.assertTrue(await self.watch.wait_started("t1", 0.05))


class ANeverStartedSwebenchCaseIsSkippedTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_it_is_skipped_not_scored_wrong(self):
        from simorgh.benchmark.config import Config
        from simorgh.benchmark.runner import Runner

        case = Case(id="c1", question="q", answer="", level="<15 min fix", suite="swebench-verified",
                    mode="swebench", data='{"image": "img", "eval_script": "x", "base_commit": "abc"}')
        runner = Runner.__new__(Runner)
        runner._config = Config()
        runner._repo_root = Path(tempfile.mkdtemp())
        runner._bus = None
        runner._clock = None
        with mock.patch.object(swebench, "available", return_value=(True, "")), \
             mock.patch.object(swebench, "materialize", return_value=""), \
             mock.patch.object(Runner, "_ask", return_value=("", 0, 0.0, f"{_UNASKED} not started within 1800s -- the queue never reached it")), \
             mock.patch.object(swebench, "evaluate") as evaluate:
            result = await runner._run_swebench(case)
        self.assertTrue(result.skipped)
        self.assertFalse(result.correct)
        self.assertIn("never reached it", result.error)
        evaluate.assert_not_called()


class OrphanedCasesAreCancelledAtBootTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_restart_cancels_open_benchmark_tasks_and_nothing_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            kernel = Kernel(LoadedConfig({
                "runtime": {"data_dir": str(Path(tmp) / "data")},
                "curiosity": {"autonomy_on_boot": False},
                "orchestration": {"workers": 0},
            }, None), secrets=EnvSecretStore({}))
            await kernel.boot()
            try:
                bus = kernel.bus
                ghost = await bus.request(bus.new(topics.TASK_CREATE, {
                    "kind": "patch", "description": "Fix this bug in the repository checked out at `workspace/swebench/x`",
                    "origin": "benchmark", "mode": "execute"}), timeout=10)
                human = await bus.request(bus.new(topics.TASK_CREATE, {
                    "kind": "patch", "description": "a person asked for this", "origin": "human", "mode": "execute"}), timeout=10)
                ghost_id, human_id = ghost.payload["task_id"], human.payload["task_id"]

                service = kernel._supervisor.services["benchmark"].service  # noqa: SLF001
                ctx = service._ctx  # noqa: SLF001
                await service.stop()
                await service.start(ctx)  # "the next boot"

                async def _status(task_id):
                    reply = await bus.request(bus.new(topics.TASK_LIST_REQUEST, {}), timeout=10)
                    return {t["task_id"]: t["status"] for t in reply.payload["tasks"]}.get(task_id)

                for _ in range(100):
                    if await _status(ghost_id) not in ("available", "pending"):
                        break
                    await asyncio.sleep(0.05)
                self.assertNotIn(await _status(ghost_id), ("available", "pending"),
                                 "the dead run's case must not wait for a worker")
                self.assertIn(await _status(human_id), ("available", "pending"),
                              "a person's task is not the benchmark's to cancel")
            finally:
                await kernel.shutdown()


if __name__ == "__main__":
    unittest.main()
