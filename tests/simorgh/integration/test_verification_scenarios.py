"""Acceptance scenarios from docs/blueprint/subsystems/10-verification.md
section 8, over a real `BusClient` + `FakeLedger` (`tests/simorgh/bus/harness.py`)
with stand-in `cognition`/`guardian`/`execution` subsystems answering
`cognition.think` / `guardian.review` / `action.proposed`->`action.result`.

Deliberately does not go through the Kernel: `simorgh/kernel/registry.py`'s
own docstring asks concurrent subsystem-track forks to use direct
`Context` construction or `mock.patch` injection in their own tests
rather than editing `registry.py` (a shared file every other in-flight
subsystem fork also touches) -- see `test_bus_two_toy_subsystems.py` for
the same pattern.

- S1: a self-patch with a clean candidate passes all mechanical checks
  and a 4-item checklist answered YES.
- S2: a self-patch that drops the original's module docstring fails
  mechanically with retryable feedback -- the checklist is never reached.
- S5: a self-patch targeting a Guardian-protected path fails with
  non-retryable feedback -- Verification never overrides Guardian.
- S3: a checklist reviewer that narrates without ever stating YES/NO
  produces `insufficient_evidence`, never a `fail` (milestone-92).
"""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from simorgh.bus.client import BusClient
from simorgh.contracts import topics
from simorgh.contracts.protocols import Context

from tests.simorgh.bus.fakes import FakeLedger
from tests.simorgh.bus.harness import Harness
from tests.simorgh.helpers import FakeClock, make_message

from simorgh.verification.config import VerificationConfig
from simorgh.verification.service import VerificationService


def _ctx(bus: BusClient, h: Harness, name: str) -> Context:
    return Context(name=name, instance_id="", run_id="r1", mode="single", bus=bus, ledger=h.ledger,
                   config={}, secrets={}, clock=h.clock, logger=None, data_dir=Path("."))  # type: ignore[arg-type]


class _Cognition:
    """Answers `cognition.think`; `answer_for` maps a prompt-matching
    predicate to reply text, checked in order (first match wins)."""

    name, version = "cognition", "0"
    consumes = (topics.COGNITION_THINK,)
    produces = (topics.COGNITION_THINK_REPLY,)

    def __init__(self, answer_for: list[tuple]) -> None:
        self._answer_for = answer_for
        self.prompts: list[str] = []

    async def start(self, ctx: Context) -> None:
        self.bus = ctx.bus
        await self.bus.subscribe(topics.COGNITION_THINK, self._on_think)

    _BASE_REPLY = {"tool_calls": [], "provider": "fake", "cost_usd": 0.0, "tokens": 1}

    async def _on_think(self, m):
        prompt = m.payload["messages"][-1]["content"]
        self.prompts.append(prompt)
        for predicate, text in self._answer_for:
            if predicate(prompt):
                payload = {**self._BASE_REPLY, "text": text, "floor": False, "non_answer": False}
                await self.bus.reply(m, type=topics.COGNITION_THINK_REPLY, payload=payload)
                return
        payload = {**self._BASE_REPLY, "text": "", "floor": True, "non_answer": True}
        await self.bus.reply(m, type=topics.COGNITION_THINK_REPLY, payload=payload)

    async def stop(self) -> None:
        return None


class _Guardian:
    """Answers `guardian.review`; also routes `action.proposed` ->
    `action.result` (the reserved-topology role -- only `guardian` may
    subscribe to `action.proposed`) by delegating to `execution_reply`."""

    name, version = "guardian", "0"
    consumes = (topics.GUARDIAN_REVIEW, topics.ACTION_PROPOSED)
    produces = (topics.GUARDIAN_REVIEW_REPLY, topics.ACTION_RESULT)

    def __init__(self, review_reply: dict, execution_reply: dict) -> None:
        self._review_reply = review_reply
        self._execution_reply = execution_reply

    async def start(self, ctx: Context) -> None:
        self.bus = ctx.bus
        await self.bus.subscribe(topics.GUARDIAN_REVIEW, self._on_review)
        await self.bus.subscribe(topics.ACTION_PROPOSED, self._on_action)

    async def _on_review(self, m):
        await self.bus.reply(m, type=topics.GUARDIAN_REVIEW_REPLY, payload=self._review_reply)

    async def _on_action(self, m):
        payload = {
            "action_id": m.payload["action_id"], "ok": True, "output_ref": "", "stdout_preview": "",
            "duration_ms": 10, "side_effects": [], **self._execution_reply,
        }
        await self.bus.publish(self.bus.new(topics.ACTION_RESULT, payload, caused_by=m))

    async def stop(self) -> None:
        return None


async def _settle(seconds: float = 0.1) -> None:
    end = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < end:
        await asyncio.sleep(0.005)


