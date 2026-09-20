# planning -- contract

One-line status: layer 3 · 3,078 lines · 20 test files · lock: `planning` in docs/modules/locks.toml

## Purpose

Planning owns the task queue: every task's lifecycle as an event-sourced `task:<id>` Ledger stream, the in-memory `TaskIndex` projection rebuilt from those streams (plus a `planning:index` snapshot), intake from goals, curiosity candidates, reflection patterns and research follow-ups (fuzzy-deduped and bounded), offering ready work (`task.available`), granting exactly one claim per task with a lease, retries, the dependency DAG, project decomposition through Plan Mode (propose, review, approve or ask a human), and re-grounding stale project children. It never runs a task, never calls a tool and never proposes an action: Orchestration's Worker claims and runs, and Planning only records outcomes it is told about. Every status change goes through the legal-transition table (`model.py:139-169`); an illegal one raises, and since a raise inside a bus handler is swallowed, handlers route around illegal steps explicitly (for example `available -> blocked -> failed` for a cancel). The shaping decision is that the Ledger stream is the truth and the index is a projection updated in the same call as each append, with claims made exclusive by compare-and-swap on the stream's sequence (`store.py:312-333`).

## Files

| File | For |
|---|---|
| `simorgh/planning/__init__.py` | re-exports `Service` |
| `simorgh/planning/api.py` | internal protocols (`TaskStoreProtocol`, `DependencyGraphProtocol`) |
| `simorgh/planning/bridge.py` | `BusCognitionCaller`: `cognition.think` with a timeout, `None` on no answer |
| `simorgh/planning/config.py` | `[planning]` dataclass (plus `SIMORGH_PLANNING_LEASE_SECONDS`) |
| `simorgh/planning/dag.py` | dependency validation (unknown id, cycle), dependents, readiness |
| `simorgh/planning/decomposer.py` | `parse_steps` (numbered-list regex) and `decompose` via `purpose="decompose"` |
| `simorgh/planning/dedupe.py` | `difflib` fuzzy duplicate test (threshold 0.45) |
| `simorgh/planning/intake.py` | maps goals, candidates, patterns and follow-ups to tasks; dedupe and backlog bound |
| `simorgh/planning/model.py` | `Task`, `Scope`, `Step`, `Lease`, statuses, kinds, origins, the transition table |
| `simorgh/planning/planmode.py` | `PlanState`, the approval matrix, plan diff, human-approval timeout |
| `simorgh/planning/reground.py` | staleness rule and the `STILL_VALID` check via `purpose="reground"` |
| `simorgh/planning/rollup.py` | project status as a pure function of children; stalled detection |
| `simorgh/planning/scheduler.py` | ready-task ranking, `task.available` offers (once per generation), lease scan |
| `simorgh/planning/service.py` | the bus subsystem: every handler, ticks, pause, plan mode, DAG propagation |
| `simorgh/planning/store.py` | `TaskStore` and `TaskIndex`: appends, CAS claim, leases, snapshot, rebuild, forget-all |

## Consumes

Authority: the handler table in `service.py:157-183`. `Service.consumes` (`service.py:49-72`) omits two of them, `task.cancel` and `task.clear.request`; see Known issues.

