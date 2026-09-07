"""Self Model completeness, end to end through a real Kernel running
real World Model (docs/blueprint/subsystems/06-worldmodel.md sections 4
and 5, Phase 4 roadmap item 6: "competence per task type, calibration,
limitations, open questions; `SELF.md` projection in the data dir").

Before this fork, `simorgh/worldmodel/selfmodel.py`'s own docstring
said it plainly: every section but identity was "an honest, clearly-
marked-empty placeholder, because their real producers (Learning,
Reflection, Planning) don't exist yet." Those producers exist now
(`simorgh/learning/competence.py`, `simorgh/reflection/calibration.py`
`.patterns.py`, `.critique.py`) but `Service.consumes` never listened to
any of `learn.competence.updated`, `reflect.calibration.updated`,
`self.observation`, `learn.self_patch.applied/reverted`, or
`learn.skill.acquired` -- this test proves each of those now actually
lands in the live `SelfModel` and gets re-rendered to the real
`SELF.md` file on disk, not just held in an untested in-memory
structure. `open_questions` remains an honest, documented placeholder
(no producer publishes a wire event carrying one yet -- see
`selfmodel.py`'s docstring for the one-line contract addition that
would close it) and is asserted as such here too.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING
from simorgh.worldmodel.config import Config as WorldConfig
from simorgh.worldmodel.service import Service as WorldModelService


def _patched_build_factories(world_config: WorldConfig):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False, execution_config=None):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories = {name: factories[name] for name in ("bus", "ledger")}
        factories["worldmodel"] = lambda: WorldModelService(world_config)
        return factories

    return _build


async def _pump(n: int = 20) -> None:
    for _ in range(n):
        await asyncio.sleep(0)


class _Collector:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    async def __call__(self, message: Message) -> None:
        self.messages.append(message)


class TestSelfModelCompleteness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        self.kernel = Kernel(config, secrets=EnvSecretStore({}))
        patch = mock.patch(
            "simorgh.kernel.service.build_factories",
            new=_patched_build_factories(WorldConfig()),
        )
        patch.start()
        self.addCleanup(patch.stop)
        await self.kernel.boot()
        self.assertEqual(self.kernel.state.state, RUNNING)
        self.assertEqual(self.kernel._supervisor.services["worldmodel"].status, "ok")  # noqa: SLF001
        self.addAsyncCleanup(self.kernel.shutdown)
        self.bus = self.kernel.bus

    def _self_md(self) -> str:
        # Context.data_dir is `<runtime.data_dir>/<subsystem name>`
        # (kernel/context.py) -- for this Kernel that's `<tmp>/worldmodel`.
        from pathlib import Path
        return (Path(self._tmp.name) / "worldmodel" / "self" / "SELF.md").read_text()

    async def test_competence_and_calibration_reach_self_summary_and_self_md(self) -> None:
        updated = _Collector()
        await self.bus.subscribe(topics.SELF_MODEL_UPDATED, updated)

        await self.bus.publish(Message.new(
            topics.LEARN_COMPETENCE_UPDATED, source="learning",
            payload={"task_type": "patch", "success_rate": 0.71, "calibration": 0.8, "samples": 58},
        ))
        await self.bus.publish(Message.new(
            topics.REFLECT_CALIBRATION_UPDATED, source="reflection",
            payload={"task_type": "patch", "stated_confidence": 0.9, "empirical_accuracy": 0.71},
        ))
        await _pump(20)

        self.assertGreaterEqual(len(updated.messages), 2)
        self.assertIn("competence", updated.messages[0].payload["changed_sections"])

        summary = await self.bus.request(Message.new(
            topics.SELF_SUMMARY, source="tester", payload={"budget_tokens": 2000},
        ))
        self.assertIn("patch", summary.payload["text"])
        self.assertIn("71%", summary.payload["text"])

        md = self._self_md()
        self.assertIn("patch", md)
        self.assertIn("71%", md)
        self.assertIn("overconfident", md)  # stated 90% vs empirical 71% is > 0.1 apart

    async def test_pattern_mined_limitation_reaches_self_md_and_is_deduped_on_repeat(self) -> None:
        await self.bus.publish(Message.new(
            topics.SELF_OBSERVATION, source="reflection",
            payload={"kind": "limitation", "detail": "patch tasks touching retry.py fail often"},
        ))
        await _pump(10)
        md_first = self._self_md()
        self.assertIn("patch tasks touching retry.py fail often", md_first)

        gaps = await self.bus.request(Message.new(topics.SELF_GAPS, source="tester", payload={"k": 5}))
        self.assertEqual(gaps.payload["gaps"], [])  # honestly still empty -- not this item's scope

        # A near-identical re-mine of the same pattern must not duplicate
        # the entry (06-worldmodel.md section 5: "difflib >= 0.6 -- never
        # duplicate").
        await self.bus.publish(Message.new(
            topics.SELF_OBSERVATION, source="reflection",
            payload={"kind": "limitation", "detail": "patch tasks touching retry.py fail often lately"},
        ))
        await _pump(10)
        md_second = self._self_md()
        self.assertEqual(md_second.count("fail often"), 1)

    async def test_self_patch_applied_reaches_change_history_and_mitigates_a_matching_limitation(self) -> None:
        await self.bus.publish(Message.new(
            topics.SELF_OBSERVATION, source="reflection",
            payload={"kind": "limitation", "detail": "src/orchestrator/retry.py has flaky retries under load"},
        ))
        await _pump(10)
        self.assertIn("open", self._self_md())

        await self.bus.publish(Message.new(
            topics.LEARN_SELF_PATCH_APPLIED, source="learning",
            payload={"subject": "src/orchestrator/retry.py", "commit": "abc1234",
                     "tests": {"baseline": 820, "patched": 820}, "reason": "added jitter to the retry loop"},
        ))
        await _pump(10)

        md = self._self_md()
        self.assertIn("self_patch", md)
        self.assertIn("abc1234", md)
        self.assertIn("mitigated", md)  # the limitation naming this exact subject flipped status

    async def test_skill_acquired_reaches_capabilities_and_change_history(self) -> None:
        await self.bus.publish(Message.new(
            topics.LEARN_SKILL_ACQUIRED, source="learning",
            payload={"name": "github_skill", "path": "src/agents/skills/github_skill.py", "tests": 4},
        ))
        await _pump(10)
        md = self._self_md()
        self.assertIn("skill_acquired", md)
        self.assertIn("github_skill", md)

    async def test_open_questions_remains_an_honest_empty_placeholder(self) -> None:
        # No producer in this build publishes a wire event carrying a
        # critique's open_questions (see selfmodel.py's docstring for
        # exactly what contract addition would close this) -- SELF.md
        # must say so honestly rather than fabricate one.
        md = self._self_md()
        self.assertIn("(none)", md)

    async def test_no_sibling_events_at_all_still_produces_a_real_self_md(self) -> None:
        # Graceful degradation: World Model must never hang or crash
        # waiting on Learning/Reflection events that never arrive.
        md = self._self_md()
        self.assertIn("Simorgh", md)
        health = await self.kernel._supervisor.services["worldmodel"].service.health()  # noqa: SLF001
        self.assertEqual(health.status, "ok")


if __name__ == "__main__":
    unittest.main()
