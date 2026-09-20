# Stage 7 -- Long horizon: sub-agents, plans, waits, checkpoint critic

Status: **in progress** (2026-09-19: items 2, 5, 7, 9 done; 1 and 8 in part) · Depends on: stages 4 and 6 · Estimated: 3 weeks · Modules touched: orchestration, planning, verification, kernel, contracts, execution

## Outcome

A project is a parent session that spawns in-process child sub-agents per plan step, each with fresh context and its own budget, and awaits them by event. Plans are typed artifacts with acceptance criteria and dependencies, produced by a planner agent definition, not a numbered-list regex. A task can WAIT for a time, an event or a person's answer without holding a worker. A checkpoint critic scores the trajectory against the node's acceptance criteria at every progress note and triggers re-planning after two drifting verdicts. Multi-day goals pause, wake, re-plan and finish.

## Why

Evaluation section 8.1 rows planning and verification; section 9.2 (projects that mark themselves complete when children exist; decomposition depth > 0 has never produced a child that ran to completion; no waiting states; "step budget exhausted" the leading benchmark failure). Unlocks: projects that produce and finish children; drift caught mid-task.

## Before you start

Stage 4's long-task suite (60 scripted turns, kill-and-resume) is the gate; record its numbers. Read `planning/decomposer.py` (`parse_steps`, the numbered-list regex), `planning/model.py`, `planning/service.py` (rollups, the DAG), `orchestration/session.py::_delegate`, `orchestration/api.py::Session`, `verification/` (plan review, trajectory), `kernel/scheduler.py`.

## Action items

Done 2026-09-19 (item 8, in part): `execution/procs.py::run_child` runs a child in its own process group, kills the group on a deadline or a cancel, and keeps the partial output; `run_tests` starts its own session and kills the group on timeout, so `pytest -n`'s workers no longer survive it. Still open: moving `run_container` and the landing gate onto `run_child`, and taking the deadline from the envelope rather than the tool's own timeout.

Done 2026-09-19 (item 9): standing intents are waits. The prompt names the events a task may wait for (`scaffolds.WAITABLE_EVENTS`, each checked against the topic catalogue by a test) and says to wait for the event rather than check in a loop; the scheduler and Planning do the rest, with no model running in between.

Done 2026-09-19 (item 5): WAITING. `task.waiting{until|event}` parks a task and drops its lease; Planning wakes it when the moment passes, when the topic it named is heard, or on `task.wake`. The session's `wait` tool ends the attempt rather than sleeping with a worker and a context in hand. Not done: `human: question_id` waits (the answer path already exists for approvals).

Done 2026-09-19 (item 2): `agents/planner.md`, `agents/verify.md`, `agents/skill-writer.md`, `agents/browser.md`. Each loads and its allowlist is enforced by the same loader as the rest: the verifier is read-only and is not itself verified, and the browser may not enter a password, a code or place an order.

Done 2026-09-19 (item 1, in part): a helper may be any agent (`delegate`/`task` with `{"agent": ...}`), children run as real asyncio tasks under a concurrency cap read from `max_children_concurrent`, and depth still bounds the chain. Still open in item 1: `isolation: fresh|fork`, a child's own `session:<id>` stream separate from its task stream, and the typed `Task` argument shape.

Done 2026-09-19 (item 7): `session.checkpoint` after every successful action that changes something, and `resume.done_actions` reading them back, so a resumed session answers an already-completed call with what it returned rather than repeating it. A read is never checkpointed.