| Topic | Schema | Where | Does |
|---|---|---|---|
| `intent.goal.stated` | `messages/intent.py::IntentGoalStated` | simorgh/planning/service.py | intake a goal (project if `wants_project`); duplicate -> debug notice |
| `curiosity.candidate` | `messages/curiosity.py::CuriosityCandidate` | simorgh/planning/service.py | intake a candidate task, deduped, deferred when the backlog is full |
| `task.create` | `messages/task.py::TaskCreate` | simorgh/planning/service.py | create a task (or project); preempt a lower-priority running task for a human; reply only if `reply_to` |
| `task.claim` | `messages/task.py::TaskClaim` | simorgh/planning/service.py | CAS claim with a lease; with `accept_better`, may hand back a better ready task |
| `task.list.request` | `messages/task.py::TaskListRequest` | simorgh/planning/service.py | reply tasks (filtered) and project rollups |
| `task.work_next.request` | `messages/task.py::TaskWorkNextRequest` | simorgh/planning/service.py | reply the next ready task id, or a reason |
| `task.started` | `messages/task.py::TaskStarted` | simorgh/planning/service.py | `claimed -> in_progress` |
| `task.step` | `messages/task.py::TaskStep` | simorgh/planning/service.py | refresh the lease |
| `task.lease_heartbeat` | `messages/task.py::TaskLeaseHeartbeat` | simorgh/planning/service.py | refresh the lease (mid-step) |
| `task.paused` | `messages/task.py::TaskPaused` | simorgh/planning/service.py | park the task as `paused` |
| `task.completed` | `messages/task.py::TaskCompleted` | simorgh/planning/service.py | mark completed, propagate to dependents, maybe finish the project; for a plan-mode project, read the plan artifact instead |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/planning/service.py | terminal: fail and block the downstream closure; otherwise retry-or-block |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/planning/service.py | a worker's blocked outcome (own echoes ignored): retry-or-block |
| `task.cancel` | `messages/task.py::TaskCancel` | simorgh/planning/service.py | requeue (preemption), remember for the worker, or end the task |
| `task.clear.request` | `messages/task.py::TaskClearRequest` | simorgh/planning/service.py | cancel running tasks, forget every record, snapshot; reply if asked |
| `plan.reviewed` | `messages/plan.py::PlanReviewed` | simorgh/planning/service.py | approval matrix: approve, ask a human, replan (bounded) or reject |
| `ui.prompt.answered` | `messages/ui.py::UiPromptAnswered` | simorgh/planning/service.py | a human's yes/no on a plan approval prompt |
| `research.finding.recorded` | `messages/research.py::ResearchFindingRecorded` | simorgh/planning/service.py | intake a research task's `follow_up` |
| `reflect.patterns.found` | `messages/reflect.py::ReflectPatternsFound` | simorgh/planning/service.py | intake a task per pattern |
| `reflect.drift.detected` | `messages/reflect.py::ReflectDriftDetected` | simorgh/planning/service.py | flag the project for re-grounding, publish `plan.revised`, re-ground available siblings |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | simorgh/planning/service.py | remember the subject (last 50) as a re-grounding "change since" |
| `system.tick.second` | `messages/system.py::SystemTickSecond` | simorgh/planning/service.py | lease scan, cancelled-after-expiry, blocked retries, approval timeouts, dispatch; backlog metrics every 30 s |
| `system.tick.idle` | `messages/system.py::SystemTickIdle` | simorgh/planning/service.py | dispatch ready work |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | simorgh/planning/service.py | pause/resume the scheduler, honour `autonomous_paused`, requeue paused tasks on resume |

