"""Learning subsystem acceptance (docs/blueprint/subsystems/11-learning.md):
the real `simorgh.learning.Service`, registered as a real Kernel `Service`
via the same `mock.patch("simorgh.kernel.service.build_factories", ...)`
seam as `test_kernel_boot_two_toy_subsystems.py`, driven end to end through
`learn.pipeline.run` with a toy Guardian (approves/denies `action.proposed`
directly with real `action.result`/`action.denied` shapes) and a toy
Verification (answers `verify.requested` with a scripted `verify.result`).
Learning never touches files -- every effect it drives is still just
`action.proposed`, observed here at the bus boundary."""

import asyncio
import tempfile
import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.protocols import Health
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING
from simorgh.learning.config import Config as LearningConfig
from simorgh.learning.service import Service as LearningService


class _ToyGuardian:
    """Answers every `action.proposed` per a scripted queue of outcomes,
    one popped per `tool` invocation (draft, apply, commit, activate,
    revert) -- real `action.result`/`action.denied` shapes, published
    as `guardian` (the only publisher `ActionDenied` and the subscriber
    restriction on `ActionProposed` allow)."""

    name = "guardian"
    version = "0.0.1-toy"
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __init__(self, script: list[dict]) -> None:
        self._script = list(script)
        self.seen: list[dict] = []

    async def start(self, ctx) -> None:
        self.ctx = ctx
        self._sub = await ctx.bus.subscribe(topics.ACTION_PROPOSED, self._on_proposed)

    async def _on_proposed(self, message: Message) -> None:
        p = message.payload
        self.seen.append(p)
        outcome = self._script.pop(0) if self._script else {"ok": True}
        if outcome.get("denied"):
            await self.ctx.bus.publish(Message.new(
                topics.ACTION_DENIED, source=self.ctx.source,
                payload={"action_id": p["action_id"], "reasons": outcome.get("reasons", ["denied"]),
                          "layer": outcome.get("layer", "policy")},
                clock=self.ctx.clock.now,
            ))
            return
        result = {
            "action_id": p["action_id"], "ok": outcome.get("ok", True),
            "output_ref": outcome.get("output_ref", "blob:x"),
            "stdout_preview": outcome.get("stdout_preview", ""),
            "duration_ms": 1, "side_effects": [],
        }
        if not result["ok"] and "error" in outcome:
            result["error"] = outcome["error"]
        await self.ctx.bus.publish(Message.new(
            topics.ACTION_RESULT, source=self.ctx.source, payload=result, clock=self.ctx.clock.now,
        ))

    async def stop(self) -> None:
        await self._sub.unsubscribe()

    async def health(self) -> Health:
        return Health.ok()


class _ToyVerification:
    """Answers every `verify.requested` with the next scripted `verdict`."""

    name = "verification"
    version = "0.0.1-toy"
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __init__(self, verdicts: list[dict]) -> None:
        self._verdicts = list(verdicts)
        self.seen: list[dict] = []

    async def start(self, ctx) -> None:
        self.ctx = ctx
        self._sub = await ctx.bus.subscribe(topics.VERIFY_REQUESTED, self._on_requested)

    async def _on_requested(self, message: Message) -> None:
        p = message.payload
        self.seen.append(p)
        verdict = dict(self._verdicts.pop(0)) if self._verdicts else {"verdict": "pass"}
        payload = {
            "verification_id": p["verification_id"], "task_id": p["task_id"],
            "verdict": verdict.get("verdict", "pass"), "checklist": [],
            "trajectory": {"steps": 1, "wasted": 0, "recovered_errors": 0},
            "mechanical": {},
        }
        if "feedback" in verdict:
            payload["feedback"] = verdict["feedback"]
        await self.ctx.bus.publish(Message.new(
            topics.VERIFY_RESULT, source=self.ctx.source, payload=payload, clock=self.ctx.clock.now,
        ))

    async def stop(self) -> None:
        await self._sub.unsubscribe()

    async def health(self) -> Health:
        return Health.ok()


def _patched_build_factories(*, guardian_script, verify_script, toys: dict, learning_config: LearningConfig | None = None):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client):
        factories = real(bus_client=bus_client, ledger_client=ledger_client)
        factories["guardian"] = lambda: toys.setdefault("guardian", _ToyGuardian(guardian_script))
        factories["verification"] = lambda: toys.setdefault("verification", _ToyVerification(verify_script))
        factories["learning"] = lambda: toys.setdefault("learning", LearningService(learning_config))
        return factories

    return _build


async def _wait_for(ctx, type_: str, *, predicate=None, timeout: float = 2.0) -> Message:
    fut: asyncio.Future = asyncio.get_event_loop().create_future()

    async def _capture(message: Message) -> None:
        if fut.done():
            return
        if predicate is None or predicate(message.payload):
            fut.set_result(message)

    sub = await ctx.bus.subscribe(type_, _capture)
    try:
        return await asyncio.wait_for(fut, timeout=timeout)
    finally:
        await sub.unsubscribe()


