"""The session state machine (16 section 5): CLAIMED -> GATHER -> THINK ->
(final -> VERIFY -> COMPLETED | tool_calls -> PROPOSE -> GATHER) with a
bounded evaluator-optimizer revision loop. One action is proposed per
step and awaited before the next THINK (section 7: "simpler resume and
exact trajectories; cost: no parallel tool calls inside a step").

Deliberately scoped down from the full spec this build: no Plan Mode
artifact assembly, no delegation (fresh/fork), no steer injection, no
reground-every-N-steps restatement. See the package README.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message

from .api import Outcome, Session, Step
from .context import DEFAULT_TIMEOUT_S, Assembler
from .tools import to_action_payload

ACTION_TIMEOUT_S = 5.0
VERIFY_TIMEOUT_S = 5.0


class _EventWaiter:
    """Waits for the first event of any of `types` whose payload[`key`]
    equals `value` -- the action.proposed -> {result|denied|needs_human}
    and verify.requested -> verify.result correlations, neither of which
    rides the bus's reply_to inbox (they're events, not request/reply;
    03 section 1's own table).
    """

    def __init__(self, bus) -> None:
        self._bus = bus

    async def wait(self, types: tuple[str, ...], *, key: str, value: str, timeout: float) -> Message | None:
        fut: asyncio.Future = asyncio.get_running_loop().create_future()

        async def _on(message: Message) -> None:
            if message.payload.get(key) == value and not fut.done():
                fut.set_result(message)

        subs = [await self._bus.subscribe(t, _on) for t in types]
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            for s in subs:
                await s.unsubscribe()


class SessionRunner:
    def __init__(
        self, bus, ledger, *, clock=None, worker_id: str = "w1", is_paused=None,
        think_timeout_s: float = 5.0, action_timeout_s: float = ACTION_TIMEOUT_S,
        verify_timeout_s: float = VERIFY_TIMEOUT_S, assemble_timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._bus = bus
        self._ledger = ledger
        self._clock = clock
        self._worker_id = worker_id
        self._assembler = Assembler(bus, clock=clock, timeout_s=assemble_timeout_s)
        self._waiter = _EventWaiter(bus)
        self._is_paused = is_paused or (lambda: False)
        self._think_timeout_s = think_timeout_s
        self._action_timeout_s = action_timeout_s
        self._verify_timeout_s = verify_timeout_s

    async def run(self, session: Session, *, user_text: str = "") -> Outcome:
        await self._append(session, topics.TASK_STARTED, {"task_id": session.task_id, "worker_id": self._worker_id})
        await self._publish(session, topics.TASK_STARTED, {"task_id": session.task_id, "worker_id": self._worker_id})

        pending_user_text = user_text
        while True:
            if self._paused():
                return await self._pause(session)

            step_no = session.next_step_no()
            is_last = session.budget.is_last_step
            think_reply = await self._think(session, pending_user_text, last_step=is_last)
            pending_user_text = ""

            if think_reply is None:  # provider unavailable / timeout -- honest floor
                if session.profile.name == "chat":
                    return Outcome("completed", result_summary="", floor=True)
                return Outcome("blocked", reason="no real provider")

            session.budget.steps_used += 1
            tool_calls = think_reply.payload.get("tool_calls") or []
            floor = think_reply.payload.get("floor", False)

            if tool_calls and not is_last:
                call = tool_calls[0]  # one action per step (section 7)
                ok, summary = await self._propose_and_await(session, call, step_no)
                step = Step(step_no, "act", summary, tool=call.get("tool"), ok=ok)
                session.record(step)
                await self._record_step(session, step)
                session.messages.append({"role": "assistant", "content": f"[tool_call {call.get('tool')}] -> {summary}"})
                if self._paused():
                    return await self._pause(session)
                continue

            text = think_reply.payload.get("text", "")
            step = Step(step_no, "gather" if step_no == 1 else "act", "final answer", ok=True)
            session.record(step)
            await self._record_step(session, step)
            session.messages.append({"role": "assistant", "content": text})

            if not session.profile.verify:
                return Outcome("completed", result_summary=text, floor=floor)

            return await self._verify_then_finish(session, text, floor=floor)

    # -- phases -----------------------------------------------------------------------------

    async def _think(self, session: Session, user_text: str, *, last_step: bool) -> Message | None:
        messages = await self._assembler.assemble(session, session.profile.scaffold, user_text=user_text)
        req = Message.new(
            topics.COGNITION_THINK, source=self._bus.source,
            payload={
                "purpose": "chat" if session.profile.name == "chat" else "draft",
                "messages": messages, "tools": list(session.profile.tools),
                "budget": {"max_tokens": 2000, "max_cost_usd": 0.5},
                "require_real_provider": False, "last_step": last_step,
            },
            clock=self._clock,
        )
        reply = await self._bus.request_or_error(req, timeout=self._think_timeout_s)
        if reply.payload.get("ok") is False:
            return None
        return reply

    async def _propose_and_await(self, session: Session, call: dict, step_no: int) -> tuple[bool, str]:
        action_id = uuid.uuid4().hex[:12]
        payload = to_action_payload(
            action_id=action_id, task_id=session.task_id, call=call,
            rationale=f"step {step_no} of {session.profile.name} session",
            proposed_by=self._bus.source,
        )
        msg = Message.new(
            topics.ACTION_PROPOSED, source=self._bus.source,
            payload=payload, partition_key=f"task:{session.task_id}", clock=self._clock,
        )
        await self._bus.publish(msg)
        result = await self._waiter.wait(
            (topics.ACTION_RESULT, topics.ACTION_DENIED, topics.ACTION_NEEDS_HUMAN),
            key="action_id", value=action_id, timeout=self._action_timeout_s,
        )
        if result is None:
            return False, f"{call.get('tool')}: no response (timed out)"
        if result.type == topics.ACTION_RESULT:
            return result.payload.get("ok", False), result.payload.get("stdout_preview", "")[:200]
        if result.type == topics.ACTION_DENIED:
            reasons = "; ".join(result.payload.get("reasons", [])) or result.payload.get("layer", "denied")
            return False, f"denied: {reasons}"
        return False, f"needs human: {result.payload.get('question', '')}"

    async def _verify_then_finish(self, session: Session, text: str, *, floor: bool) -> Outcome:
        while True:
            # A fresh verification_id per attempt (not just per session): a
            # real Verification service treats a *repeated* id on
            # `verify:<id>` as a redelivery and replays the recorded verdict
            # instead of re-running checks (10 section 8, "duplicate
            # request") -- reusing one id across revisions would silently
            # replay the first (failing) verdict forever and never see the
            # revised text (harness-06 gap #5: iterative verification).
            verification_id = uuid.uuid4().hex[:12]
            subject_ref = await self._put_verify_subject(session, text)
            msg = Message.new(
                topics.VERIFY_REQUESTED, source=self._bus.source,
                payload={
                    "verification_id": verification_id, "task_id": session.task_id,
                    "kind": "task", "subject_ref": subject_ref,
                },
                partition_key=f"task:{session.task_id}", clock=self._clock,
            )
            await self._bus.publish(msg)
            result = await self._waiter.wait(
                (topics.VERIFY_RESULT,), key="verification_id", value=verification_id, timeout=self._verify_timeout_s,
            )
            if result is None:
                # No Verification subsystem answered -- accept honestly rather than block forever.
                return Outcome("completed", result_summary=text, floor=floor, verification_ref=None)

            verdict = result.payload.get("verdict")
            if verdict in ("pass", "insufficient_evidence"):
                return Outcome("completed", result_summary=text, floor=floor, verification_ref=verification_id)

            if session.budget.revisions_used >= session.profile.max_revisions:
                return Outcome("blocked", reason="verification failed after max revisions", verification_ref=verification_id)

            session.budget.revisions_used += 1
            feedback = result.payload.get("feedback", {}).get("items", [])
            note = "; ".join(f"{f.get('what')}: {f.get('suggested_fix')}" for f in feedback) or "revise and try again"
            session.messages.append({"role": "user", "content": f"Verification feedback: {note}"})
            think_reply = await self._think(session, "", last_step=session.budget.is_last_step)
            if think_reply is None:
                return Outcome("blocked", reason="no real provider during revision", verification_ref=verification_id)
            text = think_reply.payload.get("text", text)
            session.messages.append({"role": "assistant", "content": text})

    async def _put_verify_subject(self, session: Session, text: str) -> str:
        """`verify.requested.subject_ref` is a blob ref, not raw text --
        Verification's `_resolve_subject` reads it with `ledger.get_blob`
        and expects a JSON object with `description`/`result` (the shape
        every other producer, e.g. `learning/pipeline.py`'s
        `candidate_ref`, already sends). Sending truncated raw text there
        silently resolves to an empty subject and the semantic checklist
        loses its signal.
        """
        payload = json.dumps({"description": session.user_text, "result": text[:2000]}).encode("utf-8")
        return await self._ledger.put_blob(payload, content_type="application/json")

    # -- pause/resume -------------------------------------------------------------------------

    def _paused(self) -> bool:
        return self._is_paused()

    async def _pause(self, session: Session) -> Outcome:
        resume_from = len(session.steps)
        await self._append(session, topics.TASK_PAUSED, {
            "task_id": session.task_id, "reason": "system paused", "resume_from_step": resume_from,
        })
        await self._publish(session, topics.TASK_PAUSED, {
            "task_id": session.task_id, "reason": "system paused", "resume_from_step": resume_from,
        })
        return Outcome("paused", reason="system paused")

    # -- ledger + bus plumbing -----------------------------------------------------------------

    async def _record_step(self, session: Session, step: Step) -> None:
        payload = {
            "task_id": session.task_id, "step_no": step.no, "phase": step.phase, "summary": step.summary,
        }
        if step.tool is not None:
            payload["tool"] = step.tool
        if step.ok is not None:
            payload["ok"] = step.ok
        await self._append(session, topics.TASK_STEP, payload)
        await self._publish(session, topics.TASK_STEP, payload)

    async def _append(self, session: Session, type_: str, payload: dict) -> None:
        msg = Message.new(type_, source=self._bus.source, payload=payload,
                          partition_key=f"task:{session.task_id}", clock=self._clock)
        await self._ledger.append(f"task:{session.task_id}", Event.from_message(msg, f"task:{session.task_id}"))

    async def _publish(self, session: Session, type_: str, payload: dict) -> None:
        msg = Message.new(type_, source=self._bus.source, payload=payload,
                          partition_key=f"task:{session.task_id}", clock=self._clock)
        await self._bus.publish(msg)
