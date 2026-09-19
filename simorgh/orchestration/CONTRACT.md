# orchestration -- contract

One-line status: layer X · 5,664 lines · 30 test files · lock: `orchestration` in docs/modules/locks.toml

## Purpose

Orchestration owns the agent loop: it claims a task (or takes a conversational percept), runs one `Session` through gather, think, propose, verify, and reports one terminal outcome (`task.completed|failed|blocked|paused` plus `turn.completed`). It owns the per-kind `Profile` table (which tools a session may *request*, step and revision caps, scaffold), the prompt's `task_rules` scaffold, the memory and conversation blocks of every think, and the tree hygiene around code tasks (worktree open, land, close; discard of uncommitted edits). It must never run a tool itself or decide whether one is allowed: every tool call becomes an `action.proposed` and Guardian is the sole authority. The one decision that shapes it: the session is a bus-driven state machine that talks to Cognition, Guardian/Execution, Memory and Verification only by request/reply and correlated events, and records every step on the `task:<id>` ledger stream so a second worker can resume it (`resume.py`).

## Files

| File | For |
|---|---|
| `simorgh/orchestration/__init__.py` | Re-exports `Service` and the `api.py` dataclasses |
| `simorgh/orchestration/api.py` | Package-internal types: `Profile`, `Session`, `Step`, `Budget`, `Outcome` |
| `simorgh/orchestration/claims.py` | `unsupported_claims`: a final answer's claims checked against the step log |
| `simorgh/orchestration/config.py` | `[orchestration]` dataclass |
| `simorgh/orchestration/context.py` | `Assembler`: conversation window, memory block and transcript for one think |
| `simorgh/orchestration/profiles.py` | CHAT, VOICE_CHAT, PATCH, RESEARCH, PLAN, SKILL profiles and their selection |
| `simorgh/orchestration/progress.py` | Progress note used by re-grounding and clean revisions |
| `simorgh/orchestration/resume.py` | Rebuilds a session from its `task:<id>` stream (crash vs retry) |
| `simorgh/orchestration/scaffolds.py` | Renders the `task_rules` block per scaffold, channel and speaker; tool-down notes |
| `simorgh/orchestration/service.py` | The `Service`: starts workers, chat hand-off, tool registry replay, metrics |
| `simorgh/orchestration/session.py` | `SessionRunner`: the step loop, proposals, verify, worktree landing, honesty guards |
| `simorgh/orchestration/tools.py` | Tool policy table and marker-call to `action.proposed` payload router |
| `simorgh/orchestration/worker.py` | `Worker`: claim, lease heartbeat, cancel, terminal reporting, procedural memory |

## Consumes

Subscriptions are exactly `Service.consumes` (`service.py:32-41`, pinned by `tests/simorgh/test_manifests_match_the_code.py`). `action.*` and `verify.result` are subscribed transiently per wait by `_EventWaiter` (`session.py:491`).

| Topic | Schema | Where | Does |
|---|---|---|---|
| `task.available` | `messages/task.py::TaskAvailable` | worker.py:213 | Group `workers`, `max_inflight=1`: sends `task.claim`, builds a Session, runs it |
| `task.cancel` | `messages/task.py::TaskCancel` | worker.py:218, 247 | Remembers the id; the loop stops at the next step boundary (requeue = no report) |
| `system.state.changed` | `messages/system.py::SystemStateChanged` | worker.py:262 | `paused`/`stopping`/`stopped` makes sessions pause between steps |
| `percept.text.received` | `messages/percept.py::PerceptTextReceived` | service.py:266 | Runs an ephemeral chat session off the bus handler, keyed by the percept's `session_id` |
| `tool.registered` | `messages/tool.py::ToolRegistered` | service.py:227 | Adds the tool to the known set and its reversibility to the policy table |
| `tool.probed` | `messages/tool.py::ToolProbed` | service.py:118 | Records a tool as down/up so `task_rules` says so once |
| `action.result` | `messages/action.py::ActionResult` | session.py:1656 | Ends a proposal wait; side effects fill `uncommitted`/`created`/`wrote` |
| `action.denied` | `messages/action.py::ActionDenied` | session.py:1719 | Ends a proposal wait as `denied: <reasons>`; step marked `denied` |
| `action.needs_human` | `messages/action.py::ActionNeedsHuman` | session.py:1656 | Ends a proposal wait as `needs human: <question>` |
| `verify.result` | `messages/verify.py::VerifyResult` | session.py:1760 | Verdict for this attempt's `verification_id`; fail spends a revision |

