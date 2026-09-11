"""End to end through the real Kernel: Guardian, Execution, Verification,
Orchestration and the Ledger are real; only Cognition and Planning are
scripted. A patch task on a NAMED temporary repository writes a file in
its own worktree, runs the tests, commits, is verified, and lands on
that repository's main -- which the live checkout never sees.

The repository is named (`[execution] repo_root`) on purpose: the
integration tests that boot a Kernel without naming one run against
the real checkout, and on 2026-09-11 the first version of this feature
put 45 stray task branches on it within one suite run. A worktree is
only ever made of a repository somebody named; the sibling test below
proves an unnamed one gets none.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Health
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING

_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
GREETING = "def greet(name):\n    return f'hello, {name}'\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *_ID, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _named_repo(root: Path) -> Path:
    repo = root / "repo"
    (repo / "simorgh").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "simorgh" / "__init__.py").write_text("")
    (repo / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


class _ScriptedCognition:
    """One patch session: write the file, run the whole suite, commit,
    answer. Verification's checklist and per-item review get a YES."""

    name = "cognition"
    version = "0.0.1-toy"
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._drafts = 0

    async def start(self, ctx) -> None:
        self.ctx = ctx
        self._sub = await ctx.bus.subscribe(topics.COGNITION_THINK, self._on_think)

    async def stop(self) -> None:
        await self._sub.unsubscribe()

    async def health(self) -> Health:
        return Health.ok()

    async def _on_think(self, message: Message) -> None:
        payload = message.payload
        prompt = payload["messages"][-1]["content"]
        base = {"tool_calls": [], "provider": "fake", "cost_usd": 0.0, "tokens": 5, "floor": False, "non_answer": False}
        if payload.get("purpose") in ("draft", "chat"):
            self._drafts += 1
            script = [
                {"text": "APPLY_SOURCE_PATCH: simorgh/greeting.py",
                 "tool_calls": [{"tool": "apply_source_patch", "args": {"subject": "simorgh/greeting.py", "code": GREETING}}]},
                {"text": "RUN_TESTS: tests", "tool_calls": [{"tool": "run_tests", "args": {"target": "tests"}}]},
                {"text": "GIT_COMMIT: simorgh/greeting.py",
                 "tool_calls": [{"tool": "git_commit", "args": {"path": "simorgh/greeting.py", "message": "add greet"}}]},
                {"text": "Added simorgh/greeting.py with greet(name), ran the suite, and committed it."},
            ]
            step = script[min(self._drafts - 1, len(script) - 1)]
            reply = {**base, **step}
        elif "Write up to" in prompt:
            reply = {**base, "text": "1. [required] does simorgh/greeting.py define greet?"}
        else:
            reply = {**base, "text": "YES\nthe file defines greet."}
        await self.ctx.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload=reply)


class _ToyPlanning:
    name = "planning"
    version = "0.0.1-toy"
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __init__(self, tasks: dict[str, dict]) -> None:
        self._tasks = tasks

    async def start(self, ctx) -> None:
        self.ctx = ctx
        self._sub = await ctx.bus.subscribe(topics.TASK_CLAIM, self._on_claim)

    async def _on_claim(self, message: Message) -> None:
        task = self._tasks.get(message.payload["task_id"])
        await self.ctx.bus.reply(message, type=topics.TASK_CLAIM_REPLY,
                                 payload={"granted": task is not None, "task": task or {}})

    async def stop(self) -> None:
        await self._sub.unsubscribe()

    async def health(self) -> Health:
        return Health.ok()


def _patched_build_factories(*, tasks: dict, toys: dict):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None, guardian_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl,
                         execution_config=execution_config, guardian_config=guardian_config)
        factories["cognition"] = lambda: toys.setdefault("cognition", _ScriptedCognition())
        factories["planning"] = lambda: toys.setdefault("planning", _ToyPlanning(tasks))
        return factories

    return _build


async def _wait_for(ctx, types: tuple[str, ...], *, task_id: str, timeout: float) -> Message:
    fut: asyncio.Future = asyncio.get_event_loop().create_future()

    async def _capture(message: Message) -> None:
        if not fut.done() and message.payload.get("task_id") == task_id:
            fut.set_result(message)

    subs = [await ctx.bus.subscribe(t, _capture) for t in types]
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    finally:
        for sub in subs:
            await sub.unsubscribe()


