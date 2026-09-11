"""Planning as a `Subsystem` (spec section 5): wiring for every consumed
message, the background tick loops, Plan Mode, re-grounding, and DAG
propagation. Layer 2 (registry.py).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Context, Health
from simorgh.contracts.registry import error_reply_payload

from . import dag, planmode, reground
from .bridge import BusCognitionCaller
from .config import Config
from .decomposer import decompose, parse_steps
from .intake import Intake
from .model import (
    DEPENDENCY_FAILED_NOTE,
    AVAILABLE,
    BLOCKED,
    CLAIMED,
    COMPLETED,
    FAILED,
    IN_PROGRESS,
    PAUSED,
    PENDING,
    TERMINAL_STATUSES,
    Scope,
    Task,
)
from .rollup import is_stalled, project_status
from .scheduler import Scheduler
from .store import TaskStore

NAME = "planning"
VERSION = "0.1.0"

_SECOND_TICK_COUNTER_KEY = "n"


class Service:
    name = NAME
    version = VERSION
    consumes: tuple[str, ...] = (
        topics.INTENT_GOAL_STATED,
        topics.CURIOSITY_CANDIDATE,
        topics.TASK_CREATE,
        topics.TASK_CLAIM,
        topics.TASK_LIST_REQUEST,
        topics.TASK_WORK_NEXT_REQUEST,
        topics.TASK_STARTED,
        topics.TASK_STEP,
        topics.TASK_LEASE_HEARTBEAT,
        topics.TASK_PAUSED,
        topics.TASK_COMPLETED,
        topics.TASK_FAILED,
        topics.TASK_BLOCKED,
        topics.PLAN_REVIEWED,
        topics.UI_PROMPT_ANSWERED,
        topics.RESEARCH_FINDING_RECORDED,
        topics.REFLECT_PATTERNS_FOUND,
        topics.REFLECT_DRIFT_DETECTED,
        topics.LEARN_SELF_PATCH_APPLIED,
        topics.SYSTEM_TICK_SECOND,
        topics.SYSTEM_TICK_IDLE,
        topics.SYSTEM_STATE_CHANGED,
    )
    produces: tuple[str, ...] = (
        topics.TASK_CREATE_REPLY,
        topics.TASK_CREATED,
        topics.TASK_AVAILABLE,
        topics.TASK_CLAIM_REPLY,
        topics.TASK_LIST_REPLY,
        topics.TASK_WORK_NEXT_REPLY,
        topics.TASK_DEPENDENCY_SATISFIED,
        topics.TASK_FAILED,
        topics.TASK_BLOCKED,
        topics.PLAN_PROPOSED,
        topics.PLAN_APPROVED,
        topics.PLAN_REVISED,
        topics.PROJECT_COMPLETED,
        topics.PROJECT_FAILED,
        topics.UI_PROMPT,
        topics.UI_NOTICE,
        topics.SYSTEM_HEALTH,
        topics.SYSTEM_METRICS,
)

    def __init__(self, config: Config | None = None) -> None:
        self._config_from_caller = config
        self.config = config or Config()
        self._ctx: Context | None = None
        self._subs: list = []
        self._store: TaskStore | None = None
        self._intake: Intake | None = None
        self._scheduler: Scheduler | None = None
        self._cognition: BusCognitionCaller | None = None
        # Plan-mode state, keyed by plan_id -- see planmode.PlanState. Not
        # in the Ledger as independent state; rebuilt lazily on demand
        # from the plan:<id> stream would be step 9's remaining work
        # (documented in the spec's own open questions / README).
        self._plans: dict[str, planmode.PlanState] = {}
        self._plan_by_task: dict[str, str] = {}
        self._prompt_to_plan: dict[str, str] = {}
        self._project_completed_emitted: set[str] = set()
        self._tick_n = 0
        # Re-grounding (spec section 5.5): per-project flags consulted by
        # `_maybe_reground_then_available` right before a PENDING child
        # would otherwise become `available` un-checked.
        self._project_sibling_failed: dict[str, bool] = {}
        self._project_drift_flagged: dict[str, str] = {}
        # `learn.self_patch.applied` subjects, most recent last, bounded --
        # part of `changes_since` (spec 5.5: "learn.self_patch.applied
        # subjects touching the child's subject").
        self._recent_self_patches: list[tuple[str, float]] = []
        # The answer each blocked task last offered, so a retry that
        # reproduces it can be stopped instead of run again. In memory
        # rather than on the Task: it only ever decides whether to spend
        # the NEXT attempt, and `attempts` -- which is persisted -- still
        # bounds the task after a restart.
        self._last_blocked_answer: dict[str, str] = {}

    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        # Live-caught as a class 2026-09-08: every service is handed its
        # own `[section]` from simorgh.toml (`kernel/context.py` builds
        # `ctx.config` for exactly this) and eleven of them never read
        # it. The settings existed, were documented, were parsed into a
        # Config dataclass with a `from_mapping` -- and nothing ever
        # called it, so changing the file changed nothing. The dominant
        # bug shape in this codebase: a designed slot with one side
        # implemented and nobody writing to it.
        #
        # A config passed by the caller still wins, so a test that
        # constructs the service with one is unaffected.
        if self._config_from_caller is None and ctx.config:
            self.config = Config.from_mapping(dict(ctx.config))
        self._store = TaskStore(ctx.ledger, ctx.clock)
        await self._store.rebuild()
        self._intake = Intake(self._store, dedupe_threshold=self.config.dedupe_similarity_threshold,
                              max_backlog=self.config.max_backlog,
                              autonomous_origins=tuple(self.config.autonomous_origins))
        self._scheduler = Scheduler(
            self._store, ctx.bus, ctx.clock, source=ctx.source,
            priority_weights=self.config.priority_weights, lease_seconds=self.config.lease_seconds,
            autonomous_origins=self.config.autonomous_origins,
        )
        self._cognition = BusCognitionCaller(
            ctx.bus, ctx.clock, source=ctx.source, timeout=self.config.think_timeout_s,
        )

        handlers = {
            topics.INTENT_GOAL_STATED: self._on_goal_stated,
            topics.CURIOSITY_CANDIDATE: self._on_candidate,
            topics.TASK_CREATE: self._on_task_create,
            topics.TASK_CLAIM: self._on_task_claim,
            topics.TASK_LIST_REQUEST: self._on_task_list,
            topics.TASK_WORK_NEXT_REQUEST: self._on_work_next,
            topics.TASK_STARTED: self._on_task_started,
            topics.TASK_STEP: self._on_task_step,
            topics.TASK_LEASE_HEARTBEAT: self._on_task_lease_heartbeat,
            topics.TASK_PAUSED: self._on_task_paused,
            topics.TASK_COMPLETED: self._on_task_completed,
            topics.TASK_FAILED: self._on_task_failed,
            topics.TASK_BLOCKED: self._on_task_blocked,
            topics.TASK_CANCEL: self._on_task_cancel,
            topics.PLAN_REVIEWED: self._on_plan_reviewed,
            topics.UI_PROMPT_ANSWERED: self._on_prompt_answered,
            topics.RESEARCH_FINDING_RECORDED: self._on_research_finding,
            topics.REFLECT_PATTERNS_FOUND: self._on_patterns_found,
            topics.REFLECT_DRIFT_DETECTED: self._on_drift_detected,
            topics.LEARN_SELF_PATCH_APPLIED: self._on_self_patch_applied,
            topics.SYSTEM_TICK_SECOND: self._on_tick_second,
            topics.SYSTEM_TICK_IDLE: self._on_tick_idle,
            topics.SYSTEM_STATE_CHANGED: self._on_state_changed,
        }
        self._subs = [await ctx.bus.subscribe(t, h) for t, h in handlers.items()]
        ctx.logger.info("planning.started", tasks=len(self._store.index.tasks))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs = []

    async def health(self) -> Health:
        if self._ctx is None or self._store is None:
            return Health.down("not started")
        return Health.ok()

    # -- intake ---------------------------------------------------------------------

    async def _on_goal_stated(self, message: Message) -> None:
        p = message.payload
        result = await self._intake.on_goal_stated(
            goal=p["goal"], origin=p["origin"], wants_project=p.get("wants_project", False),
            priority=p.get("priority", 0),
        )
        if result.task is not None:
            await self._announce_created(result.task)
        else:
            await self._notice("debug", f"duplicate goal, matches task {result.duplicate_of}")

    async def _on_candidate(self, message: Message) -> None:
        p = message.payload
        result = await self._intake.on_candidate(
            kind=p["kind"], description=p["description"], subject=p.get("subject"), area=p.get("area", ""),
        )
        if result.task is not None:
            await self._announce_created(result.task)
        else:
            await self._notice("debug", f"duplicate candidate, matches task {result.duplicate_of}")

    async def _on_task_create(self, message: Message) -> None:
        p = message.payload
        result = await self._intake.on_candidate(
            kind=p["kind"], description=p["description"], subject=p.get("subject"), area="",
            origin=p.get("origin", "human"), risk=p.get("risk"), max_steps=p.get("max_steps"),
        ) if p["kind"] != "project" else await self._intake.on_goal_stated(
            goal=p["description"], origin=p.get("origin", "human"), wants_project=True, risk=p.get("risk"),
            max_steps=p.get("max_steps"),
        )
        if result.task is not None:
            await self._announce_created(result.task)
            await self._preempt_for(result.task)
            payload = {"task_id": result.task.id, "backlog": result.backlog}
        elif result.deferred:
            self._ctx.logger.info("planning.candidate_deferred", origin=p.get("origin", "curiosity"),
                                  reason=result.deferred)
            payload = {"task_id": None, "deferred": result.deferred}
        else:
            payload = {"task_id": result.duplicate_of, "deduplicated_against": result.duplicate_of}
        # `task.create` is legitimately used both ways: as a request, by
        # the Interface's commands and by `start_task`, which want the
        # id back; and fire-and-forget, by Reflection's distillation and
        # by Benchmark, which are announcing work rather than asking for
        # a receipt. Replying unconditionally raised
        # "task.create (...) is not a request: no reply_to" out of the
        # bus handler for every one of the second kind -- the task WAS
        # created, so the only casualty was a traceback in the middle of
        # the screen and a dead-lettered message. Caught live 2026-09-09
        # when Reflection distilled a finished build into a skill.
        if message.reply_to:
            await self._ctx.bus.reply(message, type=topics.TASK_CREATE_REPLY, payload=payload)

    async def _on_patterns_found(self, message: Message) -> None:
        created = await self._intake.on_patterns_found(patterns=message.payload.get("patterns", []))
        for task in created:
            await self._announce_created(task)

    async def _on_research_finding(self, message: Message) -> None:
        follow_up = message.payload.get("follow_up")
        if not follow_up:
            return
        task = await self._intake.on_research_follow_up(
            research_task_id=message.payload["task_id"], subject=follow_up["subject"],
            description=follow_up["description"],
        )
        if task is not None:
            await self._announce_created(task)

    async def _announce_created(self, task: Task) -> None:
        payload = {
            "task_id": task.id, "kind": task.kind, "description": task.description,
            "description_ref": task.description_ref,
            "depends_on": list(task.depends_on), "mode": task.mode, "origin": task.origin,
            "risk": task.risk, "subject": task.subject, "parent_id": task.parent_id,
            "scope": task.scope.to_payload() if task.scope else None,
        }
        if task.max_steps:
            payload["max_steps"] = task.max_steps
        await self._ctx.bus.publish(Message.new(
            topics.TASK_CREATED, source=self._ctx.source,
            partition_key=f"task:{task.id}", payload=payload,
        ))
        # Live-caught by the CLI end-to-end test, 2026-09-07: nothing
        # dispatched a task at the moment it became ready. The only caller
        # of `dispatch_ready` was `_on_tick_idle`, and the Kernel's idle
        # tick needs `idle_threshold_s` (10s) of *no percepts* first --
        # and every line the human types is a percept that resets it. So a
        # task typed at the REPL sat unclaimed for at least ten seconds,
        # and a person who kept typing could starve their own work
        # indefinitely. Dispatch is idempotent (keyed on
        # `{task.id}:{task.updated_at}`), so this is a no-op when the idle
        # tick later notices the same still-available task.
        if self._scheduler is not None:
            await self._scheduler.dispatch_ready()

    # -- claiming / lifecycle ---------------------------------------------------------

    async def _on_task_claim(self, message: Message) -> None:
        p = message.payload
        result = await self._store.claim(p["task_id"], p["worker_id"], self.config.lease_seconds)
        payload = {"granted": result.granted}
        if result.granted:
            payload["lease_until"] = result.lease_until
            payload["task"] = _task_payload(result.task)
        else:
            payload["reason"] = result.reason
        await self._ctx.bus.reply(message, type=topics.TASK_CLAIM_REPLY, payload=payload)

    async def _on_task_started(self, message: Message) -> None:
        task_id = message.payload["task_id"]
        task = await self._store.get(task_id)
        if task is not None and task.status == "claimed":
            await self._store.transition(task_id, IN_PROGRESS)

    async def _on_task_step(self, message: Message) -> None:
        await self._store.refresh_lease(message.payload["task_id"], self.config.lease_seconds)

    # Same renewal, fired mid-step by `Worker`'s heartbeat loop rather
    # than on step completion -- see `topics.TASK_LEASE_HEARTBEAT`.
    _on_task_lease_heartbeat = _on_task_step

    async def _on_task_paused(self, message: Message) -> None:
        p = message.payload
        task = await self._store.get(p["task_id"])
        if task is not None and task.status in ("claimed", IN_PROGRESS):
            await self._store.transition(p["task_id"], PAUSED, note=p.get("reason", ""))

    async def _on_task_completed(self, message: Message) -> None:
        p = message.payload
        task_id = p["task_id"]
        task = await self._store.get(task_id)
        if task is None:
            return
        if task.kind == "project" and task.mode == "plan":
            await self._on_plan_worker_result(task, p.get("artifacts") or [])
            return
        if task.status != COMPLETED:
            await self._store.transition(task_id, COMPLETED, note=p.get("result_summary", ""))
        await self._propagate_completion(task_id)
        await self._maybe_finish_project(task.parent_id)

    async def _on_task_failed(self, message: Message) -> None:
        p = message.payload
        task_id, terminal = p["task_id"], p.get("terminal", False)
        task = await self._store.get(task_id)
        if task is None:
            return
        if terminal:
            if task.status != FAILED:
                await self._store.transition(task_id, FAILED, note=p.get("reason", ""))
            self._mark_sibling_failure(task)
            await self._propagate_failure(task_id)
            await self._maybe_finish_project(task.parent_id)
            return
        await self._retry_or_block(task, p.get("reason", ""))

    async def _preempt_for(self, task: Task) -> None:
        """Give a human's task the worker, if a lesser one is holding it.

        `select_ready` ranks the QUEUE (`human: 3, reflection: 2,
        curiosity: 1`), which decides nothing at all once the single
        worker is already busy: there is no preemption, so a curiosity
        task that claimed the worker keeps it to the end of its budget
        and a human task created a second later simply waits.

        Live-caught by an observer judging the CLI as a user
        (2026-09-08), and it was the worst moment in their session:
        they typed `improve <file> <description>`, got a task id, and
        never saw that id again for three and a half minutes while the
        screen filled with a curiosity task editing a different file
        that they had not asked for.

        The autonomous task is REQUEUED, not failed. It was real work,
        nobody rejected it, and it goes back to the queue to be picked
        up when the human's task is done. Only one is displaced per
        arrival, and only ever by a human.
        """
        if task.origin != "human":
            return
        weight = self._scheduler._priority_weights  # noqa: SLF001
        mine = weight.get("human", 3)
        running = [
            t for t in self._store.index.tasks.values()
            if t.status == IN_PROGRESS and weight.get(t.origin, 0) < mine
        ]
        if not running:
            return
        # The least important, and among equals the one that is ACTUALLY
        # RUNNING -- the most recently active, since a session writes a
        # `task.step` per step and that moves `updated_at`.
        #
        # This used to take the oldest instead, reasoning that it had
        # had the most of the worker already. That is exactly backwards:
        # the oldest `in_progress` record is the one that STOPPED being
        # worked, a stale row left by a crash or an expiry. An observer
        # watched it free such a record while the task genuinely holding
        # the worker ran on for another 92 seconds, with the human's own
        # task sitting `available` the whole time (2026-09-08). It
        # preempted a record, not a worker.
        victim = max(running, key=lambda t: (-weight.get(t.origin, 0), t.updated_at))
        reason = f"preempted by a human task ({task.id[:8]})"
        await self._ctx.bus.publish(Message.new(
            topics.TASK_CANCEL, source=self._ctx.source, partition_key=f"task:{victim.id}",
            payload={"task_id": victim.id, "reason": reason, "requeue": True},
        ))

    async def _on_task_cancel(self, message: Message) -> None:
        """Stop a task nobody is waiting for any more.

        Both halves are needed. The Worker stops its session at the next
        step boundary, which frees the worker; this frees the *record*,
        because a task left in_progress keeps its lease, and an expiring
        lease puts it straight back on the available queue to be run
        again -- the resurrection loop of 2026-09-07.

        A worker still finishing its current step will report the same
        task failed a moment later. That is a duplicate transition, which
        the store already treats as a no-op.
        """
        task_id = message.payload.get("task_id", "")
        reason = message.payload.get("reason") or "cancelled"
        task = await self._store.get(task_id) if task_id else None
        if task is None or task.status in TERMINAL_STATUSES:
            return
        if message.payload.get("requeue"):
            # Preemption, not rejection: the work was real and nobody
            # judged it, so it goes back to the queue rather than into a
            # terminal state. `expire_lease` is what frees the worker's
            # hold and returns it to AVAILABLE.
            await self._store.expire_lease(task_id)
            return
        if task.status in (IN_PROGRESS, CLAIMED):
            # A worker has it. Let the worker end it: it stops at its
            # next step boundary and reports the outcome itself, which
            # is also when the tree is actually clean again. Ending the
            # record here announced "failed" up to a step BEFORE the
            # work had stopped and the edit had been discarded, and the
            # human then saw two different failure lines for one task
            # (observer, 2026-09-08). A worker that never reports is
            # covered by lease expiry, as it always was.
            return
        # `available -> failed` and `pending -> failed` are not legal
        # transitions, so cancelling a task that had not started yet
        # raised, was swallowed by the bus, and left the task on the
        # queue -- where a worker then claimed it and killed it at step
        # zero. BLOCKED is the legal way through, and it is also the
        # honest description: the task is parked, and cancelling is a
        # reason for parking it.
        if task.status in (AVAILABLE, PENDING):
            await self._store.transition(task_id, BLOCKED, note=reason)
        await self._store.transition(task_id, FAILED, note=reason)
        await self._ctx.bus.publish(Message.new(
            topics.TASK_FAILED, source=self._ctx.source,
            partition_key=f"task:{task_id}",
            payload={"task_id": task_id, "reason": reason, "terminal": True, "attempts": task.attempts},
        ))

    async def _on_task_blocked(self, message: Message) -> None:
        # `_retry_or_block` publishes task.blocked itself, on the same
        # topic a Worker reports a blocked outcome on, and this handler
        # heard that echo as a fresh outcome: block -> publish -> hear
        # -> block ..., 466 "blocked" lines on screen from one task
        # before the kernel shut down (watched trial, 2026-09-07). An
        # echo of our own, or a task already parked, is not an outcome.
        if message.source == self._ctx.source:
            return
        p = message.payload
        task = await self._store.get(p["task_id"])
        if task is None or task.status in (BLOCKED, FAILED):
            return
        await self._retry_or_block(task, p.get("reason", ""),
                                   answer=str(p.get("result_summary") or ""))

    def _made_no_progress(self, task: Task, answer: str, reason: str) -> bool:
        """True when this attempt ended with the answer the last one was
        blocked for.

        A retry is worth running because the next attempt can be
        different -- it carries the objection, the kept edits and the
        memory of what was tried. When it comes back with the same
        answer anyway, the same reviewer will make the same objection,
        and every further attempt is the same round trip again.

        Measured on a GAIA run, 2026-09-10: 18 tasks were retried, 8 of
        them re-produced an identical answer, and retrying past the
        first repeat never once turned a wrong answer into a right one.
        Meanwhile the retries took 68% of the run's steps.

        Only a block that judged the ANSWER can count. A task blocked
        for running out of steps, or for finishing with uncommitted
        changes, carries its answer forward unchanged by design -- and
        for the first hours of this rule that counted as "no progress",
        so a patch task that had applied and tested a correct change
        was killed terminally on the second uncommitted block, with the
        work sitting in the tree and a note blaming the answer for
        repeating itself (observer, 2026-09-10, caught the same day the
        rule landed)."""
        if not reason.startswith(VERIFICATION_REASON):
            return False
        stripped = " ".join(answer.split())
        if not stripped:
            # An outcome with no answer says nothing about repetition,
            # and must not erase what the last real one said.
            return False
        seen = self._last_blocked_answer.get(task.id)
        self._last_blocked_answer[task.id] = stripped
        return stripped == seen

    async def _retry_or_block(self, task: Task, reason: str, *, answer: str = "") -> None:
        if self._made_no_progress(task, answer, reason):
            note = (f"stopped after {task.attempts + 1} attempts: the retry produced the same "
                    f"answer that was already rejected ({reason})")
            # `available -> failed` and `pending -> failed` are illegal,
            # and an outcome can arrive for a task the queue has already
            # taken back. Raising here would be swallowed by the bus and
            # leave the task cycling forever -- the exact shape that made
            # a cancelled task loop in 2026-09-07. BLOCKED is the legal
            # way through and is also true: it is parked before it ends.
            if task.status in (AVAILABLE, PENDING):
                await self._store.transition(task.id, BLOCKED, note=note)
            await self._store.transition(task.id, FAILED, attempt=True, note=note)
            self._mark_sibling_failure(task)
            await self._ctx.bus.publish(Message.new(
                topics.TASK_FAILED, source=self._ctx.source,
                partition_key=f"task:{task.id}",
                payload={"task_id": task.id, "terminal": True, "attempts": task.attempts + 1,
                         "result_summary": answer,
                         "reason": f"{reason} -- and the retry produced the same answer again, "
                                   f"so a further attempt would repeat it"},
            ))
            await self._propagate_failure(task.id)
            await self._maybe_finish_project(task.parent_id)
            return
        if task.attempts + 1 >= self.config.max_blocked_retries:
            await self._store.transition(
                task.id, FAILED, note=f"gave up after {task.attempts + 1} attempts: {reason}", attempt=True,
            )
            self._mark_sibling_failure(task)
            await self._ctx.bus.publish(Message.new(
                topics.TASK_FAILED, source=self._ctx.source,
                partition_key=f"task:{task.id}",
                payload={"task_id": task.id, "reason": reason, "terminal": True, "attempts": task.attempts + 1},
            ))
            await self._propagate_failure(task.id)
            await self._maybe_finish_project(task.parent_id)
            return
        await self._store.transition(task.id, BLOCKED, note=reason, attempt=True)
        await self._ctx.bus.publish(Message.new(
            topics.TASK_BLOCKED, source=self._ctx.source,
            partition_key=f"task:{task.id}",
            payload={"task_id": task.id, "reason": reason, "retry_after": self._retry_delay(reason)},
        ))

    def _retry_delay(self, reason: str) -> float:
        """A task that ran out of steps mid-work, or that a verification
        check objected to (edit and objection both kept for the next
        attempt, `orchestration/session.py::_continues`), is a
        continuation, not a task blocked on something outside itself: it
        comes back in seconds, with a fresh budget and a memory of the
        attempt (orchestration/resume.py), rather than in five minutes.
        Before this, a checklist rejection over a trivial, one-attempt
        fixable slip (e.g. a self-consistency mistake in the model's own
        answer) still paid the full five-minute delay every time --
        dominating a project's wall-clock time far more than any amount
        of test-suite speedup could (observer, 2026-09-08)."""
        if reason.startswith((CONTINUATION_REASON, VERIFICATION_REASON, UNCOMMITTED_REASON)):
            return self.config.continuation_delay_seconds
        return self.config.blocked_retry_delay_seconds

    async def _propagate_completion(self, task_id: str) -> None:
        for dep_id in dag.dependents_of(task_id, self._store.index.tasks):
            dependent = self._store.index.tasks.get(dep_id)
            if dependent is None:
                continue
            await self._store.record_dependency_event(dep_id, satisfied_by=task_id, failed_by=None)
            await self._ctx.bus.publish(Message.new(
                topics.TASK_DEPENDENCY_SATISFIED, source=self._ctx.source,
                partition_key=f"task:{dep_id}", payload={"task_id": dep_id, "satisfied_by": task_id},
            ))
            if dependent.status == PENDING and dag.is_ready(dependent, self._store.index.tasks):
                await self._maybe_reground_then_available(dependent)

    async def _propagate_failure(self, task_id: str) -> None:
        """Blocks every downstream task, not just the failed task's
        immediate dependents. `dag.dependents_of` is one hop; a chain
        A -> B -> C (C depends only on B, not directly on A) needs a walk
        over the whole downstream closure, or C -- whose only dependency
        just went BLOCKED and will now never complete -- is left PENDING
        forever with `dag.is_ready` perpetually false and nothing ever
        transitioning it out. Live-reproduced with a real Kernel
        (observer, 2026-09-08): A failed terminally, B correctly went
        BLOCKED, and C sat PENDING with no note and no further event,
        indistinguishable from a task legitimately still waiting on live
        work. BFS rather than recursion: a diamond that re-converges
        (C depends on both A and B) must not be visited, and blocked,
        twice."""
        queue = [task_id]
        seen = {task_id}
        while queue:
            failed_id = queue.pop(0)
            for dep_id in dag.dependents_of(failed_id, self._store.index.tasks):
                if dep_id in seen:
                    continue
                seen.add(dep_id)
                dependent = self._store.index.tasks.get(dep_id)
                if dependent is None or dependent.status in (COMPLETED, FAILED):
                    continue
                await self._store.record_dependency_event(dep_id, satisfied_by=None, failed_by=failed_id)
                if dependent.status != BLOCKED:
                    await self._store.transition(
                        dep_id, BLOCKED, note=f"{DEPENDENCY_FAILED_NOTE}{failed_id}")
                # This dependent is now BLOCKED and will never COMPLETE,
                # so anything depending on IT must be blocked too --
                # queue it for the same treatment.
                queue.append(dep_id)

    # -- re-grounding (spec section 5.5) ---------------------------------------------

    def _mark_sibling_failure(self, task: Task) -> None:
        if task.parent_id is not None:
            self._project_sibling_failed[task.parent_id] = True

    async def _maybe_reground_then_available(self, task: Task) -> None:
        """Before making a stale child `available` (spec section 5.5):
        `reground.needs_check` is true if the child is older than
        `regrounding_age_seconds`, a sibling has failed terminally since
        the plan was approved, or (this build's extension of the same
        knob) Reflection has flagged the project as drifting
        (`_on_drift_detected`) -- closes harness-06 gap #3, "no drift/
        re-grounding check across a multi-tick PROJECT_TASK." A clear
        `no` verdict replaces the child; anything else (yes, or no clear
        verdict -- a non-answer is never evidence of drift, `01` section
        4.5) proceeds to `available` exactly as before this check
        existed."""
        project_id = task.parent_id
        if project_id is None:
            await self._store.transition(task.id, AVAILABLE)
            return
        sibling_failed = self.config.reground_after_sibling_failure and (
            self._project_sibling_failed.get(project_id, False)
            or project_id in self._project_drift_flagged
        )
        if not reground.needs_check(
            task, now=self._ctx.clock.now(),
            regrounding_age_seconds=self.config.regrounding_age_seconds,
            sibling_failed_since=sibling_failed,
        ):
            await self._store.transition(task.id, AVAILABLE)
            return
        project = await self._store.get(project_id)
        if project is None or self._cognition is None:
            await self._store.transition(task.id, AVAILABLE)
            return
        still_valid, reason = await reground.check(
            self._cognition, goal=project.description, child=task,
            why=self._why_for_child(project_id, task), changes_since=self._changes_since(project_id, task),
        )
        await self._store.record_regrounded(task.id, still_valid=still_valid, reason=reason)
        if still_valid is False:
            await self._supersede_with_replacement(task, project_id, reason)
            return
        await self._store.transition(task.id, AVAILABLE)

    def _why_for_child(self, project_id: str, task: Task) -> str:
        """The plan-mode Step's recorded `why`, looked up by matching the
        child's description back to the in-memory `PlanState` (spec 5.1's
        "record of why each step is there"). `self._plans` is process-
        lifetime only (see its own field comment); falling back to the
        task's own `note` is an honest degrade, not a crash, once that
        state is gone (e.g. after a restart)."""
        plan_id = self._plan_by_task.get(project_id)
        state = self._plans.get(plan_id) if plan_id else None
        if state is not None:
            for step in state.steps:
                if step.description == task.description:
                    return step.why
        return task.note

    def _changes_since(self, project_id: str, task: Task) -> list[str]:
        """Spec 5.5's `changes_since`: sibling outcomes plus
        `learn.self_patch.applied` subjects touching the child's
        `subject`."""
        changes: list[str] = []
        for sibling in self._store.children(project_id):
            if sibling.id == task.id:
                continue
            if sibling.status == FAILED:
                suffix = f" ({sibling.note})" if sibling.note else ""
                changes.append(f"sibling step failed: {sibling.description}{suffix}")
            elif sibling.status == COMPLETED:
                changes.append(f"sibling step completed: {sibling.description}")
        if task.subject:
            for subject, _ts in self._recent_self_patches:
                if subject and (subject in task.subject or task.subject in subject):
                    changes.append(f"self-patch applied touching {subject}")
        return changes

    async def _supersede_with_replacement(self, task: Task, project_id: str, reason: str) -> None:
        """A `no` re-grounding verdict: the old child is `failed{reason:
        superseded}`, never mutated, and a replacement child is created
        in its place (spec 5.5). Known simplification, noted rather than
        hidden: any *other* task that already depends on `task.id` keeps
        pointing at the now-failed original rather than being re-pointed
        at the replacement -- re-wiring the DAG's `depends_on` edges
        after the fact is a larger change than this pass's scope; such a
        dependent will see `dependency_failed` and go `blocked`, same as
        any other upstream failure, rather than silently picking up the
        revised step."""
        note = f"superseded by re-grounding: {reason}" if reason else "superseded by re-grounding"
        # `_maybe_reground_then_available`'s only caller reaches `task`
        # while it is still PENDING (about to become `available`), and
        # PENDING has no direct legal transition to FAILED (`model.py`'s
        # `_TRANSITIONS`) -- only via BLOCKED, the same intermediate step
        # `_propagate_failure` already uses for a PENDING dependent whose
        # upstream failed.
        await self._store.transition(task.id, BLOCKED, note=note)
        await self._store.transition(task.id, FAILED, note=note)
        # `origin="project"` -- same as every other plan-approved child
        # (`_approve_plan`); `model.py`'s `ORIGINS` tuple has a "planner"
        # value the wire contract's `TASK_ORIGIN` enum (`contracts/
        # messages/task.py`) does not, so anything that reaches
        # `task.created` on the bus must stay within the wire enum.
        replacement = await self._store.create(
            kind=task.kind, description=reason or task.description, subject=task.subject, origin="project",
            parent_id=project_id, depends_on=task.depends_on, mode="execute", risk=task.risk,
            scope=task.scope, initial_status=AVAILABLE,
        )
        await self._announce_created(replacement)
        plan_id = self._plan_by_task.get(project_id, "")
        await self._ctx.bus.publish(Message.new(
            topics.PLAN_REVISED, source=self._ctx.source,
            partition_key=f"plan:{plan_id}" if plan_id else None,
            payload={
                "plan_id": plan_id,
                "reason": reason or f"re-grounding found {task.id} no longer serves the goal",
                "diff": {"added": [replacement.id], "removed": [task.id], "reordered": []},
            },
        ))

    async def _on_drift_detected(self, message: Message) -> None:
        """Reflection's `reflect.drift.detected`: flags the drifting
        task's project so its remaining PENDING siblings are re-grounded
        before they next become available (see `_maybe_reground_then_
        available`), and records the drift itself as a `plan.revised`
        with a real reason -- closes harness-06 gap #3, "no drift/
        re-grounding check across a multi-tick PROJECT_TASK."

        `reflect.drift.detected` is only ever computed at the drifting
        task's own terminal transition (reflection/service.py's module
        docstring), which means it always races the *same*
        `task.completed`/`task.failed`/`task.blocked` message Planning's
        own `_on_task_completed`/`_on_task_failed` react to. Reflection's
        side needs a real `cognition.think(purpose="review")` round trip
        before it can publish; Planning's dependency-satisfied path
        (`_propagate_completion` -> `_maybe_reground_then_available`)
        needs no such round trip and reacts to the identical message
        essentially synchronously. Live-reproduced 2026-09-08 (this
        session): a dependent that becomes ready in the very same
        propagation as the task whose *own* drift is what's being
        reported had, 5/5 runs, already been transitioned to `available`
        by the time this handler ran -- flagging the project here was
        always too late to protect it, silently defeating this feature
        for the single most natural trigger (a task's own drift review
        firing at its own completion). `_reground_available_children`
        below closes that gap by re-running the same check against any
        *other* child that is already `available` but not yet claimed --
        the drifting task itself is excluded (it may itself still be
        `available`, e.g. when `reflect.drift.detected` is raised for a
        task still in flight rather than at its own terminal transition,
        and re-grounding a task against its own drift finding is not
        what this closes)."""
        p = message.payload
        task_id = p.get("task_id")
        if not task_id:
            return
        task = await self._store.get(task_id)
        if task is None or task.parent_id is None:
            return
        project_id = task.parent_id
        reason = f"drift detected on {task_id} ({p.get('kind', '')}): {p.get('evidence', '')}"
        self._project_drift_flagged[project_id] = reason
        plan_id = self._plan_by_task.get(project_id, "")
        await self._ctx.bus.publish(Message.new(
            topics.PLAN_REVISED, source=self._ctx.source,
            partition_key=f"plan:{plan_id}" if plan_id else None,
            payload={"plan_id": plan_id, "reason": reason, "diff": {"added": [], "removed": [], "reordered": []}},
        ))
        await self._reground_available_children(project_id, exclude_task_id=task_id)

    async def _reground_available_children(self, project_id: str, *, exclude_task_id: str) -> None:
        """Catches up any child of `project_id` (other than
        `exclude_task_id`, the task whose drift this was raised for)
        that reached `available` before this drift flag landed (see
        `_on_drift_detected`'s docstring for why that race is the
        common case, not an edge case). Only `available`-and-unclaimed
        children are touched: one already `claimed`/`in_progress` is
        already being worked, and re-grounding it out from under a
        worker is a larger change than this race fix's scope."""
        project = await self._store.get(project_id)
        if project is None or self._cognition is None:
            return
        for child in self._store.children(project_id):
            if child.id == exclude_task_id or child.status != AVAILABLE:
                continue
            still_valid, reason = await reground.check(
                self._cognition, goal=project.description, child=child,
                why=self._why_for_child(project_id, child), changes_since=self._changes_since(project_id, child),
            )
            await self._store.record_regrounded(child.id, still_valid=still_valid, reason=reason)
            if still_valid is False:
                await self._supersede_with_replacement(child, project_id, reason)

    async def _on_self_patch_applied(self, message: Message) -> None:
        subject = message.payload.get("subject")
        if not subject:
            return
        self._recent_self_patches.append((subject, message.ts))
        self._recent_self_patches = self._recent_self_patches[-50:]

    async def _maybe_finish_project(self, project_id: str | None) -> None:
        if project_id is None or project_id in self._project_completed_emitted:
            return
        children = self._store.children(project_id)
        if not children:
            return
        status = project_status(children)
        if status not in (COMPLETED, FAILED):
            return
        self._project_completed_emitted.add(project_id)
        done = sum(1 for c in children if c.status == COMPLETED)
        topic = topics.PROJECT_COMPLETED if status == COMPLETED else topics.PROJECT_FAILED
        await self._ctx.bus.publish(Message.new(
            topic, source=self._ctx.source, partition_key=f"project:{project_id}",
            payload={"project_id": project_id, "done": done, "total": len(children),
                     "summary": f"{done}/{len(children)} steps completed"},
        ))

    # -- ticks / pause ------------------------------------------------------------

    async def _on_tick_idle(self, message: Message) -> None:
        if self._scheduler is not None:
            await self._scheduler.dispatch_ready()

    async def _on_tick_second(self, message: Message) -> None:
        self._tick_n += 1
        if self._scheduler is not None:
            await self._scheduler.scan_leases()
        await self._reconsider_blocked()
        await self._reconsider_awaiting_human()
        # A ready task used to be offered in exactly two places: the
        # moment it was created (`_announce_created`), and the IDLE
        # tick -- which only fires after `idle_threshold_s` (10s) of
        # nobody typing. Every other way a task becomes ready published
        # nothing at all: a blocked retry (`_reconsider_blocked`, right
        # above), a lease expiry (`Scheduler.scan_leases`), a dependency
        # satisfied by a parent completing, a resume after a pause. And
        # `dispatch_ready` offers only the top 5, so the 6th task of any
        # burst was never offered either.
        #
        # Measured 2026-09-10 (20 human tasks, 3 workers, 0.05s of work
        # each): with nobody typing, 6 ran in the first 0.3s and the
        # other 14 took 16 seconds of pure waiting, in batches of 5
        # spaced by the idle threshold and its 3s cooldown. With a
        # human typing every 2 seconds -- what ordinary chat use looks
        # like -- the idle tick never fired at all and **13 of the 20
        # tasks were never offered to anybody** in 40 seconds, with
        # three workers idle throughout and all 13 sitting in
        # `available`.
        #
        # This tick already runs every second and already scans leases,
        # and `dispatch_ready`'s emission key (`{id}:{updated_at}`)
        # makes a re-offer within one generation a deduped no-op -- so
        # this costs at most five deduped messages a second and closes
        # every one of those paths at once. It runs last so a task made
        # ready by the two calls above is offered on the same tick.
        if self._scheduler is not None:
            await self._scheduler.dispatch_ready()
        # `status` read a counter `planning.backlog` that NOTHING has
        # ever published, so it reported "backlog: 0" with three tasks
        # live -- and said so in the same breath as a chat reply that
        # correctly counted them (observer, 2026-09-08). Same
        # unconnected wire as `memory.records`. Every 30s, like Memory.
        if self._tick_n % 30 == 0:
            await self._publish_backlog()

    async def _publish_backlog(self) -> None:
        counts: dict[str, int] = {}
        for task in self._store.index.tasks.values():
            counts[task.status] = counts.get(task.status, 0) + 1
        waiting = sum(counts.get(status, 0) for status in (PENDING, AVAILABLE, BLOCKED))
        await self._ctx.bus.publish(Message.new(
            topics.SYSTEM_METRICS, source=self._ctx.source,
            payload={"subsystem": "planning", "counters": {},
                     "gauges": {"backlog": waiting, "by_status": counts}},
        ))

    async def _reconsider_blocked(self) -> None:
        now = self._ctx.clock.now()
        for task in list(self._store.index.tasks.values()):
            if task.status != BLOCKED:
                continue
            if (now - task.updated_at) < self._retry_delay(task.note):
                continue
            if task.attempts >= self.config.max_blocked_retries:
                await self._store.transition(
                    task.id, FAILED, note=f"gave up after {task.attempts} attempts: {task.note}",
                )
                continue
            await self._store.transition(task.id, AVAILABLE, note=f"retrying after being blocked: {task.note}")

    async def _on_state_changed(self, message: Message) -> None:
        state = message.payload.get("state")
        if self._scheduler is not None:
            self._scheduler.paused = state in ("paused", "stopping", "stopped")
            # `system.state.changed` has always carried this; nothing
            # read it. A scoped autonomous pause leaves `state` at
            # "running", so without this the scheduler kept offering
            # curiosity/reflection work after `auto off`.
            self._scheduler.autonomous_paused = bool(message.payload.get("autonomous_paused"))

    # -- reads ----------------------------------------------------------------------

    async def _on_task_list(self, message: Message) -> None:
        f = message.payload.get("filter") or {}
        tasks = self._store.all()
        if f.get("status"):
            tasks = [t for t in tasks if t.status == f["status"]]
        if f.get("kind"):
            tasks = [t for t in tasks if t.kind == f["kind"]]
        if f.get("parent_id"):
            tasks = [t for t in tasks if t.parent_id == f["parent_id"]]
        projects = []
        for t in self._store.all():
            if t.kind != "project":
                continue
            children = self._store.children(t.id)
            projects.append({
                "project_id": t.id, "rollup": project_status(children),
                "done": sum(1 for c in children if c.status == COMPLETED), "total": len(children),
                "stalled": is_stalled(children, now=self._ctx.clock.now(), stalled_after_seconds=self.config.stalled_after_seconds),
            })
        await self._ctx.bus.reply(message, type=topics.TASK_LIST_REPLY, payload={
            "tasks": [_task_payload(t) for t in tasks], "projects": projects,
        })

    async def _on_work_next(self, message: Message) -> None:
        ready = self._store.ready(limit=1)
        if not ready:
            await self._ctx.bus.reply(message, type=topics.TASK_WORK_NEXT_REPLY,
                                       payload={"reason": "nothing pending"})
            return
        await self._ctx.bus.reply(message, type=topics.TASK_WORK_NEXT_REPLY, payload={"task_id": ready[0].id})

    # -- plan mode --------------------------------------------------------------------

    async def _on_plan_worker_result(self, task: Task, artifacts: list[str]) -> None:
        text = ""
        if artifacts:
            try:
                raw = await self._ctx.ledger.get_blob(artifacts[0])
                data = json.loads(raw.decode("utf-8"))
                text = data.get("steps_text", "") if isinstance(data, dict) else ""
            except Exception:  # noqa: BLE001 -- a malformed artifact must not crash Planning
                text = ""
        steps = parse_steps(text, self.config.project_step_count, self.config.source_roots) if text else []
        if not steps:
            # `in_progress -> pending` is not a legal transition, so this
            # raised `ValueError` unconditionally and the bus swallowed
            # it: a plan whose text yields no steps froze the project
            # silently, exactly like the lease bug below (observer,
            # 2026-09-08). `available` is the honest destination -- the
            # work is not done and something should pick it up again --
            # and a notice says so rather than leaving it to be guessed.
            await self._store.transition(
                task.id, AVAILABLE, note="decomposition produced no real steps -- will retry",
            )
            await self._notice("warning", f"project {task.id}: the plan produced no usable steps; retrying")
            return
        plan_id = uuid.uuid4().hex[:12]
        state = planmode.PlanState(plan_id=plan_id, task_id=task.id, goal=task.description, steps=steps, risk=task.risk)
        self._plans[plan_id] = state
        self._plan_by_task[task.id] = plan_id
        # The plan-mode Worker's own lease was for exploring, not for the
        # review-plus-possible-human-decision window that starts now; left
        # alone it would keep counting down from whenever `task.step` last
        # refreshed it and could expire mid-review, which flips the
        # project task straight back to `available` (TaskStore.expire_lease
        # bypasses the transition table) -- i.e. a second Worker could claim
        # and re-run plan mode while the first plan is still pending a
        # decision. Extending it to cover the full approval-timeout budget
        # keeps the task un-reclaimable for exactly as long as this plan
        # is genuinely still being decided.
        await self._store.refresh_lease(task.id, self.config.human_approval_timeout_seconds)
        await self._ctx.bus.publish(Message.new(
            topics.PLAN_PROPOSED, source=self._ctx.source,
            partition_key=f"plan:{plan_id}",
            payload={
                "plan_id": plan_id, "task_id": task.id, "goal": task.description, "risk": task.risk,
                "estimated_cost": 0.0,
                "steps": [
                    {"step_id": s.step_id, "kind": s.kind, "description": s.description,
                     "depends_on": list(s.depends_on), "why": s.why, "subject": s.subject}
                    for s in steps
                ],
            },
        ))

    async def _on_plan_reviewed(self, message: Message) -> None:
        p = message.payload
        state = self._plans.get(p["plan_id"])
        if state is None:
            return
        if state.status in planmode.RESOLVED_STATUSES:
            return  # duplicate/late `plan.reviewed` for a plan already decided -- a no-op (spec section 8)
        decision = planmode.approval_decision(p["verdict"], state.risk, self.config.auto_approve_max_risk)
        if decision == "reject":
            state.status = planmode.REJECTED
            await self._store.transition(state.task_id, FAILED, note="plan rejected")
            await self._notice("info", f"plan {state.plan_id} rejected")
            return
        if decision == "auto_approve":
            await self._approve_plan(state, approved_by="auto")
            return
        if decision == "ask_human":
            prompt_id = uuid.uuid4().hex[:12]
            state.prompt_id = prompt_id
            state.status = planmode.AWAITING_HUMAN
            state.prompt_asked_at = self._ctx.clock.now()
            self._prompt_to_plan[prompt_id] = state.plan_id
            await self._ctx.bus.publish(Message.new(
                topics.UI_PROMPT, source=self._ctx.source,
                payload={"prompt_id": prompt_id, "question": f"Approve plan for {state.goal!r}?",
                         "options": ["yes", "no"], "timeout_s": self.config.human_approval_timeout_seconds,
                         "default": "no"},
            ))
            return
        # replan
        if state.revisions >= self.config.max_plan_revisions:
            state.status = planmode.REJECTED
            await self._store.transition(state.task_id, FAILED, note=f"plan rejected after {state.revisions} revisions")
            return
        new_steps = await decompose(self._cognition, state.goal + f"\n\nReviewer feedback: {p.get('feedback', '')}",
                                     [], self.config.project_step_count)
        state.revisions += 1
        if not new_steps:
            # This used to `return` silently, leaving the project
            # `in_progress` on a lease just extended to an hour -- frozen,
            # and invisible. Found by a watched trial 2026-09-07: every
            # replan came back empty (the 8s think timeout), and every
            # project stopped here forever. A failed revision is a real
            # outcome; count it and say so.
            await self._notice("warning", f"plan {state.plan_id}: revision {state.revisions} produced no steps")
            if state.revisions >= self.config.max_plan_revisions:
                state.status = planmode.REJECTED
                await self._store.transition(
                    state.task_id, FAILED, note=f"plan rejected: {state.revisions} revisions produced no steps",
                )
            return
        diff = planmode.compute_diff(state.steps, new_steps)
        state.steps = new_steps
        await self._ctx.bus.publish(Message.new(
            topics.PLAN_REVISED, source=self._ctx.source,
            partition_key=f"plan:{state.plan_id}",
            payload={"plan_id": state.plan_id, "reason": p.get("feedback", "revision requested"), "diff": diff},
        ))
        # A revised plan has to go back through the gate, or the revise
        # path can never terminate: nothing but Reflection listened for
        # `plan.revised`, so a successful revision produced no children
        # either. Re-propose it with the new steps.
        await self._ctx.bus.publish(Message.new(
            topics.PLAN_PROPOSED, source=self._ctx.source,
            partition_key=f"plan:{state.plan_id}",
            payload={
                "plan_id": state.plan_id, "task_id": state.task_id, "goal": state.goal, "risk": state.risk,
                "estimated_cost": 0.0,
                "steps": [
                    {"step_id": s.step_id, "kind": s.kind, "description": s.description,
                     "depends_on": list(s.depends_on), "why": s.why, "subject": s.subject}
                    for s in new_steps
                ],
            },
        ))

    async def _on_prompt_answered(self, message: Message) -> None:
        plan_id = self._prompt_to_plan.get(message.payload["prompt_id"])
        if plan_id is None:
            return
        state = self._plans.get(plan_id)
        if state is None:
            return
        if state.status != planmode.AWAITING_HUMAN:
            # Either a duplicate answer, or this plan already timed out and
            # its task was paused (see `_reconsider_awaiting_human`) -- a
            # late "yes" must not try to approve a paused task (PAUSED has
            # no legal transition straight to COMPLETED) or re-reject an
            # already-resolved one.
            return
        if message.payload["answer"] == "yes":
            await self._approve_plan(state, approved_by="human")
        else:
            state.status = planmode.REJECTED
            await self._store.transition(state.task_id, FAILED, note="plan rejected by human")

    async def _reconsider_awaiting_human(self) -> None:
        """Spec section 5.4: an unanswered human-approval prompt must not
        hang the project forever -- past `human_approval_timeout_seconds`
        the task is paused with a reason instead, closing the same
        never-hang guarantee Guardian-down/Verification-absent already get
        (`04-build-plan-and-roadmap.md` section 5, graceful degradation)."""
        now = self._ctx.clock.now()
        for state in list(self._plans.values()):
            if not planmode.is_human_approval_timed_out(
                state, now=now, timeout_seconds=self.config.human_approval_timeout_seconds
            ):
                continue
            state.status = planmode.TIMED_OUT
            task = await self._store.get(state.task_id)
            if task is not None and task.status not in (COMPLETED, FAILED, PAUSED):
                await self._store.transition(
                    state.task_id, PAUSED,
                    note=f"plan {state.plan_id} awaiting human approval timed out after "
                         f"{self.config.human_approval_timeout_seconds}s",
                )
            await self._notice(
                "warn",
                f"plan {state.plan_id} timed out waiting for a human approval answer; "
                f"task {state.task_id} paused",
            )

    async def _approve_plan(self, state: planmode.PlanState, *, approved_by: str) -> None:
        state.status = planmode.APPROVED
        children_ids: list[str] = []
        id_by_step = {}
        for step in state.steps:
            deps = tuple(id_by_step.get(d, d) for d in step.depends_on)
            child = await self._store.create(
                kind=step.kind, description=step.description, subject=step.subject, origin="project",
                parent_id=state.task_id, depends_on=deps, mode="execute", risk="low",
                scope=Scope(paths=(step.subject,), network=step.kind == "research") if step.subject else None,
                initial_status=PENDING if deps else AVAILABLE,
            )
            id_by_step[step.step_id] = child.id
            children_ids.append(child.id)
            await self._announce_created(child)
        await self._store.transition(state.task_id, COMPLETED, note="project decomposed")
        await self._ctx.bus.publish(Message.new(
            topics.PLAN_APPROVED, source=self._ctx.source,
            partition_key=f"plan:{state.plan_id}",
            payload={"plan_id": state.plan_id, "approved_by": approved_by, "children": children_ids},
        ))

    # -- helpers ----------------------------------------------------------------------

    async def _notice(self, level: str, text: str) -> None:
        await self._ctx.bus.publish(Message.new(
            topics.UI_NOTICE, source=self._ctx.source,
            payload={"level": level, "text": text, "source": self.name},
        ))


# The reasons `orchestration/session.py` gives for an attempt that is
# unfinished rather than wrong -- it ran out of steps, or verification
# objected to something worth another try with the edit and the
# objection still in hand (`Session._continues`, same three prefixes).
# Matched by prefix here because the two packages may not import each
# other.
CONTINUATION_REASON = "step budget exhausted"
VERIFICATION_REASON = "verification failed"
UNCOMMITTED_REASON = "finished with uncommitted changes"


def _task_payload(task: Task) -> dict:
    return {
        "task_id": task.id, "kind": task.kind, "description": task.description,
        # The whole brief, when the description on the wire is a preview.
        # A worker that prompts with the preview is working from a
        # truncated instruction and cannot tell.
        "description_ref": task.description_ref, "subject": task.subject,
        "status": task.status, "mode": task.mode, "risk": task.risk, "origin": task.origin,
        "parent_id": task.parent_id, "depends_on": list(task.depends_on), "attempts": task.attempts,
        "note": task.note, "max_steps": task.max_steps,
    }


__all__ = ["Service", "NAME", "VERSION"]