Replies received by request/reply: `task.claim.reply` (Planning), `cognition.think.reply`, `memory.retrieve.reply`, `world.env.query.reply`.

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `action.proposed` | `messages/action.py::ActionProposed` | session.py:1637 | Every tool call, worktree open/land/close and `git_discard` |
| `cognition.think` | `messages/cognition.py::CognitionThink` | session.py:1246 | Each think (request, `think_timeout_s`), plus progress notes and wrap-up |
| `memory.retrieve` | `messages/memory.py::MemoryRetrieve` | context.py:272-288, 357 | Each think: matched, recent, per-person and working-window recalls (0.25 s) |
| `world.env.query` | `messages/world.py::WorldEnvQuery` | context.py:369 | `Assembler.world_facet` (request) |
| `task.claim` | `messages/task.py::TaskClaim` | worker.py:271 | Request to Planning on every `task.available` |
| `task.lease_heartbeat` | `messages/task.py::TaskLeaseHeartbeat` | worker.py:374 | Every `min(heartbeat_s, lease/3)` while a claimed task runs |
| `task.started` | `messages/task.py::TaskStarted` | session.py:890 | Start of every attempt (also appended to the ledger) |
| `task.step` | `messages/task.py::TaskStep` | session.py:918, 1338, 1943 | Every recorded step, thinking announcements, cognition errors |
| `task.paused` | `messages/task.py::TaskPaused` | session.py:1917 | Session saw the system paused |
| `task.completed` / `task.failed` / `task.blocked` | `messages/task.py` | worker.py:454-492 | Terminal outcome; appended to `task:<id>` then published |
| `turn.completed` | `messages/task.py::TurnCompleted` | worker.py:523 | After every terminal outcome of every kind (Interface/Voice resolve chat by `session_id`; Memory feeds episodic and working memory) |
| `memory.store` | `messages/memory.py::MemoryStore` | worker.py:500 | A procedural record of what a finished task did |
| `verify.requested` | `messages/verify.py::VerifyRequested` | session.py:1751 | A final answer on a profile with `verify=True`; kind always `task` |
| `learn.self_patch.applied` | `messages/learn.py::LearnSelfPatchApplied` | session.py:809 | `_land` succeeded: a worktree branch landed on main |
| `system.metrics` | `messages/system.py::SystemMetrics` | service.py:312 | Every `metrics_interval_s` (worker busy gauges) |

## Ledger streams

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `task:<task_id>` | worker.py:491, session.py:1949 (append); resume.py:112 (read) | planning, verification, learning, reflection, interface, benchmark | forever (no prefix in DEFAULT_RETENTION) |
| `execution:tools` | service.py:21 (read at start to replay registrations) | written by execution | 30d |
| `capabilities` | service.py:22 (read at start to replay probes) | written by execution | forever |

Also written: blobs (`ledger.put_blob`) for the verify subject (`session.py:1905`), plan artifacts (`worker.py:444`) and oversized result text (`worker.py:569`). `person:<name>` and `someone:` in this package are memory tags and room-text markers, not streams.

## Config

`[orchestration]` in simorgh.toml; dataclass in `simorgh/orchestration/config.py`. The live config sets `delegation=true, parallel_read_tools=4, escalate_from_attempt=1` (stage 0 item 12).

| Key | Default | Read in the package |
|---|---|---|
| `workers` | `1` | yes |
| `review_benchmark` | `True` | yes |
| `reground_every_steps` | `0` | yes |
| `keep_recent_steps` | `2` | yes |
| `clean_revisions` | `False` | yes |
| `delegation` | `False` | yes |
| `delegate_max_steps` | `12` | yes |
| `escalate_from_attempt` | `0` | yes |
| `parallel_read_tools` | `1` | yes |
| `skills_enabled` | `True` | yes |
| `skills_catalog_max_chars` | `3000` | yes |
| `skills_roots` | `('skills', '~/.simorgh/skills')` | yes |
| `skills_channels` | `('', 'cli', 'http')` | yes |
| `heartbeat_s` | `30` | yes |
| `max_depth` | `3` | yes (delegation depth) |
| `max_children_concurrent` | `4` | NO (declared, never read) |
| `think_timeout_s` | `200.0` | yes |
| `needs_human_timeout_s` | `600.0` | NO (declared, never read) |
| `worktrees` | `True` | yes |
| `metrics_interval_s` | `3.0` | yes |

There is no `lease_seconds` key: a task's lease is `[planning] lease_seconds`, carried on each `task.available` and read by `worker.py` from the payload. The unread copy here was removed on 2026-09-19, so writing it is now reported by `kernel/configcheck.py` as a section that changed nothing (`test_config.py`).

## Public Python surface

