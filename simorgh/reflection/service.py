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
import time
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
from .digest import Alert, AlertRouter, Digest, MonitorRegistry
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
    # For the stall check (`stall_idle_seconds`): when this task last
    # showed a sign of life, and whether the current silence has
    # already been reported. Reset by every `task.step`, so a task that
    # stalls, recovers and stalls again is reported twice, not once.
    last_step_ts: float = 0.0
    stall_reported: bool = False
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
        topics.SYSTEM_TICK_IDLE,
    )
    produces: tuple[str, ...] = (
        topics.REFLECT_HEALTH_FINDING, topics.REFLECT_PATTERNS_FOUND, topics.REFLECT_CALIBRATION_UPDATED,
        topics.REFLECT_DRIFT_DETECTED, topics.SELF_OBSERVATION, topics.MEMORY_STORE,
        topics.COGNITION_THINK, topics.REFLECT_REVIEW_REPLY, topics.SYSTEM_HEALTH,
        topics.TASK_CREATE,
        topics.REFLECT_ALERT_RAISED, topics.REFLECT_ALERT_CLEARED, topics.ACTION_PROPOSED,
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
        self._monitors = MonitorRegistry()
        self._ad_hoc: list = []
        self._router: AlertRouter | None = None
        self._digest: Digest | None = None
        self._alert_tick_running = False
        self._reflect_loop: asyncio.Task | None = None

    def _rebuild_from_config(self) -> None:
        """Re-make the pieces that were built from config defaults."""
        self._health = HealthMonitor(self.config)
        self._build_alerting()
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
        self._build_alerting()
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
            await ctx.bus.subscribe(topics.SYSTEM_TICK_IDLE, self._on_idle_tick),
        ]
        if self.config.reflect_after_start_s > 0:
            self._reflect_loop = asyncio.create_task(self._reflect_periodically(), name="reflection-pass")
        ctx.logger.info("reflection.started")

    async def stop(self) -> None:
        if self._reflect_loop is not None:
            self._reflect_loop.cancel()
            try:
                await self._reflect_loop
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise from a background pass
                pass
            self._reflect_loop = None
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
        meta = _TaskMeta(kind=p["kind"], description=p["description"], scope_paths=tuple(scope.get("paths", [])), started_ts=message.ts,
                         last_step_ts=message.ts)
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
        meta.last_step_ts = message.ts
        meta.stall_reported = False
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
                self._record_calibration(meta.kind, confidence, succeeded)

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
            self._record_calibration(meta.kind, critique.confidence, succeeded)
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

    def _record_calibration(self, task_type: str, stated, hit: bool) -> None:
        """One calibration sample, with the unusable ones said out loud.

        `CalibrationTable.record` refuses a confidence that is not a
        probability (NaN, inf, -3.0) instead of folding it into the
        figures. Refusing silently would be the other half of the same
        honesty problem, so it is logged: a producer sending garbage
        confidence is a bug someone has to see.
        """
        if self._calibration.record(task_type, float(stated), hit):
            return
        if self._ctx is not None:
            self._ctx.logger.warning(
                "reflection.calibration_sample_unusable", task_type=task_type, stated=repr(stated),
            )

    # -- calibration inputs from elsewhere --------------------------------------------------

    async def _on_verify_result(self, message: Message) -> None:
        p = message.payload
        confidence = p.get("confidence")
        if isinstance(confidence, (int, float)):
            self._record_calibration("verify", confidence, p["verdict"] == "pass")

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
            self._record_calibration(p["task_type"], confidence, p["succeeded"])

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

    # -- the reflection pass: pattern mining + calibration emission ---------------------------
    #
    # Reached two ways, and the second one is why the first was not
    # enough. `system.tick.sleep` is the six-hourly tick, and the
    # Kernel's sleep loop waits a full `sleep_every_s` before its FIRST
    # tick -- so a session shorter than six hours ran this pass zero
    # times, and every pattern mined, every calibration snapshot and
    # every `self.observation{kind:limitation}` in it reached nobody
    # (observer bulk5-02, 2026-09-10; a real Kernel boot with twelve
    # failed `patch` outcomes at stated confidence 0.9 published
    # nothing at all until a sleep tick was fired by hand). The
    # `reflect_after_start_s`/`reflect_every_s` loop below is the same
    # fix `[ledger] compact_after_start_s` and `[memory]
    # consolidate_after_start_s` already carry for the same reason.

    async def _reflect_periodically(self) -> None:
        """The pass on a real cadence, not only on the six-hourly tick.

        Deliberately not run inside `start()`: at boot there is nothing
        to mine yet, and boot is not the place to wait. A failure is
        logged and dropped -- reflection that cannot mine this minute
        still mines next minute.
        """
        assert self._ctx is not None
        delay = self.config.reflect_after_start_s
        while True:
            try:
                # Wall-clock `asyncio.sleep`, not `ctx.clock.sleep`, and
                # for the same reason `ledger`/`memory`'s equivalent
                # loops use it: this is a real-time cadence, and a test
                # `FakeClock` whose `sleep` returns instantly would turn
                # it into a hot loop republishing the same mined
                # patterns thousands of times.
                await asyncio.sleep(delay)
                if not self._paused:
                    await self._run_pass(Message.new(
                        topics.SYSTEM_TICK_SLEEP, source=self._ctx.source,
                        payload={"window_seconds": delay}, clock=self._ctx.clock.now,
                    ))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._ctx.logger.warning("reflection.pass_failed", error=repr(exc))
            if self.config.reflect_every_s <= 0:
                return
            delay = self.config.reflect_every_s

    async def _on_sleep(self, message: Message) -> None:
        await self._run_pass(message)

    async def _run_pass(self, message: Message) -> None:
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

    # -- monitors, alerts and the digest -----------------------------------------------------
    #
    # platform-connectors-design.md section 6. The deciding is all in
    # `digest.py` and is pure; this is the half that touches the world:
    # run the due monitors on an idle tick, put the raised alerts on the
    # bus and in the Ledger, and turn the ones that earned a person's
    # attention into a real `notify` call.
    #
    # That call goes out as `action.proposed`, not by reaching for the
    # tool -- so Guardian sees it exactly like any other irreversible
    # action, `irreversible_requires_human` still holds it for approval
    # if that is the deployment's choice, and it is ledgered with
    # everything else. An alerting path that bypassed the gate would be
    # the one irreversible thing in the system nobody was watching.

    ALERTS_STREAM = "reflection:alerts"

    def _build_alerting(self) -> None:
        clock = self._ctx.clock.now if self._ctx is not None else None
        self._monitors = MonitorRegistry(clock=clock) if clock else MonitorRegistry()
        try:
            self._router = AlertRouter(
                clock=clock or time.time,
                warn_window_s=self.config.alert_warn_window_s,
                quiet_hours=self.config.quiet_hours,
                announce_enabled=self.config.announce_critical,
            )
        except ValueError as exc:
            # A malformed `quiet_hours` must not take the subsystem down,
            # and must not silently become "no quiet hours" either --
            # that would send at 3am precisely because someone tried to
            # stop it.
            if self._ctx is not None:
                self._ctx.logger.warning("reflection.quiet_hours_invalid", error=str(exc))
            self._router = AlertRouter(
                clock=clock or time.time,
                warn_window_s=self.config.alert_warn_window_s,
                announce_enabled=self.config.announce_critical,
            )
        self._digest = Digest(hour=self.config.digest_hour, clock=clock or time.time)

    def register_monitor(self, monitor) -> None:
        """How a domain adds a check. `home`, `pim`, `security` and the
        rest register theirs at their own `start()`; nothing here needs
        to know they exist."""
        self._monitors.register(monitor)

    def raise_alert(self, alert: Alert) -> None:
        """A one-off alert from something that is not a polling monitor
        (a percept, a failed sync). Routed on the next idle tick with
        everything else, so the rate limit and quiet hours apply to it
        exactly as they do to a monitor's."""
        self._ad_hoc.append(alert)

    async def _on_idle_tick(self, message: Message) -> None:
        if self._paused:
            return
        # Deliberately ahead of, and independent of, the monitor gate:
        # the stall check is not a monitor and must still run when
        # `monitors_enabled` is off.
        await self._check_stalls(message)
        if not self.config.monitors_enabled or self._router is None:
            return
        # An idle tick can arrive while the previous one is still
        # checking. Overlapping runs would double-send every alert the
        # first pass had not yet recorded as open.
        if self._alert_tick_running:
            return
        self._alert_tick_running = True
        try:
            await self._run_monitors(message)
        except Exception as exc:  # noqa: BLE001 -- alerting must not break the tick it rides on
            if self._ctx is not None:
                self._ctx.logger.warning("reflection.monitor_tick_failed", error=repr(exc))
        finally:
            self._alert_tick_running = False

    async def _check_stalls(self, cause: Message) -> None:
        """An in-progress task that has shown no sign of life for
        `stall_idle_seconds` is `behavior` drift, recommendation `note`.

        12-reflection.md section 3.5 has specified this since the
        subsystem was designed -- "In-progress task with no step for
        this long -> `behavior` drift `note`" -- and nothing read the
        field. `kernel/configcheck.py` carried it in
        `KNOWN_DEAD_FIELDS`, which is honest about it being dead but
        does not make the stall visible to anyone. It is now built, on
        the tick that is exactly right for it: `system.tick.idle` fires
        only when nothing is happening, which is the definition of the
        condition being looked for (observer bulk5-02, 2026-09-10).

        Reported once per stall episode. A task that produces a step
        and goes quiet again is a second stall and is reported again;
        one that simply stays quiet is not re-reported every three
        seconds.
        """
        if self.config.stall_idle_seconds <= 0 or not self._tasks:
            return
        now = self._ctx.clock.now() if self._ctx is not None else cause.ts
        for task_id, meta in list(self._tasks.items()):
            if meta.stall_reported or meta.last_step_ts <= 0:
                continue
            idle_for = now - meta.last_step_ts
            if idle_for < self.config.stall_idle_seconds:
                continue
            meta.stall_reported = True
            evidence = (
                f"no step for {idle_for:.0f}s (threshold {self.config.stall_idle_seconds:.0f}s); "
                f"goal: {' '.join((meta.description or '').split())[:200]}"
            )
            await self._append(f"{DRIFT_STREAM_PREFIX}{task_id}", "stalled",
                               {"idle_seconds": idle_for, "threshold": self.config.stall_idle_seconds})
            await self._publish(cause, topics.REFLECT_DRIFT_DETECTED, {
                "kind": "behavior", "evidence": evidence, "recommendation": "note", "task_id": task_id,
            })

    async def _run_monitors(self, cause: Message) -> None:
        assert self._router is not None and self._ctx is not None
        deliveries, resolved = await self._monitors.run_due(self._router)

        for name, alerts in self._drain_ad_hoc().items():
            sent, cleared = self._router.observe(name, alerts)
            deliveries.extend(sent)
            resolved.extend(cleared)

        for delivery in deliveries:
            alert = delivery.alert
            await self._publish(cause, topics.REFLECT_ALERT_RAISED, {
                "monitor": alert.monitor, "severity": alert.severity, "key": alert.key,
                "message": alert.message, "channel": delivery.channel, "reason": delivery.reason,
                "reopened": float(delivery.reopened), "entity": alert.entity,
                "detail": dict(alert.detail),
            })
            await self._append(self.ALERTS_STREAM, "raised", {
                "monitor": alert.monitor, "severity": alert.severity, "key": alert.key,
                "message": alert.message, "channel": delivery.channel, "reason": delivery.reason,
                "reopened": delivery.reopened, "entity": alert.entity,
            })
            if delivery.channel == "digest":
                if self._digest is not None:
                    self._digest.hold(alert)
            else:
                await self._send_alert(cause, delivery)

        for alert in resolved:
            await self._publish(cause, topics.REFLECT_ALERT_CLEARED, {
                "monitor": alert.monitor, "key": alert.key, "message": alert.message,
                "entity": alert.entity,
            })
            await self._append(self.ALERTS_STREAM, "cleared", {
                "monitor": alert.monitor, "key": alert.key, "entity": alert.entity,
            })

        await self._maybe_send_digest(cause)

    async def _send_alert(self, cause: Message, delivery) -> None:
        alert = delivery.alert
        prefix = "REGRESSED: " if delivery.reopened else ""
        subject = f"{prefix}{alert.severity}: {alert.monitor}"
        body = alert.message
        if alert.entity:
            body = f"{body}\n\n({alert.entity})"
        await self._propose_notify(cause, subject=subject, body=body,
                                    rationale=f"{alert.severity} alert from the {alert.monitor} monitor")

    async def _maybe_send_digest(self, cause: Message) -> None:
        if not self.config.digest_enabled or self._digest is None or self._router is None:
            return
        if not self._digest.due():
            return
        body = self._digest.render(
            monitor_failures=dict(self._monitors.failures),
            suppressed=self._router.take_suppressed(),
        )
        # `sent()` regardless of whether anything went out: a day with
        # nothing to report is a day the digest is done with, and not
        # marking it would re-render an empty digest on every tick.
        self._digest.sent()
        if not body:
            return
        await self._propose_notify(cause, subject="Simorgh daily digest", body=body,
                                    rationale="the daily digest")

    async def _propose_notify(self, cause: Message, *, subject: str, body: str, rationale: str) -> None:
        import uuid

        await self._publish(cause, topics.ACTION_PROPOSED, {
            "action_id": str(uuid.uuid4()),
            "tool": "notify",
            "args": {"subject": subject, "body": body},
            "scope": {"paths": [], "network": True},
            "reversibility": "irreversible",
            "rationale": rationale,
            "proposed_by": self._ctx.source if self._ctx is not None else "reflection",
        })

    def _drain_ad_hoc(self) -> dict:
        """Ad-hoc alerts grouped by monitor name.

        Grouped because `AlertRouter.observe` takes one monitor's
        *complete* view -- handing it a partial list would resolve
        every other alert that monitor has open.
        """
        grouped: dict[str, list] = {}
        for alert in self._ad_hoc:
            grouped.setdefault(alert.monitor, []).append(alert)
        self._ad_hoc = []
        for name in grouped:
            # An ad-hoc source has no "current view", so anything it
            # already had open stays open and is re-stated here.
            existing = {a.key: a for a in self._router.open_for(name)} if self._router else {}
            for alert in grouped[name]:
                existing[alert.key] = alert
            grouped[name] = list(existing.values())
        return grouped

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