1. **The `Task` built-in.** *Lock `orchestration`.* `Task{agent, brief, isolation: fresh|fork, budget}` spawns a child `Session` on its own `session:<id>` stream, in-process (never via the task queue: the documented single-worker deadlock), depth ≤ `max_depth`, concurrency ≤ `max_children`; summary-only return bounded as a ToolResult; tier escalation on helper failure kept from `_delegate`; `delegate` becomes an alias. Acceptance: a research agent spawning two verify children concurrently, each on its own stream, parent context unchanged.
2. **Agent definitions for the roles.** *Lock `orchestration`, `docs`.* `agents/planner.md`, `agents/verify.md`, `agents/skill-writer.md`, `agents/browser.md` (over `browse_page`'s snapshot-act loop, item 8). Acceptance: each loads and its tool allowlist is enforced.
3. **A typed Plan artifact.** *Lock `planning`, `contracts`.* `Plan{nodes: [{id, kind: patch|research|action|question|wait, subject, acceptance: [str], depends_on: [id], agent}]}` in `contracts/messages/plan.py`, produced by the planner agent as JSON and validated by schema; `parse_steps`'s regex retired; kind `action` scoped to tool families so a household goal decomposes without a repo path. Acceptance: `tests/simorgh/planning/test_plan_artifact.py`: a household goal decomposes into action nodes with acceptance criteria; an invalid plan is rejected with the schema error.
4. **Projects await children by event.** *Lock `planning`, `orchestration`.* A project session spawns a child per ready node via `Task`, subscribes to `task.completed/failed` for its children, and marks a node done only when its child completed and (item 6) its acceptance was verified; the rollup stays a pure function of children. Acceptance: a three-node project with a dependency runs the nodes in order and completes only after the last child; today's "complete when children exist" test is inverted.
5. **WAITING.** *Lock `planning`, `kernel`, `contracts`.* `task.waiting{until | event: topic+filter | human: question_id}`; the Kernel scheduler publishes `task.wake` at `until` or on the matching event; a human's answer arrives as `task.answer` (from the CLI, Telegram or the dashboard); a waiting task holds no worker. Acceptance: a task that waits 10 minutes (fake clock) for a calendar event resumes on `task.wake` with its context; both-sides test updated.
6. **The checkpoint critic.** *Lock `verification`, `orchestration`.* `verify.checkpoint.request/reply`: at every progress note, score the trajectory against the node's acceptance criteria returning `{on_track | drifting | blocked, unmet: [], next}`; two consecutive `drifting` verdicts trigger re-planning of the subtree (planning's `reground.py` becomes a structured subtree revision on the cheap tier); `insufficient_evidence` preserved; majority vote of three cheap samples for the yes/no verdict. Acceptance: a scripted task that wanders is re-planned by the second note.
7. **A checkpoint after every irreversible action.** *Lock `orchestration`.* `session.checkpoint` event after a successful tier-2/3 ToolResult so a crash-resume never repeats it. Acceptance: kill after a `git_commit` and resume: no second commit.
8. **Heavy steps as subprocesses with kill-on-deadline.** *Lock `execution`.* `run_tests`, `run_container`, the landing gate run as subprocesses whose deadline comes from the envelope; cancellation kills the process group. Acceptance: a cancelled task's test run is gone from `ps` within 2 s.
9. **Standing intents.** *Lock `planning`, `worldmodel`.* "Tell me when X" becomes a `wait{event}` node evaluated by the scheduler against `world.home.situation_changed`, never by a model polling. Acceptance: "tell me when the TV turns off" fires once, from the event.
10. **Findings entry** with the long-task suite: resolved rate at ≥ 50 turns, fraction ending in budget exhaustion, projects producing and completing children, wall time for the scripted three-day household goal, resume-after-kill success.

## Measurements after

| Number | Before | Target |
|---|---|---|
| Projects that produce and complete children | 0 | 100% of the suite's projects |
| Long-task suite resolved at ≥ 50 turns | recorded in stage 4 | higher, 3 repeats |
| Cases ending in budget exhaustion | leading failure | under 10% |
| Resume after kill without repeating an irreversible action | recorded | 100% |

## Risks and mitigations

- The single-worker deadlock if any wait goes through the queue: waits are event-driven; the long-run scenario is the gate.
- Critic false positives thrashing re-planning: two consecutive verdicts required; vote of three.
- Worktree landing and checkpoints on retry: bounded by the resume eval.

## Definition of done

- [ ] Items 1-9 with tests; CONTRACT.md for planning, orchestration, verification, kernel updated.
- [ ] Findings entry.