- `simorgh.orchestration.Service` (`service.py:30`): the Subsystem. Built only by the Kernel (`kernel/registry.py:131`, `kernel/service.py:651`); `kernel/configcheck.py` imports `Config`. A `Config` passed to the constructor wins over `ctx.config`.
- `api.py` types (`Profile`, `Session`, `Step`, `Budget`, `Outcome`) are internal: no other package imports them, and nothing here is exported through `simorgh.contracts`. Other packages see only messages.
- Types this package takes from `simorgh.contracts`: `topics`, `envelope.Message/Event`, `protocols.Context/Health`, `settings.conversation_key`, `scratch.SCRATCH_PREFIX/is_scratch`, `pytestfailures.hoist_marker`.
- String constants other packages duplicate by agreement (no import allowed): `CONTINUATION_REASON = "step budget exhausted"` (`session.py:47`, matched by `planning/service.py`), `DENIED_PREFIX = "denied: "` (`session.py:37`).
- Module-level mutable singletons (risks: shared across every Worker and every Kernel in one process, emptied only by `Service.stop`):
  - `tools._TOOL_POLICY`, `tools._DYNAMIC_TOOLS`, `tools._REGISTERED` (`tools.py:29, 559, 569`): the policy table and known-tool set, mutated by `tool.registered`. A hand-written entry wins over an announced one.
  - `scaffolds._UNAVAILABLE` (`scaffolds.py:35`): tools currently probed down.

## Invariants