class TestLearningPipelineKernelBoot(unittest.IsolatedAsyncioTestCase):
    async def _boot(self, *, guardian_script, verify_script, learning_config=None):
        toys: dict = {}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        # A real wall clock, not FakeClock: some kernel-side housekeeping
        # loop calls `clock.sleep()` internally, and with a manual-advance
        # FakeClock that races ahead of this test's real-time `wait_for`
        # calls, tripping the pipeline's own wall-clock ceiling spuriously.
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patcher = mock.patch(
            "simorgh.kernel.service.build_factories",
            new=_patched_build_factories(guardian_script=guardian_script, verify_script=verify_script, toys=toys,
                                          learning_config=learning_config),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        await kernel.boot()
        self.addCleanup(lambda: asyncio.ensure_future(kernel.shutdown()))
        self.assertEqual(kernel.state.state, RUNNING)
        return kernel, toys

    async def test_approved_patch_applies_and_records_outcome_and_competence(self):
        kernel, toys = await self._boot(
            guardian_script=[{"ok": True}, {"ok": True}, {"ok": True, "stdout_preview": "abc123"}, {"ok": True}],
            verify_script=[{"verdict": "pass"}],
        )
        ctx = toys["learning"]._ctx  # noqa: SLF001 -- the only handle a test has on the real Context

        completed_fut = asyncio.ensure_future(
            _wait_for(ctx, topics.LEARN_PIPELINE_COMPLETED, predicate=lambda p: p.get("task_id") == "t1", timeout=5)
        )
        applied_fut = asyncio.ensure_future(_wait_for(ctx, topics.LEARN_SELF_PATCH_APPLIED, timeout=5))
        await asyncio.sleep(0)

        await ctx.bus.publish(Message.new(
            topics.LEARN_PIPELINE_RUN, source="orchestration@test",
            payload={"task_id": "t1", "kind": "patch", "description": "add recency weighting",
                      "subject": "src/memory/retrieval.py"},
            clock=ctx.clock.now,
        ))

        completed = await asyncio.wait_for(completed_fut, timeout=5)
        applied = await asyncio.wait_for(applied_fut, timeout=5)
        self.assertEqual(completed.payload["outcome"], "applied")
        self.assertEqual(applied.payload["subject"], "src/memory/retrieval.py")

        # Planning owns `task:<id>` for writing; stand in for it here so
        # the OutcomeRecorder's read-only lookup finds a real kind/subject.
        await ctx.ledger.append("task:t1", Event(
            stream="task:t1", type="created", ts=ctx.clock.now(), trace_id="t1", causation_id=None,
            payload={"kind": "patch", "subject": "src/memory/retrieval.py"},
        ))
        recorded_fut = asyncio.ensure_future(_wait_for(ctx, topics.LEARN_OUTCOME_RECORDED, timeout=5))
        updated_fut = asyncio.ensure_future(_wait_for(
            ctx, topics.LEARN_COMPETENCE_UPDATED, timeout=5,
            predicate=lambda p: p.get("task_type") == "patch:src/memory",
        ))
        await asyncio.sleep(0)  # let both subscriptions land before the publish that races them
        await ctx.bus.publish(Message.new(
            topics.TASK_COMPLETED, source="orchestration@test",
            payload={"task_id": "t1", "result_summary": "ok", "artifacts": [], "verification_ref": None},
            clock=ctx.clock.now,
        ))
        recorded = await asyncio.wait_for(recorded_fut, timeout=5)
        self.assertTrue(recorded.payload["succeeded"])
        updated = await asyncio.wait_for(updated_fut, timeout=5)
        self.assertEqual(updated.payload["samples"], 1)

    async def test_failing_verification_retries_once_with_feedback_then_rejects(self):
        kernel, toys = await self._boot(
            guardian_script=[{"ok": True}, {"ok": True}],
            verify_script=[
                {"verdict": "fail", "feedback": {"items": [{"what": "tests", "why": "broke existing tests",
                                                              "suggested_fix": "narrow the diff"}]}},
                {"verdict": "fail", "feedback": {"items": [{"what": "tests", "why": "still broke tests",
                                                              "suggested_fix": "narrow further"}]}},
            ],
            learning_config=LearningConfig(max_draft_attempts=2),
        )
        ctx = toys["learning"]._ctx  # noqa: SLF001
        completed_fut = asyncio.ensure_future(
            _wait_for(ctx, topics.LEARN_PIPELINE_COMPLETED, predicate=lambda p: p.get("task_id") == "t2", timeout=5)
        )
        await asyncio.sleep(0)
        await ctx.bus.publish(Message.new(
            topics.LEARN_PIPELINE_RUN, source="orchestration@test",
            payload={"task_id": "t2", "kind": "patch", "description": "tighten a regex",
                      "subject": "src/memory/retrieval.py"},
            clock=ctx.clock.now,
        ))
        completed = await asyncio.wait_for(completed_fut, timeout=5)

        self.assertEqual(completed.payload["outcome"], "rejected")
        draft_calls = [p for p in toys["guardian"].seen if p["tool"] == "self_patch.draft"]
        self.assertEqual(len(draft_calls), 2)
        # the 2nd draft is fed the *1st* verify's feedback (the 2nd verify's
        # feedback would only ever seed a 3rd draft, which the bound forbids)
        self.assertIn("broke existing tests", draft_calls[1]["args"]["prior_reasons"])


if __name__ == "__main__":
    unittest.main()
