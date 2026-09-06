"""`local-multi` mode's crash/resume drill (docs/blueprint/04-build-plan-
and-roadmap.md Phase 5 item 1: "`local-multi` mode: Worker processes on
the SQLite bus; crash/resume drills"; 03-kernel.md section 5.6;
16-orchestration.md S5/S7).

`tests/simorgh/orchestration/test_worker.py::TestResumeOnASecondWorker`
already proves the *logic* half in-process: a fresh `Session` restores
its step count from the Ledger. `tests/simorgh/bus/
test_sqlite_multiprocess.py` already proves a second OS process can
consume a durable competing delivery and that a dead process's expired
lease is reaped. Neither proves the two put together: a real `simorgh
worker` OS process is SIGKILLed mid-task, and a second real `simorgh
worker` OS process -- spawned fresh, sharing nothing but the sqlite
bus/ledger WAL file(s) on disk -- claims the same task and finishes it,
without redoing the step the first process already completed durably.
This test is that proof, using the real production entry points
(`simorgh.kernel.cli.main(["worker", ...])`, `WorkerKernel`), not a
reimplementation of the claim/resume logic.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import tempfile
import time
import unittest
from pathlib import Path

from simorgh.bus.enforcement import IdentityRegistry, ReservedTopologyPolicy
from simorgh.bus.factory import make_backend as make_bus_backend, make_client as make_bus_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.kernel.config import load_config
from simorgh.kernel.service import _bus_config_for, _ledger_mapping_for  # noqa: SLF001 -- shared test-only reuse
from simorgh.ledger.factory import make_ledger

CLAIM_TIMEOUT_S = 25.0
POLL_S = 0.05


def _write_config(tmp: Path) -> Path:
    path = tmp / "simorgh.toml"
    path.write_text(f"""
[runtime]
mode = "local-multi"
data_dir = "{tmp}"

[bus]
backend = "sqlite"
default_lease_seconds = 2.0
metrics_interval_seconds = 0

[bus.sqlite]
poll_interval_ms = 20

