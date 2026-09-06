"""Evaluator-optimizer loop over a real Kernel boot -- closes harness-06
gap #5 by name: "Verification is single-pass outcome-only, not iterative
or trajectory-aware" (docs/blueprint/subsystems/10-verification.md
section 1; docs/blueprint/04-build-plan-and-roadmap.md Phase 4 item 3).

`simorgh/orchestration/session.py`'s `SessionRunner._verify_then_finish`
already implements the bounded revise-with-feedback loop (claim -> think
-> verify.requested -> verify.result -> revise -> re-think ->
re-verify, up to `session.profile.max_revisions`) and it is already
covered end to end by `tests/simorgh/orchestration/test_session_flows.py`
-- but only against `FakeVerification`, a test double that just echoes a
scripted verdict per request and does not reproduce the real
`simorgh.verification.VerificationService`'s behavior. Reading the real
service against the real orchestration code turned up two bugs that the
fakes-based tests could not see, both fixed alongside this test:

1. `_verify_then_finish` minted ONE `verification_id` before its
   `while True:` loop and reused it for every revision inside the same
   attempt. The real service's duplicate-request rule (10 section 8:
   "if a `verdict` already exists on `verify:<id>`, re-emit it" -- meant
   for at-least-once bus redelivery of the *same* request) would treat
   the second `verify.requested` for a revision as a redelivery of the
   first and simply replay the FIRST (failing) verdict without ever
   re-running the checks against the revised text. The loop would look
   like it was iterating (`revisions_used` increments, a real THINK call
   happens) but verification itself would never actually see the fix --
   it would keep "failing" the same cached verdict until
   `max_revisions`, then wrongly `task.blocked`. Fixed: a fresh
   `verification_id` per attempt (matching the sibling implementation in
   `simorgh/learning/pipeline.py`'s `PatchPipeline._verify_once`, which
   already did this correctly).
2. `subject_ref` was sent as raw, truncated session text. The real
   service's `_resolve_subject` treats `subject_ref` as a Ledger blob id
   (`ledger.get_blob(subject_ref)`) holding a JSON object with
   `description`/`result` keys -- the shape every other producer already
   sends (`learning/pipeline.py`'s `candidate_ref`, and every scenario in
   `tests/simorgh/integration/test_verification_scenarios.py`). Raw text
   there is not a valid blob id, so it silently resolved to `subject={}`
   and the semantic checklist review ran against an empty description
   and an empty result -- the evaluator-optimizer's actual feedback
   signal was gone. Fixed: `_put_verify_subject` blobs
   `{description, result}` before every `verify.requested`.

This test boots a real Kernel (the `mock.patch(
"simorgh.kernel.service.build_factories", ...)` seam from
`test_kernel_boot_two_toy_subsystems.py` / `test_learning_pipeline_
kernel_boot.py`) with the REAL `orchestration` and `verification`
Services -- only `cognition` (no real provider in this sandbox) and
`planning` (out of this fork's scope; a trivial claim-granting stand-in)
are toys. It drives one `patch`-kind task through a first draft that
fails the checklist, one feedback-driven revision, and a second draft
that passes -- and asserts the SECOND verification genuinely re-ran
against the REVISED text (proving fix #2) on a DISTINCT verification id
whose own `verify:<id>` Ledger stream holds a `pass` verdict while the
first id's stream still holds `fail` (proving fix #1: neither replayed
the other). It also asserts `verify.result.trajectory.steps > 0`,
because a request with `kind="task"` resolves to `Rigor.STANDARD` (10
section 5.2 default), which computes real trajectory metrics from the
Ledger's `task:<id>` stream -- the "trajectory-aware" half of gap #5.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Health
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING

DRAFT_1 = "VALUE = 1\n"  # no docstring -- fails the checklist item
DRAFT_2 = '"""Restored docstring."""\nVALUE = 1\n'  # revised after feedback -- passes


class _ScriptedCognition:
    """Answers `cognition.think` for BOTH callers that need it in this
    scenario: Orchestration's own draft/redraft (`purpose="draft"`) and
    Verification's checklist generation + per-item review
    (`purpose="review"`, distinguished by the two verification prompt
    templates in `simorgh/verification/checklist.py`). The per-item
    answer is decided from the ACTUAL `result` text embedded in the
    prompt -- this is what proves the revised draft's content, not a
    cached verdict, reached the second verification.
    """

    name = "cognition"
    version = "0.0.1-toy"
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    def __init__(self) -> None:
        self.think_calls: list[dict] = []
        self._draft_calls = 0

    async def start(self, ctx) -> None:
        self.ctx = ctx
        self._sub = await ctx.bus.subscribe(topics.COGNITION_THINK, self._on_think)

    async def stop(self) -> None:
        await self._sub.unsubscribe()

    async def health(self) -> Health:
        return Health.ok()

    async def _on_think(self, message: Message) -> None:
        payload = message.payload
        self.think_calls.append(payload)
        purpose = payload.get("purpose")
        prompt = payload["messages"][-1]["content"]
        base = {"tool_calls": [], "provider": "fake", "cost_usd": 0.0, "tokens": 5, "floor": False, "non_answer": False}

        if purpose in ("draft", "chat"):
            self._draft_calls += 1
            text = DRAFT_1 if self._draft_calls == 1 else DRAFT_2
            reply_payload = {**base, "text": text}
        elif "Write up to" in prompt:  # checklist generation (checklist.py's _CHECKLIST_PROMPT)
            reply_payload = {**base, "text": "1. [required] does the result preserve the module docstring?"}
        else:  # per-item YES/NO evaluation (checklist.py's _ANSWER_PROMPT)
            answer = "YES" if "Restored docstring" in prompt else "NO"
            reply_payload = {**base, "text": f"{answer}\nchecked the reported result text."}

        await self.ctx.bus.reply(message, type=topics.COGNITION_THINK_REPLY, payload=reply_payload)


class _ToyPlanning:
    """Grants `task.claim` for tasks it was told about, mirroring
    `tests/simorgh/orchestration/fakes.py`'s `FakePlanning` -- Planning
    itself is a different fork's scope this session; this is a
    request/reply stand-in only, not a reimplementation of anything
    Planning owns.
    """

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
        await self.ctx.bus.reply(
            message, type=topics.TASK_CLAIM_REPLY, payload={"granted": task is not None, "task": task or {}},
        )

    async def stop(self) -> None:
        await self._sub.unsubscribe()

    async def health(self) -> Health:
        return Health.ok()


def _patched_build_factories(*, tasks: dict, toys: dict):
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories["cognition"] = lambda: toys.setdefault("cognition", _ScriptedCognition())
        factories["planning"] = lambda: toys.setdefault("planning", _ToyPlanning(tasks))
        return factories

    return _build


async def _wait_for(ctx, type_: str, *, predicate=None, timeout: float = 5.0) -> Message:
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


class TestEvaluatorOptimizerAgainstRealVerification(unittest.IsolatedAsyncioTestCase):
    async def test_second_revision_re_verifies_the_revised_text_not_a_cached_verdict(self):
        tasks = {"t-eo1": {"description": "restore the accidentally-dropped module docstring", "mode": "execute"}}
        toys: dict = {}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        config = LoadedConfig({"runtime": {"data_dir": tmp.name}}, None)
        # A real wall clock (not a manual-advance fake): SessionRunner and
        # VerificationService both use real asyncio.wait_for timeouts.
        kernel = Kernel(config, secrets=EnvSecretStore({}))
        patcher = mock.patch(
            "simorgh.kernel.service.build_factories",
            new=_patched_build_factories(tasks=tasks, toys=toys),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        await kernel.boot()
        self.addCleanup(lambda: asyncio.ensure_future(kernel.shutdown()))
        self.assertEqual(kernel.state.state, RUNNING)

        ctx = toys["planning"].ctx

        verify_requests: list[dict] = []
        verify_results: list[dict] = []
        req_sub = await ctx.bus.subscribe(topics.VERIFY_REQUESTED, lambda m: verify_requests.append(m.payload))
        res_sub = await ctx.bus.subscribe(topics.VERIFY_RESULT, lambda m: verify_results.append(m.payload))
        self.addCleanup(lambda: asyncio.ensure_future(req_sub.unsubscribe()))
        self.addCleanup(lambda: asyncio.ensure_future(res_sub.unsubscribe()))

        completed_fut = asyncio.ensure_future(
            _wait_for(ctx, topics.TASK_COMPLETED, predicate=lambda p: p.get("task_id") == "t-eo1", timeout=10)
        )
        await asyncio.sleep(0)

        await ctx.bus.publish(Message.new(
            topics.TASK_AVAILABLE, source="test",
            payload={"task_id": "t-eo1", "kind": "patch", "lease_seconds": 60.0},
            clock=ctx.clock.now,
        ))

        completed = await asyncio.wait_for(completed_fut, timeout=10)

        # -- the loop actually completed by revising, not by blocking -----
        self.assertEqual(completed.payload["result_summary"], DRAFT_2)
        self.assertIsNotNone(completed.payload["verification_ref"])

        # -- two DISTINCT verifications ran, not one replayed -------------
        self.assertEqual(len(verify_requests), 2, f"expected 2 verify.requested, got {verify_requests}")
        self.assertEqual(len(verify_results), 2, f"expected 2 verify.result, got {verify_results}")
        id1, id2 = verify_requests[0]["verification_id"], verify_requests[1]["verification_id"]
        self.assertNotEqual(id1, id2, "each revision must mint a fresh verification_id (10 section 8's "
                                       "duplicate-request rule would otherwise replay the first verdict)")

        # -- subject_ref carried real content, not raw/truncated text -----
        for req in verify_requests:
            self.assertNotIn(DRAFT_1, req["subject_ref"])
            self.assertNotIn(DRAFT_2, req["subject_ref"])  # a blob id, never the draft text itself

        subject1 = json.loads(await ctx.ledger.get_blob(verify_requests[0]["subject_ref"]))
        subject2 = json.loads(await ctx.ledger.get_blob(verify_requests[1]["subject_ref"]))
        self.assertEqual(subject1["result"], DRAFT_1)
        self.assertEqual(subject2["result"], DRAFT_2)
        self.assertEqual(subject1["description"], tasks["t-eo1"]["description"])

        # -- the FIRST verdict genuinely failed, the SECOND genuinely passed
        self.assertEqual(verify_results[0]["verdict"], "fail")
        self.assertEqual(verify_results[1]["verdict"], "pass")
        self.assertEqual(verify_results[1]["verification_id"], completed.payload["verification_ref"])

        # -- each id's own Ledger stream is independent (not a shared replay)
        stream1 = await ctx.ledger.read(f"verify:{id1}")
        stream2 = await ctx.ledger.read(f"verify:{id2}")
        verdict1 = next(e for e in reversed(stream1) if e.type == "verdict")
        verdict2 = next(e for e in reversed(stream2) if e.type == "verdict")
        self.assertEqual(verdict1.payload["verdict"], "fail")
        self.assertEqual(verdict2.payload["verdict"], "pass")

        # -- trajectory-aware: kind="task" resolves to STANDARD rigor (10
        # section 5.2), which computes real Ledger-derived trajectory
        # metrics rather than skipping them -- the other half of gap #5.
        self.assertGreater(verify_results[0]["trajectory"]["steps"], 0)
        self.assertGreater(verify_results[1]["trajectory"]["steps"], 0)

        # -- the checklist reviewer actually saw the revised draft's own
        # content (not a stale/empty subject) when it changed its answer.
        answer_prompts = [
            c["messages"][-1]["content"] for c in toys["cognition"].think_calls
            if c.get("purpose") == "review" and "Does the result satisfy this?" in c["messages"][-1]["content"]
        ]
        self.assertEqual(len(answer_prompts), 2)
        self.assertIn(DRAFT_1, answer_prompts[0])
        self.assertIn(DRAFT_2, answer_prompts[1])


if __name__ == "__main__":
    unittest.main()