class TestVerificationScenarios(unittest.IsolatedAsyncioTestCase):
    async def test_s1_self_patch_passes_with_full_checklist(self):
        candidate = '"""A clean, well-documented module."""\n\ndef add(a, b):\n    return a + b\n'
        payload = {
            "verification_id": "v-s1", "task_id": "t-s1", "kind": "self_patch",
            "subject_ref": "", "checklist_hint": None,
        }
        # subject is resolved via a Ledger blob in the real service; write it directly.
        subject = {
            "path": "simorgh/scratch/adder.py", "original": "", "candidate": candidate,
            "description": "add an addition helper", "result": "added add(a, b)", "reversibility": "reversible",
        }
        async with Harness("memory") as h:
            ref = await h.ledger.put_blob(__import__("json").dumps(subject).encode(), content_type="application/json")
            payload["subject_ref"] = ref

            service = VerificationService(VerificationConfig())
            cognition = _Cognition([
                (lambda p: "Write up to" in p, "1. [required] does it add two numbers?\n2. [required] is the function named add?\n"
                                                "3. [optional] is it documented?\n4. [required] does it avoid side effects?\n"),
                (lambda p: "Does the result satisfy this?" in p, "YES, confirmed by inspection."),
            ])
            guardian = _Guardian(
                review_reply={"approved": True, "reasons": [], "layers_run": ["static", "adaptive"]},
                execution_reply={"ok": True, "stdout_preview": "3 passed", "output_ref": "", "error": None,
                                  "metadata": {"baseline": 3, "patched": 3, "passed": True}},
            )
            await service.start(_ctx(h.client("verification"), h, "verification"))
            await cognition.start(_ctx(h.client("cognition"), h, "cognition"))
            await guardian.start(_ctx(h.client("guardian"), h, "guardian"))

            results: list = []
            await h.client("test-observer").subscribe(topics.VERIFY_RESULT, lambda m: results.append(m.payload))
            await h.client("orchestration").publish(make_message(topics.VERIFY_REQUESTED, source="orchestration", payload=payload))
            await _settle(0.3)
            try:
                self.assertEqual(len(results), 1)
                result = results[0]
                self.assertEqual(result["verdict"], "pass")
                self.assertEqual(len(result["checklist"]), 4)
                self.assertTrue(all(item["answer"] == "yes" for item in result["checklist"]))
            finally:
                await service.stop()

    async def test_s2_docstring_regression_is_retryable_fail_before_checklist(self):
        original = '"""' + ("This module explains its own rationale in real detail. " * 3) + '"""\n\ndef f():\n    return 1\n'
        candidate = "def f():\n    return 1\n"  # docstring dropped
        subject = {
            "path": "simorgh/scratch/f.py", "original": original, "candidate": candidate,
            "description": "tweak f", "result": "removed the docstring", "reversibility": "reversible",
        }
        async with Harness("memory") as h:
            ref = await h.ledger.put_blob(__import__("json").dumps(subject).encode(), content_type="application/json")
            payload = {"verification_id": "v-s2", "task_id": "t-s2", "kind": "self_patch", "subject_ref": ref}

            service = VerificationService(VerificationConfig())
            cognition = _Cognition([])  # must never be asked -- checklist is short-circuited
            guardian = _Guardian(review_reply={"approved": True, "reasons": [], "layers_run": []}, execution_reply={"ok": True})
            await service.start(_ctx(h.client("verification"), h, "verification"))
            await cognition.start(_ctx(h.client("cognition"), h, "cognition"))
            await guardian.start(_ctx(h.client("guardian"), h, "guardian"))

            results: list = []
            await h.client("test-observer").subscribe(topics.VERIFY_RESULT, lambda m: results.append(m.payload))
            await h.client("orchestration").publish(make_message(topics.VERIFY_REQUESTED, source="orchestration", payload=payload))
            await _settle(0.3)
            try:
                self.assertEqual(len(results), 1)
                result = results[0]
                self.assertEqual(result["verdict"], "fail")
                self.assertEqual(result["checklist"], [])  # never reached
                self.assertTrue(result["feedback"]["retryable"])
                self.assertTrue(any("docstring" in item["why"] for item in result["feedback"]["items"]))
                self.assertEqual(cognition.prompts, [])
            finally:
                await service.stop()

    async def test_s5_protected_target_is_non_retryable_fail(self):
        candidate = '"""fine."""\ndef f():\n    return 1\n'
        subject = {
            "path": "simorgh/scratch/protected.py", "candidate": candidate,
            "description": "touch a protected file", "result": "changed it", "reversibility": "irreversible",
        }
        async with Harness("memory") as h:
            ref = await h.ledger.put_blob(__import__("json").dumps(subject).encode(), content_type="application/json")
            payload = {"verification_id": "v-s5", "task_id": "t-s5", "kind": "self_patch", "subject_ref": ref}

            service = VerificationService(VerificationConfig())
            cognition = _Cognition([])
            guardian = _Guardian(
                review_reply={"approved": False, "reasons": ["path is on the protected list"], "layers_run": ["protected"]},
                execution_reply={"ok": True},
            )
            await service.start(_ctx(h.client("verification"), h, "verification"))
            await cognition.start(_ctx(h.client("cognition"), h, "cognition"))
            await guardian.start(_ctx(h.client("guardian"), h, "guardian"))

            results: list = []
            await h.client("test-observer").subscribe(topics.VERIFY_RESULT, lambda m: results.append(m.payload))
            await h.client("orchestration").publish(make_message(topics.VERIFY_REQUESTED, source="orchestration", payload=payload))
            await _settle(0.3)
            try:
                self.assertEqual(len(results), 1)
                result = results[0]
                self.assertEqual(result["verdict"], "fail")
                self.assertFalse(result["feedback"]["retryable"])
            finally:
                await service.stop()

    async def test_s3_reviewer_non_answer_is_insufficient_evidence_never_fail(self):
        subject = {
            "description": "summarize the research finding", "result": "wrote up the finding",
            "reversibility": "read_only",
        }
        async with Harness("memory") as h:
            ref = await h.ledger.put_blob(__import__("json").dumps(subject).encode(), content_type="application/json")
            payload = {"verification_id": "v-s3", "task_id": "t-s3", "kind": "task", "subject_ref": ref}

            service = VerificationService(VerificationConfig())
            cognition = _Cognition([
                (lambda p: "Write up to" in p, "1. [required] does the summary match the finding?\n"),
                (lambda p: "Does the result satisfy this?" in p, "I'll need to look at the original finding before I can judge this properly."),
            ])
            guardian = _Guardian(review_reply={"approved": True, "reasons": [], "layers_run": []}, execution_reply={"ok": True})
            await service.start(_ctx(h.client("verification"), h, "verification"))
            await cognition.start(_ctx(h.client("cognition"), h, "cognition"))
            await guardian.start(_ctx(h.client("guardian"), h, "guardian"))

            results: list = []
            await h.client("test-observer").subscribe(topics.VERIFY_RESULT, lambda m: results.append(m.payload))
            await h.client("orchestration").publish(make_message(topics.VERIFY_REQUESTED, source="orchestration", payload=payload))
            await _settle(0.3)
            try:
                self.assertEqual(len(results), 1)
                result = results[0]
                self.assertEqual(result["verdict"], "insufficient_evidence")
                self.assertNotIn("feedback", result)
            finally:
                await service.stop()

    async def test_duplicate_request_re_emits_recorded_verdict_without_rerunning(self):
        """section 8, "duplicate request": if a `verdict` already exists on
        `verify:<id>`, re-emit it -- proven here by a `cognition` fake whose
        call count must not grow on the second `verify.requested`."""
        subject = {"description": "summarize the finding", "result": "wrote it up", "reversibility": "reversible"}
        async with Harness("memory") as h:
            ref = await h.ledger.put_blob(__import__("json").dumps(subject).encode(), content_type="application/json")
            payload = {"verification_id": "v-dup", "task_id": "t-dup", "kind": "task", "subject_ref": ref}

            service = VerificationService(VerificationConfig())
            cognition = _Cognition([
                (lambda p: "Write up to" in p, "1. [required] does it match?\n"),
                (lambda p: "Does the result satisfy this?" in p, "YES, it matches."),
            ])
            guardian = _Guardian(review_reply={"approved": True, "reasons": [], "layers_run": []}, execution_reply={"ok": True})
            await service.start(_ctx(h.client("verification"), h, "verification"))
            await cognition.start(_ctx(h.client("cognition"), h, "cognition"))
            await guardian.start(_ctx(h.client("guardian"), h, "guardian"))

            results: list = []
            await h.client("test-observer").subscribe(topics.VERIFY_RESULT, lambda m: results.append(m.payload))
            requester = h.client("orchestration")
            try:
                await requester.publish(make_message(topics.VERIFY_REQUESTED, source="orchestration", payload=payload))
                await _settle(0.3)
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0]["verdict"], "pass")
                first_call_count = len(cognition.prompts)
                self.assertGreater(first_call_count, 0)

                await requester.publish(make_message(topics.VERIFY_REQUESTED, source="orchestration", payload=payload))
                await _settle(0.3)
                self.assertEqual(len(results), 2)
                self.assertEqual(results[1], results[0])  # the exact recorded verdict, replayed
                self.assertEqual(len(cognition.prompts), first_call_count)  # no re-run
            finally:
                await service.stop()


if __name__ == "__main__":
    unittest.main()
