"""Phase 4 roadmap item 4.7 acceptance: "skills discoverable by
description, loaded on demand" -- proven with REAL `simorgh.memory.
Service`, `simorgh.guardian.Service`, and `simorgh.execution.Service`,
booted through the real Kernel composition root
(`registry.build_factories` -> `ContextFactory` -> `Supervisor`), the
same `mock.patch("simorgh.kernel.service.build_factories", ...)` seam
`test_guardian_execution_action_path.py` and `test_learning_pipeline_
kernel_boot.py` use.

Learning's own `PatchPipeline` (kind="skill") is unit-tested against a
scripted harness in `tests/simorgh/learning/test_pipeline.py` -- it
can't usefully run against a REAL Guardian+Execution here, because the
`skill.draft` LLM-drafting tool it proposes first is a Cognition-backed
composite tool that is a pre-existing, out-of-scope gap (08-execution.md
section 12; `simorgh/execution/README.md`'s "Deliberate scope cuts"),
not something this build adds. So this test drives the two contract-level
events Learning's pipeline actually emits on a successful skill
acquisition (`memory.store{kind: procedural}`, `learn.skill.acquired`)
directly, exactly the way `test_guardian_execution_action_path.py`
drives `action.proposed` directly instead of going through Orchestration.

Four properties, matching the roadmap line word for word:
1. A procedural memory record with a real description is *discoverable*
   via `memory.retrieve{kinds:[procedural]}` (memory/store.py's already-
   generic retrieval, no new machinery).
2. `learn.skill.acquired` makes Execution load exactly that one skill as
   a `skill:<name>` tool and emit `tool.registered{provider: skill}`,
   never a directory scan of every skill ever acquired at boot -- and
   the registered tool's `description` is the same one Memory holds
   (discoverability feeding the load, not two disconnected facts).
3. That live, on-demand-loaded tool is genuinely invokable end to end: a
   real `action.proposed` for it is approved by a real Guardian and
   actually executed by a real Execution, inside the same sandboxed
   subprocess `run_python_sandboxed` uses.
4. A second skill, never announced via `learn.skill.acquired` in this
   process, still loads and runs the first time an approved action
   names it -- the lazy fallback in `Service._on_approved` -- proving
   "loaded on demand" doesn't depend on having observed the acquisition
   event this process's lifetime.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.service import Service as ExecutionService
from simorgh.guardian.config import Config as GuardianConfig
from simorgh.guardian.service import Service as GuardianService
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING

_GREET_SKILL = 'def run(name="world"):\n    return f"hello {name}"\n'
_FAREWELL_SKILL = 'def run(name="world"):\n    return f"farewell {name}"\n'


def _patched_build_factories(*, repo_root: Path):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories["guardian"] = lambda: GuardianService(config=GuardianConfig(mode="guarded"))
        factories["execution"] = lambda: ExecutionService(config=ExecutionConfig(repo_root=repo_root))
        return factories

    return _build


async def _wait_for(bus, type_: str, *, predicate=None, timeout: float = 5.0) -> Message | None:
    fut: asyncio.Future = asyncio.get_event_loop().create_future()

    async def _capture(message: Message) -> None:
        if not fut.done() and (predicate is None or predicate(message.payload)):
            fut.set_result(message)

    sub = await bus.subscribe(type_, _capture)
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    except asyncio.TimeoutError:
        return None
    finally:
        await sub.unsubscribe()


def _proposal(action_id: str, *, tool: str, args: dict, reversibility: str = "reversible") -> Message:
    return Message.new(
        topics.ACTION_PROPOSED, source="test",
        payload={"action_id": action_id, "tool": tool, "args": args,
                 "scope": {"network": False}, "reversibility": reversibility,
                 "rationale": "integration test", "proposed_by": "test"},
    )


class TestSkillAcquisitionProceduralMemory(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "simorgh_skills").mkdir()
        (self.root / "simorgh_skills" / "greet.py").write_text(_GREET_SKILL)
        (self.root / "simorgh_skills" / "farewell.py").write_text(_FAREWELL_SKILL)

        data_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(data_tmp.cleanup)
        config = LoadedConfig({"runtime": {"data_dir": data_tmp.name}}, None)
        self.kernel = Kernel(config, secrets=EnvSecretStore({}))
        patcher = mock.patch(
            "simorgh.kernel.service.build_factories", new=_patched_build_factories(repo_root=self.root),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        await self.kernel.boot()
        self.addAsyncCleanup(self.kernel.shutdown)
        self.assertEqual(self.kernel.state.state, RUNNING)
        self.bus = self.kernel.bus

    async def test_a_skill_becomes_discoverable_procedural_memory_and_an_on_demand_tool(self):
        # -- 1. Learning's own effect on a successful skill acquisition:
        # a procedural memory record with a real description --------------
        stored_fut = asyncio.ensure_future(_wait_for(self.bus, topics.MEMORY_STORED))
        await self.bus.publish(Message.new(
            topics.MEMORY_STORE, source="learning", payload={
                "kind": "procedural",
                "content": "Greets a person by name -- a friendly hello.",
                "tags": ["skill", "greet"], "source_ref": "simorgh_skills/greet.py",
            },
        ))
        self.assertIsNotNone(await asyncio.wait_for(stored_fut, timeout=5))

        # -- discoverable by description: a semantically-related query,
        # not the exact stored string, still finds it -----------------
        retrieved = await self.bus.request(Message.new(
            topics.MEMORY_RETRIEVE, source="test",
            payload={"query": "friendly hello greeting", "kinds": ["procedural"], "k": 5},
        ), timeout=5.0)
        self.assertEqual(len(retrieved.payload["items"]), 1)
        self.assertIn("Greets a person by name", retrieved.payload["items"][0]["content"])

        # -- 2. `learn.skill.acquired` makes Execution load exactly this
        # one skill on demand, never a boot-time directory scan --------
        registered_fut = asyncio.ensure_future(_wait_for(
            self.bus, topics.TOOL_REGISTERED, predicate=lambda p: p.get("name") == "skill:greet",
        ))
        await self.bus.publish(Message.new(
            topics.LEARN_SKILL_ACQUIRED, source="learning",
            payload={"name": "greet", "path": "simorgh_skills/greet.py", "tests": 1},
        ))
        registered = await asyncio.wait_for(registered_fut, timeout=5)
        self.assertEqual(registered.payload["provider"], "skill")
        # the same description Memory holds -- discovery feeding the load,
        # not two disconnected facts.
        self.assertIn("Greets a person by name", registered.payload["description"])

        # -- 3. that on-demand tool actually runs, through a real
        # Guardian approval and a real Execution dispatch --------------
        await self.bus.publish(_proposal("greet-1", tool="skill:greet", args={"name": "Simorgh"}))
        result = await _wait_for(self.bus, topics.ACTION_RESULT, predicate=lambda p: p.get("action_id") == "greet-1")
        self.assertIsNotNone(result, "no action.result for the on-demand skill tool")
        self.assertTrue(result.payload["ok"], result.payload)
        self.assertIn("hello Simorgh", result.payload["stdout_preview"])

        # -- 4. a second skill, never announced via `learn.skill.acquired`
        # in this process, still loads and runs the first time an
        # approved action names it (the lazy fallback in `_on_approved`) --
        await self.bus.publish(_proposal("farewell-1", tool="skill:farewell", args={"name": "Simorgh"}))
        farewell_result = await _wait_for(
            self.bus, topics.ACTION_RESULT, predicate=lambda p: p.get("action_id") == "farewell-1",
        )
        self.assertIsNotNone(farewell_result, "no action.result for the lazily-loaded skill tool")
        self.assertTrue(farewell_result.payload["ok"], farewell_result.payload)
        self.assertIn("farewell Simorgh", farewell_result.payload["stdout_preview"])


if __name__ == "__main__":
    unittest.main()
