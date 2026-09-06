"""Reflection as a `Subsystem` (Layer 3, registry.py). Observer only --
never emits `action.proposed`, never writes `self:model` directly (only
`self.observation`; World Model owns the projection).

Scope note (honest, not aspirational): drift review is evaluated once,
at task-terminal time, over the whole accumulated step trajectory,
rather than as a live mid-task check every `drift_check_every_steps` --
a deliberate simplification for this build session (see the package
README's build log and the spec's own section 12 for the fuller,
live-per-step version). The heuristic itself, the combined-score
formula, and the never-fabricate-on-`unknown` rule are all real and
match the spec exactly; only the *timing* of the model-backed review is
simplified.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health

from .calibration import CalibrationTable
from .config import Config
from .critique import parse_critique
from .drift import DriftTracker, parse_verdict
from .health import HealthMonitor
from .patterns import PatternMiner

NAME = "reflection"
VERSION = "0.1.0"

HEALTH_STREAM = "reflect:health"
DRIFT_STREAM_PREFIX = "reflect:drift:"
CRITIQUE_STREAM_PREFIX = "reflect:critique:"
CALIBRATION_STREAM = "reflect:calibration"
PATTERNS_STREAM = "reflect:patterns"
SELF_STREAM = "reflect:self"

_CRITIQUE_KINDS = frozenset({"patch", "skill", "research", "project"})


@dataclass
class _TaskMeta:
    kind: str = "chat"
    description: str = ""
    scope_paths: tuple[str, ...] = ()
    tracker: DriftTracker | None = None
    started_ts: float = 0.0


class Service:
    name = NAME
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.PERSONA_STATE_CHANGED,
        topics.TASK_CREATED, topics.TASK_STEP, topics.TASK_COMPLETED, topics.TASK_FAILED, topics.TASK_BLOCKED,
        topics.VERIFY_RESULT,
        topics.PLAN_REVISED,
        topics.LEARN_OUTCOME_RECORDED, topics.LEARN_SELF_PATCH_APPLIED, topics.LEARN_SELF_PATCH_REVERTED,
        topics.LEARN_SKILL_ACQUIRED,
        topics.SYSTEM_STARTED, topics.SYSTEM_STATE_CHANGED, topics.SYSTEM_TICK_SLEEP,
        topics.REFLECT_REVIEW_REQUEST,
    )
    produces: tuple[str, ...] = (
        topics.REFLECT_HEALTH_FINDING, topics.REFLECT_PATTERNS_FOUND, topics.REFLECT_CALIBRATION_UPDATED,
        topics.REFLECT_DRIFT_DETECTED, topics.SELF_OBSERVATION, topics.MEMORY_STORE,
        topics.COGNITION_THINK, topics.REFLECT_REVIEW_REPLY, topics.SYSTEM_HEALTH,
    )

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self._ctx: Context | None = None
        self._subs: list = []
        self._health = HealthMonitor(self.config)
        self._last_health_severity: str | None = None
        self._patterns = PatternMiner(self.config)
        self._calibration = CalibrationTable(self.config)
        self._tasks: dict[str, _TaskMeta] = {}
        self._paused = False
        self._review_sem: asyncio.Semaphore | None = None

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        self._review_sem = asyncio.Semaphore(self.config.max_concurrent_reviews)
        self._subs = [
            await ctx.bus.subscribe(topics.PERSONA_STATE_CHANGED, self._on_persona_state),
            await ctx.bus.subscribe(topics.TASK_CREATED, self._on_task_created),
            await ctx.bus.subscribe(topics.TASK_STEP, self._on_task_step),
            await ctx.bus.subscribe(topics.TASK_COMPLETED, self._on_task_terminal("completed")),
            await ctx.bus.subscribe(topics.TASK_FAILED, self._on_task_terminal("failed")),
            await ctx.bus.subscribe(topics.TASK_BLOCKED, self._on_task_terminal("blocked")),
            await ctx.bus.subscribe(topics.VERIFY_RESULT, self._on_verify_result),
            await ctx.bus.subscribe(topics.PLAN_REVISED, self._on_plan_revised),
            await ctx.bus.subscribe(topics.LEARN_OUTCOME_RECORDED, self._on_outcome_recorded),
            await ctx.bus.subscribe(topics.LEARN_SELF_PATCH_APPLIED, self._on_self_patch("applied")),
            await ctx.bus.subscribe(topics.LEARN_SELF_PATCH_REVERTED, self._on_self_patch("reverted")),
            await ctx.bus.subscribe(topics.LEARN_SKILL_ACQUIRED, self._on_skill_acquired),
            await ctx.bus.subscribe(topics.SYSTEM_STARTED, self._on_system_started),
            await ctx.bus.subscribe(topics.SYSTEM_STATE_CHANGED, self._on_system_state),
            await ctx.bus.subscribe(topics.SYSTEM_TICK_SLEEP, self._on_sleep),
            await ctx.bus.subscribe(topics.REFLECT_REVIEW_REQUEST, self._on_review_request),
        ]
        ctx.logger.info("reflection.started")

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs = []

    async def health(self) -> Health:
        return Health.ok()

    # -- persona / health -------------------------------------------------------------------

    async def _on_persona_state(self, message: Message) -> None:
        p = message.payload
        self._health.observe(p["valence"], p["arousal"], p["cognitive_load"], p["source"], message.ts)
        finding = self._health.inspect()
        severity = finding.severity if finding is not None else "ok"
        if severity == self._last_health_severity:
            return
        self._last_health_severity = severity
        if finding is None:
            return
        await self._append(HEALTH_STREAM, "finding", {"severity": finding.severity, "detail": finding.detail, "action_taken": finding.action_taken})
        await self._publish(message, topics.REFLECT_HEALTH_FINDING, {
            "severity": finding.severity, "detail": finding.detail, "action_taken": finding.action_taken,
        })

    # -- task lifecycle / drift --------------------------------------------------------------

    async def _on_task_created(self, message: Message) -> None:
        p = message.payload
        scope = p.get("scope") or {}
        meta = _TaskMeta(kind=p["kind"], description=p["description"], scope_paths=tuple(scope.get("paths", [])), started_ts=message.ts)
        meta.tracker = DriftTracker(p["task_id"], p["description"], list(meta.scope_paths), self.config)
        self._tasks[p["task_id"]] = meta
        await self._append(f"{DRIFT_STREAM_PREFIX}{p['task_id']}", "goal_registered", {"goal": p["description"], "scope": list(meta.scope_paths)})

    async def _on_task_step(self, message: Message) -> None:
        p = message.payload
        meta = self._tasks.get(p["task_id"])
        if meta is None or meta.tracker is None:
            return
        meta.tracker.observe_step(p.get("tool"), p.get("summary", ""))
        await self._append(f"{DRIFT_STREAM_PREFIX}{p['task_id']}", "step_seen", {"step_no": p["step_no"], "tool": p.get("tool")})

    def _on_task_terminal(self, outcome: str):
        async def _handler(message: Message) -> None:
            p = message.payload
            task_id = p["task_id"]
            meta = self._tasks.pop(task_id, _TaskMeta())
            succeeded = outcome == "completed"

            self._patterns.add(meta.kind, succeeded, None, message.ts)

            confidence = p.get("confidence")
            if isinstance(confidence, (int, float)):
                self._calibration.record(meta.kind, float(confidence), succeeded)

            if meta.tracker is not None:
                await self._run_drift_close(message, meta)

            await self._publish(message, topics.SELF_OBSERVATION, {
                "kind": "success" if succeeded else "failure",
                "detail": f"task {task_id} ({meta.kind}) {outcome}: {p.get('reason') or p.get('result_summary') or ''}",
            })

            if meta.kind in _CRITIQUE_KINDS:
                await self._run_critique(message, task_id, meta, succeeded, p)
        return _handler

    async def _run_drift_close(self, message: Message, meta: _TaskMeta) -> None:
        tracker = meta.tracker
        assert tracker is not None
        verdict = None
        if tracker.due_for_review() and not self._paused and self._ctx is not None:
            verdict = await self._request_review(message, tracker.goal, list(tracker.scope_paths))
            tracker.mark_reviewed()
            await self._append(f"{DRIFT_STREAM_PREFIX}{tracker.task_id}", "review", {"verdict": verdict.verdict})
        combined, finding = tracker.combined(verdict)
        if finding is None:
            return
        await self._append(f"{DRIFT_STREAM_PREFIX}{tracker.task_id}", "detected", {"kind": finding.kind, "score": combined, "recommendation": finding.recommendation})
        await self._publish(message, topics.REFLECT_DRIFT_DETECTED, {
            "kind": finding.kind, "evidence": finding.evidence, "recommendation": finding.recommendation, "task_id": tracker.task_id,
        })

    async def _request_review(self, message: Message, goal: str, scope_paths: list[str]):
        assert self._ctx is not None and self._review_sem is not None
        async with self._review_sem:
            prompt = (
                f"Goal: {goal}\nDeclared scope: {scope_paths}\n"
                "Is the work so far still serving the goal? Answer on_track, drifting, or unknown, then one sentence."
            )
            req = message.caused(topics.COGNITION_THINK, {
                "purpose": "review", "messages": [{"role": "user", "content": prompt}],
                "budget": {"max_tokens": 200, "max_cost_usd": 0.02}, "require_real_provider": False,
            }, source=self._ctx.source)
            reply = await self._ctx.bus.request_or_error(req, timeout=self.config.review_timeout_s)
            if reply.payload.get("ok") is False:
                return parse_verdict("")
            return parse_verdict(reply.payload.get("text", ""))

    async def _run_critique(self, message: Message, task_id: str, meta: _TaskMeta, succeeded: bool, terminal_payload: dict) -> None:
        assert self._ctx is not None
        mechanical = terminal_payload.get("result_summary") or terminal_payload.get("reason") or ("succeeded" if succeeded else "failed")
        text = ""
        if not self._paused:
            prompt = (
                f"Task ({meta.kind}): {meta.description}\nOutcome: {'succeeded' if succeeded else 'failed'} -- {mechanical}\n"
                'Respond as JSON: {"what_changed": str, "confidence": 0-1, "open_questions": [str], "lesson": str|null}'
            )
            req = message.caused(topics.COGNITION_THINK, {
                "purpose": "review", "messages": [{"role": "user", "content": prompt}],
                "budget": {"max_tokens": self.config.critique_max_tokens, "max_cost_usd": 0.02},
                "require_real_provider": False,
            }, source=self._ctx.source)
            reply = await self._ctx.bus.request_or_error(req, timeout=self.config.review_timeout_s)
            if reply.payload.get("ok") is not False:
                text = reply.payload.get("text", "")

        critique = parse_critique(text, mechanical_summary=mechanical)
        await self._append(f"{CRITIQUE_STREAM_PREFIX}{task_id}", "critique", {
            "what_changed": critique.what_changed, "confidence": critique.confidence,
            "open_questions": critique.open_questions, "lesson": critique.lesson, "floor": critique.floor,
        })
        await self._publish(message, topics.MEMORY_STORE, {
            "kind": "episodic", "content": critique.what_changed,
            "tags": ["self_critique", f"task:{task_id}"], "source_ref": f"reflect:critique:{task_id}",
        })
        if critique.confidence is not None:
            self._calibration.record(meta.kind, critique.confidence, succeeded)

    # -- calibration inputs from elsewhere --------------------------------------------------

    async def _on_verify_result(self, message: Message) -> None:
        p = message.payload
        confidence = p.get("confidence")
        if isinstance(confidence, (int, float)):
            self._calibration.record("verify", float(confidence), p["verdict"] == "pass")

    async def _on_plan_revised(self, message: Message) -> None:
        # Known simplification: plan_id isn't guaranteed to equal the
        # project TASK_CREATED's task_id anywhere in the current
        # contracts, so a project-level DriftTracker (spec section 5.4's
        # closing paragraph, "the same tracker runs at plan level") isn't
        # actually reachable from this event yet -- this only fires for
        # the (currently untested) case a caller happens to key them the
        # same. Left in place rather than removed, with this note, so
        # wiring the real project<->plan correlation later is a one-line
        # change, not a re-derivation.
        p = message.payload
        meta = self._tasks.get(p.get("plan_id", ""))
        if meta is not None and meta.tracker is not None:
            meta.tracker.observe_plan_revision(bool(p.get("reason")))

    async def _on_outcome_recorded(self, message: Message) -> None:
        p = message.payload
        self._patterns.add(p["task_type"], p["succeeded"], p.get("strategy"), message.ts)
        confidence = p.get("confidence")
        if isinstance(confidence, (int, float)):
            self._calibration.record(p["task_type"], float(confidence), p["succeeded"])

    # -- self.observation from learn.* / system.* -------------------------------------------

    def _on_self_patch(self, outcome: str):
        async def _handler(message: Message) -> None:
            p = message.payload
            await self._publish(message, topics.SELF_OBSERVATION, {
                "kind": "change", "detail": f"self-patch {outcome}: {p['subject']} ({p.get('commit', '')})",
            })
        return _handler

    async def _on_skill_acquired(self, message: Message) -> None:
        p = message.payload
        await self._publish(message, topics.SELF_OBSERVATION, {"kind": "change", "detail": f"skill acquired: {p['name']} ({p['tests']} tests)"})

    async def _on_system_started(self, message: Message) -> None:
        await self._publish(message, topics.SELF_OBSERVATION, {"kind": "restart", "detail": f"system started (mode={message.payload.get('mode', '?')})"})

    async def _on_system_state(self, message: Message) -> None:
        self._paused = message.payload.get("state") in ("paused", "stopping", "stopped")

    # -- sleep tick: pattern mining + calibration emission -----------------------------------

    async def _on_sleep(self, message: Message) -> None:
        now = self._ctx.clock.now() if self._ctx is not None else message.ts
        patterns = self._patterns.mine(now)
        if patterns:
            await self._append(PATTERNS_STREAM, "mined", {"window": self.config.pattern_window_seconds, "count": len(patterns)})
            await self._publish(message, topics.REFLECT_PATTERNS_FOUND, {
                "window": self.config.pattern_window_seconds,
                "patterns": [{"kind": p.kind, "rate": p.rate, "proposal": p.proposal} for p in patterns],
            })
        for task_type in self._calibration.task_types():
            summary = self._calibration.summary(task_type)
            if summary is None:
                continue
            await self._append(CALIBRATION_STREAM, "snapshot", {
                "task_type": summary.task_type, "stated_confidence": summary.stated_confidence,
                "empirical_accuracy": summary.empirical_accuracy, "brier": summary.brier, "samples": summary.samples,
            })
            await self._publish(message, topics.REFLECT_CALIBRATION_UPDATED, {
                "task_type": summary.task_type, "stated_confidence": summary.stated_confidence,
                "empirical_accuracy": summary.empirical_accuracy,
            })

    async def _on_review_request(self, message: Message) -> None:
        now = self._ctx.clock.now() if self._ctx is not None else message.ts
        window_s = message.payload.get("window_seconds") or self.config.pattern_window_seconds
        patterns = self._patterns.mine(now, window_s=window_s)
        assert self._ctx is not None
        await self._ctx.bus.reply(message, type=topics.REFLECT_REVIEW_REPLY, payload={
            "patterns": [{"kind": p.kind, "rate": p.rate, "proposal": p.proposal} for p in patterns],
            "takeaways": [],
        })

    # -- helpers ------------------------------------------------------------------------------

    async def _publish(self, cause: Message, type_: str, payload: dict) -> None:
        assert self._ctx is not None
        await self._ctx.bus.publish(cause.caused(type_, payload, source=self._ctx.source))

    async def _append(self, stream: str, event_type: str, payload: dict) -> None:
        if self._ctx is None:
            return
        import uuid

        from simorgh.contracts.envelope import Event
        await self._ctx.ledger.append(stream, Event(
            stream=stream, type=event_type, ts=self._ctx.clock.now(),
            trace_id=str(uuid.uuid4()), causation_id=None, payload=payload,
        ))