Requests it makes: `cognition.think` (`purpose="decompose"` on replan, `purpose="reground"`) through `bridge.py`, timeout `think_timeout_s`; reads a plan artifact blob from the Ledger (`service.py:1088-1090`).

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `task.created` | `messages/task.py::TaskCreated` | simorgh/planning/service.py | every new task, including each project child |
| `task.create.reply` | `messages/task.py::TaskCreateReply` | simorgh/planning/service.py | reply to a `task.create` request: id, or `deferred`, or `deduplicated_against`, plus `held` |
| `task.available` | `messages/task.py::TaskAvailable` | simorgh/planning/scheduler.py | top 5 ready tasks, each once per `{id}:{updated_at}` generation, not while paused |
| `task.claim.reply` | `messages/task.py::TaskClaimReply` | simorgh/planning/service.py | reply to every claim: `granted`, lease and task, or a reason |
| `task.list.reply` | `messages/task.py::TaskListReply` | simorgh/planning/service.py | reply to `task.list.request` |
| `task.work_next.reply` | `messages/task.py::TaskWorkNextReply` | simorgh/planning/service.py | reply to `task.work_next.request` |
| `task.clear.reply` | `messages/task.py::TaskClearReply` | simorgh/planning/service.py | reply to `task.clear.request` when it has `reply_to` |
| `task.cleared` | `messages/task.py::TaskCleared` | simorgh/planning/service.py | after every clear |
| `task.cancel` | `messages/task.py::TaskCancel` | simorgh/planning/service.py | preempting for a human task (`requeue: true`), and for running tasks on clear |
| `task.blocked` | `messages/task.py::TaskBlocked` | simorgh/planning/service.py | a retry is scheduled, with `retry_after` |
| `task.failed` | `messages/task.py::TaskFailed` | simorgh/planning/service.py | terminal: retries exhausted, repeated rejected answer, cancel, or cancelled-and-expired |
| `task.dependency.satisfied` | `messages/task.py::TaskDependencySatisfied` | simorgh/planning/service.py | per dependent when a task completes (audit only; allow-listed) |
| `plan.proposed` | `messages/plan.py::PlanProposed` | simorgh/planning/service.py | a plan-mode project yielded steps, and again after each revision |
| `plan.revised` | `messages/plan.py::PlanRevised` | simorgh/planning/service.py | a replan produced new steps, a drift was flagged, or a child was superseded after re-grounding |
| `plan.approved` | `messages/plan.py::PlanApproved` | simorgh/planning/service.py | children created, the project task completed |
| `project.completed` | `messages/plan.py::ProjectCompleted` | simorgh/planning/service.py | once per project, when the child rollup is completed |
| `project.failed` | `messages/plan.py::ProjectFailed` | simorgh/planning/service.py | once per project, when the child rollup is failed |
| `ui.prompt` | `messages/ui.py::UiPrompt` | simorgh/planning/service.py | a plan above `auto_approve_max_risk` needs a human yes/no |
| `ui.notice` | `messages/ui.py::UiNotice` | simorgh/planning/service.py | duplicates, empty plans, rejections, approval timeouts |
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/planning/service.py | every 30 s: backlog and counts by status |
| `cognition.think` | `messages/cognition.py::CognitionThink` | simorgh/planning/bridge.py | request, for replan and re-grounding |

`task.cancel` and `task.cleared` are published but not in `Service.produces` (the publish direction is not pinned by any test).

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `task:<id>` | simorgh/planning/store.py:211 | written also by orchestration (the Worker appends `task.step` events); read by interface, orchestration (resume, progress), verification, learning, benchmark | forever (no `task:` entry in DEFAULT_RETENTION) |
| `planning:index` (snapshot key, not an event stream) | simorgh/planning/store.py:178 | - | snapshot, rewritten every 500 events and on clear |

Not streams: `plan:{id}`, `project:{id}` and `task:{id}` in `service.py` are bus partition keys; `dependency_failed:` is a note prefix (`model.py:34`). Nothing writes a `plan:` stream, although `planmode.py`'s docstring says the plan is recorded there (see Known issues).

## Config