class TestAPatchLandsThroughAWorktree(unittest.IsolatedAsyncioTestCase):
    async def _boot(self, *, name_the_repo: bool):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        repo = _named_repo(root)
        task = {"t-land": {"description": "add simorgh/greeting.py with greet(name)", "mode": "execute",
                           "kind": "patch", "subject": "simorgh/greeting.py"}}
        toys: dict = {}
        execution = {"repo_root": str(repo), "test_timeout_s": 120.0} if name_the_repo else {}
        config = LoadedConfig({"runtime": {"data_dir": str(root / "data")}, "execution": execution,
                               "guardian": {"irreversible_requires_human": False},
                               "curiosity": {"autonomy_on_boot": False}}, None)
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patcher = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories(tasks=task, toys=toys))
        patcher.start()
        self.addCleanup(patcher.stop)
        await kernel.boot()
        self.assertEqual(kernel.state.state, RUNNING)
        return kernel, toys["planning"].ctx, repo, root

    async def test_the_change_lands_on_the_named_repository(self):
        kernel, ctx, repo, root = await self._boot(name_the_repo=True)
        try:
            before = _git(repo, "rev-parse", "HEAD")
            done = asyncio.ensure_future(_wait_for(
                ctx, (topics.TASK_COMPLETED, topics.TASK_BLOCKED, topics.TASK_FAILED), task_id="t-land", timeout=240))
            await asyncio.sleep(0)
            await ctx.bus.publish(Message.new(
                topics.TASK_AVAILABLE, source="test",
                payload={"task_id": "t-land", "kind": "patch", "lease_seconds": 300.0}, clock=ctx.clock.now))
            outcome = await done
            self.assertEqual(outcome.type, topics.TASK_COMPLETED, outcome.payload)
            self.assertIn("[landed 1 commit(s) on main", outcome.payload["result_summary"])

            after = _git(repo, "rev-parse", "HEAD")
            self.assertNotEqual(after, before)
            self.assertEqual(_git(repo, "rev-list", "--count", f"{before}..{after}"), "1")
            self.assertEqual((repo / "simorgh" / "greeting.py").read_text(), GREETING)
            self.assertEqual(_git(repo, "status", "--porcelain"), "")
            self.assertEqual(_git(repo, "branch", "--list", "sim/task-*"), "")
            self.assertEqual(list((root / "data" / "execution" / "worktrees").glob("*")), [])

            steps = [e.payload for e in await ctx.ledger.read("task:t-land") if e.type == topics.TASK_STEP]
            tools = [s.get("tool") for s in steps]
            self.assertEqual(tools[0], "worktree_open")
            self.assertIn("worktree_land", tools)
            self.assertTrue(all(s.get("ok") for s in steps if s.get("tool") in ("worktree_open", "worktree_land")), steps)
        finally:
            await kernel.shutdown()

    async def test_an_unnamed_repository_is_never_branched(self):
        """The Kernel booted from this checkout with no repository named:
        the task edits nothing here, and no branch appears on the live
        repository -- the failure this test exists to keep away."""
        kernel, ctx, repo, root = await self._boot(name_the_repo=False)
        try:
            live = Path(__file__).resolve().parents[3]
            stray_before = _git(live, "branch", "--list", "sim/task-*")
            done = asyncio.ensure_future(_wait_for(
                ctx, (topics.TASK_COMPLETED, topics.TASK_BLOCKED, topics.TASK_FAILED), task_id="t-land", timeout=120))
            await asyncio.sleep(0)
            # A scripted session that would commit a real file into the
            # live checkout is not something a test may run; the first
            # think here is enough to see whether a worktree was asked
            # for, so the task is cancelled right after it starts.
            started = asyncio.ensure_future(_wait_for(ctx, (topics.TASK_STARTED,), task_id="t-land", timeout=30))
            await asyncio.sleep(0)
            await ctx.bus.publish(Message.new(
                topics.TASK_AVAILABLE, source="test",
                payload={"task_id": "t-land", "kind": "patch", "lease_seconds": 300.0}, clock=ctx.clock.now))
            await started
            await ctx.bus.publish(Message.new(
                topics.TASK_CANCEL, source="test", payload={"task_id": "t-land", "reason": "test"},
                clock=ctx.clock.now))
            outcome = await done
            self.assertNotEqual(outcome.type, topics.TASK_COMPLETED)
            steps = [e.payload for e in await ctx.ledger.read("task:t-land") if e.type == topics.TASK_STEP]
            self.assertNotIn("worktree_open", [s.get("tool") for s in steps])
            self.assertEqual(_git(live, "branch", "--list", "sim/task-*"), stray_before)
            self.assertFalse((root / "data" / "execution" / "worktrees").exists())
        finally:
            await kernel.shutdown()


if __name__ == "__main__":
    unittest.main()