[ledger]
backend = "sqlite"
""")
    return path


def _run_worker(config_path: str, worker_id: str) -> None:
    """Module-level so `multiprocessing`'s `spawn` context can pickle it
    -- the real CLI entry point a human would run, not a test double."""
    from simorgh.kernel.cli import main

    main(["--config", config_path, "worker", "--id", worker_id])


class _Cognition:
    """Runs in the parent process, standing in for a real Cognition
    subsystem over the *same* shared sqlite bus every worker process also
    connects to. Scripted so the crash window is deterministic rather
    than raced against real wall-clock timing:
      call 1 (worker 1's first THINK)  -> a tool call (produces step 1)
      call 2 (worker 1's second THINK) -> never answered; worker 1 is
                                           killed well before this could
                                           time out, simulating a real
                                           crash mid-session
      call 3+ (worker 2's first THINK) -> final text; worker 2 resumes
                                           at step 2, not step 1
    """

    def __init__(self, bus) -> None:
        self._bus = bus
        self._sub = None
        self.call_count = 0

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.COGNITION_THINK, self._on)

    async def stop(self) -> None:
        if self._sub is not None:
            await self._sub.unsubscribe()

    async def _on(self, message: Message) -> None:
        self.call_count += 1
        if self.call_count == 1:
            payload = {"text": "", "tool_calls": [{"tool": "read_file", "args": {"path": "x"}}],
                      "provider": "fake", "cost_usd": 0.0, "tokens": 10, "floor": False, "non_answer": False}
        elif self.call_count == 2:
            return  # deliberately unanswered -- see class docstring
        else:
            payload = {"text": "done", "tool_calls": [], "provider": "fake", "cost_usd": 0.0, "tokens": 5,
                      "floor": False, "non_answer": False}
        await self._bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload=payload)


class _GuardianExecution:
    def __init__(self, bus) -> None:
        self._bus = bus
        self._sub = None
        self.proposals: list[Message] = []

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.ACTION_PROPOSED, self._on)

    async def stop(self) -> None:
        if self._sub is not None:
            await self._sub.unsubscribe()

    async def _on(self, message: Message) -> None:
        self.proposals.append(message)
        result = message.caused(topics.ACTION_RESULT, {
            "action_id": message.payload["action_id"], "ok": True, "output_ref": "",
            "stdout_preview": f"ran {message.payload['tool']}", "duration_ms": 1, "side_effects": [],
        }, source="execution")
        await self._bus.publish(result)


class _Planning:
    def __init__(self, bus) -> None:
        self._bus = bus
        self._sub = None
        self._tasks: dict[str, dict] = {}

    def add_task(self, task_id: str, **fields) -> None:
        self._tasks[task_id] = fields

    async def start(self) -> None:
        self._sub = await self._bus.subscribe(topics.TASK_CLAIM, self._on)

    async def stop(self) -> None:
        if self._sub is not None:
            await self._sub.unsubscribe()

    async def _on(self, message: Message) -> None:
        task = self._tasks.get(message.payload["task_id"])
        await self._bus.reply(message, type=topics.TASK_CLAIM_REPLY,
                              payload={"granted": task is not None, "task": task or {}})


class TestWorkerCrashIsResumedByASecondProcess(unittest.TestCase):
    def test_a_killed_worker_process_is_resumed_by_a_fresh_one(self):
        with tempfile.TemporaryDirectory() as tmp_s:
            tmp = Path(tmp_s)
            config_path = _write_config(tmp)
            config = load_config(str(config_path))

            asyncio.run(self._drive(tmp, config, config_path))

    async def _drive(self, tmp: Path, config, config_path: Path) -> None:
        ledger = make_ledger(_ledger_mapping_for(config, config.runtime))
        await ledger.start()
        bus_backend = make_bus_backend(_bus_config_for(config, config.runtime))
        await bus_backend.start()

        # Self-authenticated, exactly like `ContextFactory.build` does for
        # every real subsystem process -- see `kernel.context`'s docstring
        # addition for why this is required in any mode but `single`.
        identities = IdentityRegistry(b"integration-test-secret", "run-parent")
        policy = ReservedTopologyPolicy(identities)

        def client(source: str):
            name, _, instance = source.partition("@")
            policy.authenticate(source, identities.issue(name, instance))
            return make_bus_client(bus_backend, source=source, ledger=ledger, clock=time.time, policy=policy)

        planning = _Planning(client("planning"))
        planning.add_task("t1", kind="chat", mode="execute", description="hi")
        cognition = _Cognition(client("cognition"))
        gx = _GuardianExecution(client("guardian"))
        # `_GuardianExecution` subscribes as "guardian" but its own reply
        # (the real Guardian/Execution split) carries `source="execution"`
        # -- `check_publish` authenticates whatever `message.source` says,
        # not the subscribing client's own bound source, so "execution"
        # needs its own token too even though no client object is ever
        # built with that exact bound source.
        client("execution")
        await planning.start()
        await cognition.start()
        await gx.start()

        # Pre-register the durable "workers" group (bus/backends/sqlite.py
        # section 5.4 / test_sqlite_multiprocess.py's own precedent):
        # without a subscription row already on file, `task.available`
        # published before any worker process exists fans out to nobody
        # and is lost, durable group or not.
        placeholder = client("planning")
        await placeholder.subscribe(topics.TASK_AVAILABLE, lambda m: asyncio.sleep(3600),
                                    group="workers", durable=True, max_inflight=0)
        await placeholder.publish(Message.new(
            topics.TASK_AVAILABLE, source="planning",
            payload={"task_id": "t1", "kind": "chat", "lease_seconds": 60.0},
            partition_key="task:t1", clock=time.time,
        ))

        ctx = mp.get_context("spawn")
        worker1 = ctx.Process(target=_run_worker, args=(str(config_path), "w1"))
        worker1.start()
        try:
            await self._wait_for_step_count(ledger, at_least=1, timeout=CLAIM_TIMEOUT_S)
        finally:
            worker1.kill()  # SIGKILL -- an actual crash, no cooperation, no cleanup
            worker1.join(timeout=10)

        steps_before_worker2 = await self._task_steps(ledger)
        self.assertEqual(len(steps_before_worker2), 1)
        self.assertEqual(steps_before_worker2[0].payload.get("tool"), "read_file")

        worker2 = ctx.Process(target=_run_worker, args=(str(config_path), "w2"))
        worker2.start()
        try:
            completed = await self._wait_for_completion(ledger, timeout=CLAIM_TIMEOUT_S)
        finally:
            worker2.terminate()  # SIGTERM -- the graceful path _cmd_worker's signal handler takes
            worker2.join(timeout=10)

        self.assertIsNotNone(completed, "task:t1 never reached task.completed")
        self.assertEqual(completed.payload.get("result_summary"), "done")

        # The crash-recovery half of the proof: worker 2 restored from
        # step 1 (`restore_step_count`) and never re-ran the tool call --
        # Guardian/Execution saw exactly one `action.proposed`, and the
        # trajectory holds exactly one `read_file` step, not two.
        self.assertEqual(len(gx.proposals), 1)
        self.assertEqual(gx.proposals[0].payload["tool"], "read_file")
        final_steps = [e for e in await self._task_steps(ledger) if e.payload.get("tool") == "read_file"]
        self.assertEqual(len(final_steps), 1)

        await planning.stop()
        await cognition.stop()
        await gx.stop()
        await bus_backend.stop()
        await ledger.stop()

    @staticmethod
    async def _task_steps(ledger) -> list:
        events = await ledger.read("task:t1")
        return [e for e in events if e.type == topics.TASK_STEP]

    async def _wait_for_step_count(self, ledger, *, at_least: int, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(await self._task_steps(ledger)) >= at_least:
                return
            await asyncio.sleep(POLL_S)
        self.fail(f"task:t1 never reached {at_least} recorded step(s) within {timeout}s")

    async def _wait_for_completion(self, ledger, *, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            events = await ledger.read("task:t1")
            for e in events:
                if e.type == topics.TASK_COMPLETED:
                    return e
            await asyncio.sleep(POLL_S)
        return None


if __name__ == "__main__":
    unittest.main()