1. Every tool call a session makes, including `worktree_open`, `worktree_land`, `worktree_close` and `git_discard`, is published as `action.proposed` and awaited for `action.result|denied|needs_human` in `SessionRunner._propose_and_await` (`session.py:1626`); nothing in this package calls a tool directly. The only local refusal is `unplaced_voice_refusal` (`session.py:559`), which proposes nothing.
2. Orchestration never subscribes to `action.proposed` (`SUBSCRIBE_ONLY_BY[action.proposed] = {guardian}`) and never publishes `action.approved`, `action.denied`, `system.pause|stop|resume|restart|reload`, `self.model.updated` or `plan.proposed` (`contracts/topics.py:288-303`).
3. An unregistered tool is labelled `irreversible` in the proposal (`tools.py:572-585`); the label is a request, and Guardian decides (S6, T1: Guardian still reads this label).
4. A chat turn's conversation window is keyed by `contracts.settings.conversation_key(channel, speaker)` (`context.py:350`), the same function Memory feeds `WorkingMemory` under; the window (last 6 turns) is rendered before the memory block, and only for the `chat` scaffold.
5. On a voice channel, memory items tagged `person:<x>` reach the prompt only when `<x>` is the current speaker (`context.py` `_theirs`).
6. A context request (memory, world) that times out or errors is omitted and the prompt says why; it never stalls a session beyond `DEFAULT_TIMEOUT_S = 0.25` s.
7. `_land` publishes `learn.self_patch.applied` with the landed commit whenever `worktree_land` succeeds (`session.py:793-812`; `test_worktree_flow.py`).
8. A session never ends leaving an uncommitted edit it made in the live tree: `SessionRunner.run` discards it, or keeps it for the next attempt only when the outcome is `blocked` for continuation, verification, uncommitted or landing reasons and `attempt < KEEP_EDITS_UNTIL_ATTEMPT` (6) (`session.py:840-857`).
9. A `completed` outcome whose text claims work the step log does not show, or with uncommitted edits, is turned into `blocked` (`session.py:684-735`).
10. Patch and skill tasks in `execute` mode work in their own worktree when Execution offers `worktree_open` (`WORKTREE_KINDS`, `session.py:59`); chat, research and plan sessions edit the live tree (S10).
11. Every terminal outcome publishes exactly one `task.*` terminal message and one `turn.completed`, including a cancelled or crashed chat turn (`worker.py:405-420`); a requeued (preempted) task reports nothing.
12. A worker runs one claimed task at a time (`max_inflight=1`), and a percept chat runs as its own asyncio task so the bus handler timeout cannot cancel it (`service.py:266-290`).
13. Each verify request uses a fresh `verification_id` per attempt (`session.py:1748`), so Verification never replays an old verdict.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract orchestration`.

- `tests/simorgh/orchestration/test_session_flows.py` -- the loop over the real in-memory bus: think, `action.proposed`, result or denial fed back, verify and revisions, pause, the honest floor.
- `tests/simorgh/orchestration/test_worker.py` -- claim via `task.claim`, terminal reporting, `turn.completed` for percepts and tasks, lease heartbeats, crash resume on a second worker.
- `tests/simorgh/orchestration/test_tools_router.py` -- the `action.proposed` payload: reversibility, scope and the unknown-tool default.
- `tests/simorgh/orchestration/test_the_memory_block_remembers_recent_turns.py` -- the memory block and the per-(channel, person) conversation window.
- `tests/simorgh/orchestration/test_worktree_flow.py` -- worktree open before the first step, land after verification, a refused landing blocks, close on cancel.
- `tests/simorgh/orchestration/test_never_leave_a_broken_tree.py` -- uncommitted edits are discarded or kept, never abandoned.
- `tests/simorgh/orchestration/test_cancel.py` -- `task.cancel` stops a session at a step boundary.
- `tests/simorgh/orchestration/test_scaffolds.py` -- `Profile.scaffold` reaches Cognition's `task_rules`.

## Known issues (2026-09-18 evaluation)

- L1 (critical): tool calls are regex-parsed text markers; the model never sees a tool's description or schema (`tools.py`). Open; stage 2.
- L2 (critical): the transcript reaches the provider flattened into one user message (Cognition side). Open; stage 2 item 5.
- L3: no stable prompt prefix; the per-minute clock opens `task_rules` (`scaffolds.py:638, 690-692`). Open; stage 4.
- L4: one tool call is ~13 bus messages and ~20 appends (`_propose_and_await`). Open.
- L5: crash-resume restores the step count but not the context (`resume.py:117-144`). Open; stage 4 item 2.
- L6 / S10: a chat turn can edit the live checkout and orphan the edit (`profiles.py` CHAT carries `apply_source_patch`, `replace_in_file`, `run_script`, `install_package`). Open.
- L7 / W8: CHAT is a 20-step, 72-tool profile without task semantics. Open; stage 4 item 7.
- L8: domain and channel rules (TV, dashboard, pronunciation, voice refusal) live in `session.py`; four guards share one `claim_corrected` flag. Open; stage 4 item 8.
- L9: claim RPC, leases and heartbeats for one in-process worker. Open; stage 4 item 10.
- L10: loop features off by default. Addressed in the live config 2026-09-18 (stage 0 item 12); code defaults unchanged.
- L11: `session_id` never sent on `cognition.think`. Open.
- C1: `_land` published nothing on a landing. Fixed 2026-09-18 (commit 1e486f1).
- C7: critiques as episodic memory reached chat prompts. Fixed 2026-09-18 (aa05475): chat recalls episodic and semantic only; tasks add procedural.
- C8: no conversation across chat turns. Partly fixed 2026-09-18 (1e486f1): the working window per `conversation_key`; the session stream is stage 4.
- B2 / P4: the chat path drops the percept Message and the think request gets a fresh trace (`service.py:266-290`). Open; stage 1 item 2.
- S6 / T1 / S8: the proposal's reversibility label from `_TOOL_POLICY` is what Guardian trusts; physical tools are labelled `reversible`. Open.
- T2: `tool.registered` carries no schema; argument shapes live in `_MARKER_ARG_HINT` and marker tables (`tools.py:241-360`). Open; stage 2.
- T9: denial detection is the `denied: ` string prefix (`session.py:37-41`). Open; stage 2 item 8.
- P2: the verify subject never carries candidate/code/original and the wire kind is always `task` (`_put_verify_subject`). Open.

## Planned changes (roadmap)

- Stage 1 (telemetry): trace ids threaded per turn (`trace_id=session.task_id` on think, keep the percept Message); spans around think, tool run and verify.
- Stage 2 (native tool use): the prompt renders name, description and argument shape; typed turns in `session.messages` (assistant `tool_calls`, tool results by id); N calls per turn with reads concurrent and writes in order; error kinds replace `was_denied`; VOICE_CHAT flips first; the marker dialect is frozen in `tools.py`.
- Stage 3 (streaming): `session.delta` published as tokens arrive; a spoken filler on slow tools with Voice; a cheap-tier bridge line before slow turns.
- Stage 4 (session stream): one `session:<id>` event per turn that `resume.py` folds back (L5); one persistent session per (channel, person); `orchestration/contextbuilder.py` with a fixed stable prefix (L3); compaction by token pressure; token, USD and wall-clock budgets; agent definitions as files replacing `profiles.py`; one generic Stop hook replacing the claim guards (L8); the lease protocol skipped in single mode (L9).
- Stage 5: entity facts and per-person digest block; speculative recall on percept; a `memory_search` built-in.
- Stage 6: routing escalates by the Self Model's posterior; environment events appended into open sessions.
- Stage 7: the `Task` built-in for child sessions, projects awaiting children by event, checkpoint critic, a checkpoint after each irreversible action.
- Stage 8: propose, evaluate, adopt for growth candidates run in worktrees.
- Stage 9: the package moves to `simorgh/agent/`.

## Working on this module

Lock it first (`python tools/modlock.py claim orchestration --by <you> --task "..."`), commit the lock, edit only `simorgh/orchestration/`, `tests/simorgh/orchestration/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py orchestration` before committing; commit subject `orchestration: <what changed>`.
