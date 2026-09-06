"""The Verification `Subsystem` (docs/blueprint/subsystems/10-verification.md
section 5). Consumes `verify.requested` (a command -- one Worker's
verification per request, group `verification`) and `plan.proposed`
(an event); runs mechanical checks cheapest-first, stopping at the first
failure; runs the semantic checklist at LIGHT+ rigor; computes trajectory
at STANDARD+; combines into a verdict; emits `verify.result` /
`plan.reviewed`. Reads the target's original/candidate content and
`task.step`/`action:*` history from the Ledger directly (not a side
effect); asks Guardian (`guardian.review`) and Cognition
(`cognition.think`) for their own answers rather than deciding safety or
generating a checklist itself; proposes `action.proposed` for the two
checks that need real execution (`isolated_test_suite`,
`run_python_sandboxed`) and awaits the matching `action.result` by
`action_id` -- Verification never runs a tool itself (harness-01,
"minimal scaffolding, minimal duplicate executors").

Every external call is bounded by a timeout and degrades honestly: a
sibling that never answers (not built yet, or genuinely down) becomes
`insufficient_evidence` or a skipped check, never a hang and never a
false `fail` (`01` section 4.5).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.protocols import Context, Health

from .api import ActionResult, CheckContext, CheckResult, ReviewReply, ThinkReply, VerifyRequest
from .checklist import evaluate_checklist, generate_checklist
from .checks import ALL_CHECKS
from .config import VerificationConfig
from .planreview import review_plan
from .rigor import select_rigor
from .trajectory import TrajectoryMetrics, compute_trajectory
from .verdict import combine, feedback_to_wire

_ORDER = {"free": 0, "cheap": 1, "expensive": 2}


def _guardian_kind(kind: str) -> str:
    # guardian.review's wire kind enum is self_patch|skill only
    # (contracts/schema/guardian.review.v1.json); every other verification
    # kind (task, plan-step "patch") is reviewed the same way self_patch is.
    return "skill" if kind == "skill" else "self_patch"


class VerificationService:
    name = "verification"
    version = "0.1.0"
    consumes = (topics.VERIFY_REQUESTED, topics.PLAN_PROPOSED, topics.SYSTEM_STATE_CHANGED)
    produces = (
        topics.VERIFY_RESULT, topics.PLAN_REVIEWED, topics.ACTION_PROPOSED,
        topics.GUARDIAN_REVIEW, topics.COGNITION_THINK, topics.UI_NOTICE,
    )

    def __init__(self, config: VerificationConfig | None = None) -> None:
        self._config = config or VerificationConfig()
        self._ctx: Context | None = None
        self._subs: list = []
        self._pending_actions: dict[str, asyncio.Future] = {}
        self._paused = False
        self._stopping = False
        self._floor_streak = 0
        self._inflight: set[asyncio.Task] = set()

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._subs.append(await ctx.bus.subscribe(topics.VERIFY_REQUESTED, self._on_verify_requested, group="verification"))
        self._subs.append(await ctx.bus.subscribe(topics.PLAN_PROPOSED, self._on_plan_proposed))
        self._subs.append(await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_state_changed))
        self._subs.append(await ctx.bus.subscribe(topics.ACTION_RESULT, self._on_action_result))

    async def stop(self) -> None:
        self._stopping = True
        for task in list(self._inflight):
            task.cancel()
        for sub in self._subs:
            await sub.unsubscribe()

    async def health(self) -> Health:
        if self._floor_streak >= 5:
            return Health.degraded(f"semantic reviewer has been on the floor for {self._floor_streak} verifications in a row")
        return Health.ok()

    # -- event handlers -----------------------------------------------------------------
    async def _on_state_changed(self, message: Message) -> None:
        state = message.payload.get("state")
        self._paused = state == "paused"
        self._stopping = state == "stopping"

    async def _on_action_result(self, message: Message) -> None:
        action_id = message.payload.get("action_id")
        fut = self._pending_actions.pop(action_id, None)
        if fut is not None and not fut.done():
            fut.set_result(message.payload)

    async def _on_verify_requested(self, message: Message) -> None:
        task = asyncio.ensure_future(self._run_verification(message))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        await task

    async def _on_plan_proposed(self, message: Message) -> None:
        ctx = self._ctx
        assert ctx is not None
        result = await review_plan(self._think, self._review, message.payload, self._config.plan_review_max_steps)
        reviewed = ctx.bus.new(
            topics.PLAN_REVIEWED, {"plan_id": message.payload["plan_id"], "verdict": result.verdict,
                                    "checklist": result.checklist, "feedback": result.feedback},
            caused_by=message,
        )
        await ctx.bus.publish(reviewed)

    # -- the main pipeline --------------------------------------------------------------
    async def _run_verification(self, message: Message) -> None:
        ctx = self._ctx
        assert ctx is not None
        payload = message.payload
        verification_id = payload["verification_id"]
        task_id = payload["task_id"]
        kind = payload["kind"]

        existing = await self._find_existing_result(verification_id)
        if existing is not None:
            # section 8, "duplicate request": a redelivered verify.requested
            # (at-least-once bus, or a caller retrying) re-emits the recorded
            # verdict rather than re-running the pipeline a second time.
            result_msg = ctx.bus.new(
                topics.VERIFY_RESULT, existing, caused_by=message, partition_key=f"task:{task_id}"
            )
            await ctx.bus.publish(result_msg)
            return

        if self._stopping:
            await self._emit_result(message, verification_id, task_id, "insufficient_evidence", [], None, {"stopping": True})
            return

        subject = await self._resolve_subject(payload.get("subject_ref", ""))
        req = VerifyRequest(
            verification_id=verification_id, task_id=task_id, kind=kind, subject=subject,
            checklist_hint=payload.get("checklist_hint"),
            reversibility=subject.get("reversibility", "reversible"),
        )
        rigor = select_rigor(req, self._config)

        if rigor.value == "none":
            await self._emit_result(message, verification_id, task_id, "pass", [], None, {"skipped": True})
            return

        check_ctx = CheckContext(act=self._act, think=self._think, review=self._review, clock=ctx.clock, config=self._config)
        applicable = sorted((c for c in ALL_CHECKS if c.applies(req)), key=lambda c: _ORDER[c.cost])
        # FULL rigor runs isolated_suite/sandbox_smoke; lighter rigor skips the expensive check.
        if rigor.value in ("none", "light", "standard"):
            applicable = [c for c in applicable if c.name != "isolated_suite"]

        mechanical_results: list[tuple[str, CheckResult]] = []
        for check in applicable:
            result = await check.run(req, check_ctx)
            mechanical_results.append((check.name, result))
            if result.status == "failed":
                break  # cheapest-first: stop at the first failure

        answered_items = []
        if rigor.value in ("light", "standard", "full") and not any(r.status == "failed" for _, r in mechanical_results):
            items = await generate_checklist(self._think, req, self._config)
            answered_items = await evaluate_checklist(self._think, req, items)
            if answered_items and all(a.answer is None for a in answered_items):
                self._floor_streak += 1
            else:
                self._floor_streak = 0

        trajectory = (
            await compute_trajectory(ctx.ledger, task_id)
            if rigor.value in ("standard", "full")
            else TrajectoryMetrics(available=False)
        )

        combined = combine(mechanical_results, answered_items, trajectory, self._config)
        await self._emit_result(
            message, verification_id, task_id, combined.verdict, combined.checklist, combined.feedback, combined.mechanical, trajectory
        )

    async def _resolve_subject(self, subject_ref: str) -> dict[str, Any]:
        ctx = self._ctx
        assert ctx is not None
        if not subject_ref:
            return {}
        try:
            raw = await ctx.ledger.get_blob(subject_ref)
            return json.loads(raw.decode("utf-8"))
        except Exception:  # noqa: BLE001 -- a missing/malformed blob degrades to an empty subject
            return {}

    async def _emit_result(self, message, verification_id, task_id, verdict, checklist, feedback, mechanical, trajectory=None):
        ctx = self._ctx
        assert ctx is not None
        traj = trajectory or TrajectoryMetrics(available=False)
        payload = {
            "verification_id": verification_id, "task_id": task_id, "verdict": verdict,
            "checklist": checklist, "trajectory": traj.to_payload(), "mechanical": mechanical,
        }
        if feedback is not None:
            payload["feedback"] = feedback_to_wire(feedback)
        result_msg = ctx.bus.new(topics.VERIFY_RESULT, payload, caused_by=message, partition_key=f"task:{task_id}")
        await ctx.bus.publish(result_msg)
        await self._append_verdict(verification_id, payload)

    async def _append_verdict(self, verification_id: str, payload: dict) -> None:
        ctx = self._ctx
        assert ctx is not None
        try:
            await ctx.ledger.append(
                f"verify:{verification_id}",
                Event(stream=f"verify:{verification_id}", type="verdict", ts=ctx.clock.now(), trace_id=verification_id,
                      causation_id=None, payload=payload),
            )
        except Exception:  # noqa: BLE001 -- the audit trail is best-effort; the emitted event is the real record
            pass

    async def _find_existing_result(self, verification_id: str) -> dict | None:
        ctx = self._ctx
        assert ctx is not None
        try:
            events = await ctx.ledger.read(f"verify:{verification_id}")
        except Exception:  # noqa: BLE001 -- ledger unavailable: fall through and run normally
            return None
        for event in reversed(events):
            if event.type == "verdict":
                return dict(event.payload)
        return None

    # -- the three outbound calls checks/planreview use ----------------------------------
    async def _act(self, tool: str, args: dict, *, timeout: float | None = None) -> ActionResult:
        ctx = self._ctx
        assert ctx is not None
        action_id = str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_actions[action_id] = fut
        proposal = ctx.bus.new(
            topics.ACTION_PROPOSED,
            {"action_id": action_id, "tool": tool, "args": args, "scope": {"network": False},
             "reversibility": "read_only", "rationale": "verification check", "proposed_by": "verification",
             "task_id": None},
            partition_key=f"verification:{action_id}",
        )
        await ctx.bus.publish(proposal)
        try:
            result = await asyncio.wait_for(fut, timeout=timeout or self._config.action_timeout_seconds)
        except asyncio.TimeoutError:
            self._pending_actions.pop(action_id, None)
            return ActionResult(ok=False, error="timeout")
        return ActionResult(
            ok=result.get("ok", False), output=result.get("stdout_preview", ""),
            output_ref=result.get("output_ref", ""), error=result.get("error"),
            metadata=result.get("metadata", {}),
        )

    async def _think(self, *, purpose: str, prompt: str) -> ThinkReply:
        ctx = self._ctx
        assert ctx is not None
        request = ctx.bus.new(
            topics.COGNITION_THINK,
            {"purpose": purpose, "messages": [{"role": "user", "content": prompt}],
             "budget": {"max_tokens": 512, "max_cost_usd": 0.05}, "require_real_provider": False},
        )
        # request_or_error: a timeout (Cognition not built yet, or genuinely
        # down) comes back as the section-9 {ok:false, error:...} shape
        # instead of an exception -- this is the graceful-degradation path.
        reply = await ctx.bus.request_or_error(request, timeout=self._config.action_timeout_seconds)
        payload = reply.payload
        if payload.get("ok") is False:
            return ThinkReply(text="", floor=True, ok=False)
        return ThinkReply(text=payload.get("text", ""), floor=bool(payload.get("floor")), non_answer=bool(payload.get("non_answer")), ok=True)

    async def _review(self, subject: str, code: str, kind: str) -> ReviewReply:
        ctx = self._ctx
        assert ctx is not None
        code_ref = await ctx.ledger.put_blob(code.encode("utf-8"), content_type="text/x-python")
        request = ctx.bus.new(topics.GUARDIAN_REVIEW, {"subject": subject, "code_ref": code_ref, "kind": _guardian_kind(kind)})
        reply = await ctx.bus.request_or_error(request, timeout=self._config.action_timeout_seconds)
        payload = reply.payload
        if payload.get("ok") is False:
            return ReviewReply(approved=False, ok=False)
        return ReviewReply(
            approved=bool(payload.get("approved")), reasons=tuple(payload.get("reasons", [])),
            layers_run=tuple(payload.get("layers_run", [])), ok=True,
        )
