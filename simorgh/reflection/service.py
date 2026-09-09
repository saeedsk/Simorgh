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
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health

from .calibration import CalibrationTable
from .config import Config
from . import distillation
from .critique import parse_critique
from .denials import DenialMiner
from .drift import DriftTracker, parse_verdict
from .health import HealthMonitor
from .patterns import PatternMiner

NAME = "reflection"
VERSION = "0.1.0"


def _looks_like_the_repo(candidate: Path) -> bool:
    return (candidate / "simorgh" / "kernel" / "service.py").is_file()


def _repo_root() -> Path:
    """Where Sim's own source lives -- duplicated from
    `execution/config.py::find_repo_root` rather than imported (a
    subsystem may not import another's internals,
    tests/simorgh/test_module_boundaries.py).

    `Config.skill_dir` (default `"simorgh_skills"`) is a bare relative
    path, and `_existing_skills` used to resolve it against
    `Path.cwd()` directly. `apply_source_patch` -- the tool that
    actually writes a distilled skill to disk -- resolves the very
    same `subject` path against `execution.Config.repo_root`, which is
    `find_repo_root()`, not the cwd. Booted from anywhere but the repo
    root (a sandboxed trial, the sim loader, a service manager with its
    own working directory -- exactly the cases `find_repo_root`'s own
    docstring exists to cover, observer 2026-09-08), `_existing_skills`
    silently saw an empty directory forever while skills piled up at
    the real path, defeating the slug-collision check `distillation.
    slug_for` depends on it for (observer, W21-09, 2026-09-09).
    """
    here = Path(__file__).resolve().parents[2]
    base = Path.cwd().resolve()
    for candidate in (base, *base.parents):
        if _looks_like_the_repo(candidate):
            return candidate
    return here if _looks_like_the_repo(here) else base