`[planning]` in simorgh.toml; dataclass in `simorgh/planning/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `lease_seconds` | `600.0` | yes |
| `max_task_attempts` | `3` | NO (declared, never read) |
| `max_backlog` | `40` | yes |
| `max_blocked_retries` | `9` | yes |
| `blocked_retry_delay_seconds` | `300.0` | yes |
| `continuation_delay_seconds` | `10.0` | yes |
| `dedupe_similarity_threshold` | `0.45` | yes |
| `project_step_count` | `4` | yes |
| `source_roots` | `('simorgh/',)` | yes |
| `max_plan_revisions` | `2` | yes |
| `auto_approve_max_risk` | `'medium'` | yes |
| `human_approval_timeout_seconds` | `3600.0` | yes |
| `regrounding_age_seconds` | `21600.0` | yes |
| `reground_after_sibling_failure` | `True` | yes |
| `stalled_after_seconds` | `1800.0` | yes |
| `autonomous_origins` | `('curiosity', 'reflection', 'research', 'project', 'assistan` | yes |
| `priority_weights` | `field(default_factory=lambda: {'human': 3, 'project': 3, 'be` | yes |
| `leader` | `True` | NO (declared, never read) |
| `think_timeout_s` | `200.0` | yes |

`max_task_attempts` and `leader` are listed in `kernel/configcheck.py:147` `KNOWN_DEAD_FIELDS`. `SIMORGH_PLANNING_LEASE_SECONDS` overrides `lease_seconds` (`config.py`, `from_mapping`).

## Public Python surface

- `simorgh.planning.Service` (name `planning`, `VERSION = "0.1.0"`): constructed by `kernel/registry.py:133` with no arguments.
- `simorgh.planning.config.Config`: imported by `kernel/configcheck.py:223`.
- Nothing else is imported from outside the package; `Task` and the status names are not in `simorgh/contracts` (other packages see task payloads only). The reason prefixes `step budget exhausted`, `verification failed`, `finished with uncommitted changes` (`service.py`, bottom) are a string contract with `orchestration/session.py` that neither side can import.
- Module-level state: `scheduler.DEFAULT_PRIORITY_WEIGHTS` is a mutable dict built from `Config()` at import; it is exported but the Service never reads it (it passes `config.priority_weights`), so mutating it changes nothing. No other singletons. Per-instance state lost at restart: `_plans`, `_plan_by_task`, `_prompt_to_plan` (every plan in review or awaiting a human), `_cancel_requested`, `_last_blocked_answer`, drift and sibling-failure flags, `_recent_self_patches`.

## Invariants

- A plan is typed (stage 7 item 3, 2026-09-19): `decomposer.parse_plan` reads the planner's JSON `{nodes: [...]}` against `contracts/messages/plan.py::PLAN_NODE` -- kinds patch, skill, research, action, question, wait; acceptance criteria per node (carried into `Step.why`); edges by node id, refused by name when they point at nothing. An unreadable plan says what was wrong instead of producing nothing, which is how 21 projects sat at 0/0 steps. The line format stays as the fallback.
- A waiting task holds no worker (stage 7 item 5, 2026-09-19): `task.waiting{until|event}` parks it as `WAITING` and drops its lease; it returns to `AVAILABLE` when the moment passes (checked on the per-second tick), when the named topic is heard (Planning subscribes to it once), or on `task.wake`. `WAITING` is distinct from `PENDING` (waiting on another task) and from `BLOCKED` (an outcome): a waiting task is going fine and is simply not due yet.

- Only `planning` may publish `plan.proposed` (`contracts/topics.py` PUBLISH_ONLY_BY). No other policy entry names planning.
- Every status change is legal under `_TRANSITIONS` (`model.py:139-169`); a repeat of the current status is a no-op. `completed` and `failed` have no exits: a finished task is never offered, claimed or run again.
- A completion that arrives after the lease expired (task back at `available` or `claimed`) is still recorded as completed.
- At most one claimant holds a task: `claim` appends with `expected_seq` and a conflict re-reads the stream and refuses.
- An expired lease returns a non-terminal, non-paused task to `available`; a paused task is never reopened by lease expiry; a task cancelled while held ends as failed when its lease expires.
- A ready task is offered on the second tick without waiting for idle, and each (task, `updated_at`) generation is offered at most once.
- A human-origin task is never deferred by the backlog bound; autonomous origins are deferred at `max_backlog` waiting tasks. A new human task preempts (requeues, never fails) the lowest-priority running task.
- Intake dedupes against every known description regardless of status.
- A blocked task comes back only after its retry delay (`continuation_delay_seconds` for continuation, verification and uncommitted reasons; otherwise `blocked_retry_delay_seconds`); after `max_blocked_retries` attempts, or when a verification-blocked retry repeats the same answer, it fails terminally.
- A terminal failure blocks the whole downstream closure; project status is always computed from children, never stored; `project.completed`/`failed` fires once per project.
- A plan with no parseable steps sends the project back to `available` with a notice; replans are bounded by `max_plan_revisions`; an unanswered human approval pauses the project after `human_approval_timeout_seconds`.
- A re-grounding non-answer is never treated as drift: only a clear `no` supersedes a child.
- `tasks clear` forgets every record and the forgetting survives a restart; the streams themselves remain.
- While the system is paused nothing is offered; while `autonomous_paused`, tasks of `autonomous_origins` are not offered.
- In `single` mode a lease found at boot belonged to a dead process and is released at once (`_release_dead_leases`), so a restart resumes a task without waiting out `lease_seconds`. In `local-multi` it stands.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract planning`.

- `tests/simorgh/planning/test_store.py` -- `TaskStore`: appends, CAS claim, leases, rebuild from streams and snapshot.
- `tests/simorgh/planning/test_model_dag_rollup.py` -- the transition table, DAG validation and readiness, project rollup.
- `tests/simorgh/planning/test_completed_tasks_stay_completed.py` -- an expired lease never resurrects a completed task.
- `tests/simorgh/planning/test_a_completion_after_the_lease_expired_is_not_lost.py` -- a late completion is recorded, not re-run.
- `tests/simorgh/planning/test_task_create_reply.py` -- `task.create` works as a request and as fire-and-forget.
- `tests/simorgh/planning/test_project_decomposition.py` -- `parse_steps` keeps only steps under the live source roots, and the plan scaffold's format is what the parser reads.
- `tests/simorgh/planning/test_decomposer_dedupe_planmode.py` -- the plan approval matrix, the human-approval timeout predicate, the dedupe threshold.
- `tests/simorgh/planning/test_the_backlog_is_offered_without_an_idle_tick.py` -- ready work is offered on the second tick, once per generation.

## Known issues (2026-09-18 evaluation)

- C1 -- Planning subscribes to `learn.self_patch.applied`, which the real landing path never published. **Fixed 2026-09-18** (`1e486f1`: `_land` publishes it).
- L9 -- consumer groups, claim RPC, leases and heartbeats for one in-process worker (Planning's claim and lease half, Orchestration's worker half). Open; stage 4 item 10 puts the lease protocol behind a flag.
- W7 -- `task.dependency.satisfied` has no subscriber; allow-listed as an audit event (`b5c2671`).
- Evaluation section 9.2 (not a catalogue id): a decomposed project has never produced a child that ran to completion; decomposition is a numbered-list regex (`decomposer.py::parse_steps`), and projects have no waiting states. Stage 7.
- Plans under review or waiting for a person were held in memory only and lost on restart. Fixed 2026-09-19: every change is appended to `planning:plans` and replayed at start, prompt mapping included (`test_plans_survive_a_restart.py`).

## Planned changes (roadmap)

- Stage 4 item 10: the lease protocol behind a flag (`workers=1` skips claims and heartbeats); the code stays for multi-worker.
- Stage 6 item 2: Planning runs a node whose task type has a low Self Model posterior in plan mode with a human gate.
- Stage 7 item 3: a typed `Plan{nodes: [{id, kind, subject, acceptance, depends_on, agent}]}` in `contracts/messages/plan.py`, produced by a planner agent as JSON; `parse_steps` retired.
- Stage 7 item 4: projects await children by event and mark a node done only when its child completed and its acceptance was verified.
- Stage 7 item 5: a WAITING state (`task.waiting{until | event | human}`, `task.wake`, `task.answer`) that holds no worker.
- Stage 7 item 6: two consecutive `drifting` checkpoint verdicts re-plan the subtree; `reground.py` becomes a structured subtree revision.
- Stage 7 item 9: standing intents as `wait{event}` nodes (with `worldmodel`).
- This file is to be updated when stage 7 lands.

## Working on this module

Lock it first (`python tools/modlock.py claim planning --by <you> --task "..."`), commit the lock, edit only `simorgh/planning/`, `tests/simorgh/planning/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py planning` before committing; commit subject `planning: <what changed>`.

- Leases in single mode (stage 4 item 10, 2026-09-19): a renewal on `task.step` or `task.lease_heartbeat` updates the in-memory lease only (`TaskStore.refresh_lease(durable=False)`); no `lease_refreshed` event is written, because a restart releases every lease it finds. `local-multi`/`aws` still write them. Claims still happen: they are how a task changes hands.