HEALTH_STREAM = "reflect:health"
DRIFT_STREAM_PREFIX = "reflect:drift:"
CRITIQUE_STREAM_PREFIX = "reflect:critique:"
# Skills Reflection proposed off the back of a solved task.
DISTILLATION_STREAM = "reflect:distillation"
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
    # Which tools this task actually used, for distillation.py: a task
    # that reached outside the repo and got somewhere is a technique
    # worth keeping, and the tool list is how that shows.
    tools_used: set[str] = field(default_factory=set)


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
        topics.ACTION_DENIED,
    )
    produces: tuple[str, ...] = (
        topics.REFLECT_HEALTH_FINDING, topics.REFLECT_PATTERNS_FOUND, topics.REFLECT_CALIBRATION_UPDATED,
        topics.REFLECT_DRIFT_DETECTED, topics.SELF_OBSERVATION, topics.MEMORY_STORE,
        topics.COGNITION_THINK, topics.REFLECT_REVIEW_REPLY, topics.SYSTEM_HEALTH,
        topics.TASK_CREATE,
    )

    def __init__(self, config: Config | None = None) -> None:
        self._config_from_caller = config
        self.config = config or Config()
        self._ctx: Context | None = None
        self._subs: list = []
        # `_maybe_distil`'s daily cap. Despite the name, this used to be
        # a counter that only ever went up: nothing ever set it back to
        # 0, so on a process that runs for more than a day (the normal
        # case -- Sim is meant to run continuously) the cap was really
        # "at most `max_distillations_per_day` skills, ever, until the
        # process restarts", not per day at all (observer, W21-09,
        # 2026-09-09). `_distilled_day` below is the UTC day bucket the
        # count was last reset for; `_maybe_distil` resets the counter
        # whenever the bucket changes.
        self._distilled_today = 0
        self._distilled_day: int | None = None
        self._health = HealthMonitor(self.config)
        self._last_health_severity: str | None = None
        self._patterns = PatternMiner(self.config)
        self._denials = DenialMiner(
            window_seconds=self.config.denial_window_seconds,
            min_repeats=self.config.denial_min_repeats,
        )
        self._calibration = CalibrationTable(self.config)
        self._tasks: dict[str, _TaskMeta] = {}
        self._paused = False
        self._review_sem: asyncio.Semaphore | None = None

    def _rebuild_from_config(self) -> None:
        """Re-make the pieces that were built from config defaults."""
        self._health = HealthMonitor(self.config)
        self._patterns = PatternMiner(self.config)
        self._denials = DenialMiner(
            window_seconds=self.config.denial_window_seconds,
            min_repeats=self.config.denial_min_repeats,
        )
        self._calibration = CalibrationTable(self.config)

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        # `Context.config` is this subsystem's own `[reflection]` section
        # (03 section 6). Nothing read it, here or anywhere -- so every
        # knob in that section was dead, and only the dataclass defaults
        # ever applied. An explicitly-constructed config still wins, which
        # is how tests and embeddings inject one.
        if self._config_from_caller is None and ctx.config:
            self.config = Config.from_mapping(dict(ctx.config))
            self._rebuild_from_config()
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
            await ctx.bus.subscribe(topics.ACTION_DENIED, self._on_action_denied),
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
        if meta is None:
            return
        if p.get("tool"):
            meta.tools_used.add(str(p["tool"]))
        if meta.tracker is None:
            return
        if p.get("tool"):
            meta.tools_used.add(str(p["tool"]))
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
        await self._maybe_distil(message, task_id, meta, succeeded)

    async def _maybe_distil(self, message: Message, task_id: str, meta: _TaskMeta, succeeded: bool) -> None:
        """Offer to turn a solved problem into a skill.

        Sim could always write skills when asked; what it never did was
        notice it had just worked something out that will be needed
        again. `distillation.candidate_for` is deliberately stingy --
        most tasks are ordinary work -- and the daily cap means a bad
        run of judgement costs a few tasks, not a directory full of
        near-duplicate skills. Planning dedupes on the subject, so a
        second attempt at the same slug is dropped there rather than
        producing two skills that do the same thing.
        """
        if not self.config.distillation_enabled or self._ctx is None:
            return
        candidate = distillation.candidate_for(
            kind=meta.kind, succeeded=succeeded, description=meta.description,
            tools=meta.tools_used, existing_skills=self._existing_skills(),
        )
        if candidate is None:
            return
        today = int((self._ctx.clock.now() if self._ctx is not None else message.ts) // 86400)
        if today != self._distilled_day:
            self._distilled_day = today
            self._distilled_today = 0
        if self._distilled_today >= self.config.max_distillations_per_day:
            return
        self._distilled_today += 1
        subject = f"{self.config.skill_dir}/{candidate.slug}.py"
        await self._append(DISTILLATION_STREAM, "proposed", {
            "task_id": task_id, "slug": candidate.slug, "subject": subject,
            "tools": list(candidate.tools),
        })
        await self._publish(message, topics.TASK_CREATE, {
            "kind": "skill", "description": candidate.description, "subject": subject,
            "origin": "reflection",
        })

    def _existing_skills(self) -> set[str]:
        try:
            return {p.stem for p in (_repo_root() / self.config.skill_dir).glob("*.py")}
        except OSError:
            return set()

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

    async def _on_action_denied(self, message: Message) -> None:
        """A denial that keeps repeating becomes a task Sim opens for
        itself.

        The creator, 2026-09-07: "why should [it] take precious time of
        creator to review random warning". Until now `action.denied` had
        one consumer that did anything with it -- the Interface, which
        printed it at a human. This subsystem, whose whole job is turning
        patterns into work, never saw one.

        Raised the moment the threshold is crossed rather than on the
        six-hourly sleep tick, because a denial loop should not run for
        hours before anything notices; `DenialMiner` reports each group
        once per window so this cannot itself become a flood.
        """
        p = message.payload
        reasons = p.get("reasons") or []
        layer = p.get("layer", "")
        now = self._ctx.clock.now() if self._ctx is not None else message.ts

        # A layer="scope" denial is exactly the "scope crossing" the
        # drift heuristic's largest term (weight 0.5, DriftTracker.
        # heuristic_score) is meant to count. Nothing ever called
        # observe_scope_denial() before this -- scope_crossings sat at 0
        # forever, capping the heuristic-only score below
        # drift_emit_threshold even in a genuinely drifting task
        # (confirmed finding). Attribute the denial to the task's own
        # tracker when both a task_id and that task are known; an
        # untracked proposal (no task_id, or a task Reflection never saw
        # task.created for) is silently skipped, same as every other
        # per-task observation in this file.
        if layer == "scope":
            task_id = p.get("task_id")
            meta = self._tasks.get(task_id) if task_id else None
            if meta is not None and meta.tracker is not None:
                meta.tracker.observe_scope_denial()

        pattern = self._denials.add(
            tool=p.get("tool", ""), reason=reasons[0] if reasons else "",
            layer=layer, now=now,
        )
        if pattern is None:
            return
        await self._append(PATTERNS_STREAM, "denial_pattern", {
            "tool": pattern.tool, "reason": pattern.reason, "count": pattern.count,
        })
        await self._publish(message, topics.REFLECT_PATTERNS_FOUND, {
            "window": self.config.denial_window_seconds,
            "patterns": [{"kind": "repeated_denial", "rate": 1.0, "proposal": pattern.proposal}],
        })

    # -- sleep tick: pattern mining + calibration emission -----------------------------------

    async def _on_sleep(self, message: Message) -> None:
        now = self._ctx.clock.now() if self._ctx is not None else message.ts
        patterns = self._patterns.mine(now)
        if patterns:
            await self._append(PATTERNS_STREAM, "mined", {"window": self.config.pattern_window_seconds, "count": len(patterns)})
            await self._publish(message, topics.REFLECT_PATTERNS_FOUND, {
                "window": self.config.pattern_window_seconds,
                # `task_type` on the wire (2026-09-08 observer, w8-04): two
                # genuinely distinct patterns -- different task_types, same
                # window -- render as near-identical proposal text (only the
                # quoted type differs), which pushed their SequenceMatcher
                # ratio to ~0.93 against Planning's 0.45 dedupe threshold and
                # silently collapsed the second one into the first's task.
                # `Pattern` already carries `task_type`; only the wire
                # payload was dropping it. The schema is
                # `additionalProperties: true`, so this is a pure addition --
                # no existing consumer (World Model's `self.observation`
                # mirror, Planning's `on_patterns_found`) breaks by gaining a
                # field it ignores.
                "patterns": [{"kind": p.kind, "rate": p.rate, "proposal": p.proposal, "task_type": p.task_type} for p in patterns],
            })
            # 06-worldmodel.md section 5's ingestion table: a mined pattern
            # is also a `self.observation{kind:limitation}` -- the only
            # wire path a real limitation can reach the Self Model by
            # today (World Model fuzzy-dedupes on ingest, so a pattern
            # re-mined next window is a no-op there, not a duplicate).
            for pattern in patterns:
                await self._publish(message, topics.SELF_OBSERVATION, {"kind": "limitation", "detail": pattern.proposal})
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
