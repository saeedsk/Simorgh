# 06 — Migration from v1 (`src/`) to v2 (`simorgh/`)

> Part of the Simorgh v2 blueprint. v1 is a working system with ~20k
> lines, ~890 tests, and a constitution. This file maps every v1 module to
> its v2 home, lists the live-caught lessons that must survive the move,
> and gives the strangler-pattern procedure that keeps the suite green at
> every step.

## 1. Principles of the migration

1. **Port, don't rewrite.** Most v1 functions move nearly verbatim into
   a subsystem; what changes is *how they are invoked* (a message handler
   instead of a direct call) and *where state lives* (Ledger streams
   instead of module-level stores).
2. **Adapters keep v1 alive.** When a module is ported, its old path in
   `src/` becomes a thin adapter that delegates to the v2 package, so
   v1's tests and CLI keep working until cutover.
3. **Safety never regresses mid-migration.** v1's `AuditGate` remains
   the authority for any autonomous action until Guardian's test suite
   is a strict superset of `tests/test_audit.py` and the approval-token
   path is proven. Until then, v2 runs in `observe` mode.
4. **Lessons are tests.** Every live-caught fix in `docs/EVOLUTION.md`
   that has a regression test keeps that test, moved into the new
   package's test directory.

## 2. Module map

| v1 module | v2 subsystem | Notes |
|---|---|---|
| `src/main.py` (CLI loop, banner, commands, `run_cli`, `handle_turn`) | `interface` (CLI), `orchestration` (turn session), `kernel` (`__main__`, self-check) | The 3,300-line file dissolves: commands become bus messages; wiring becomes Kernel composition |
| `src/main.py` `propose_skill*`, `propose_self_patch`, `propose_patch_batch`, `_relaunch_or_rollback`, `_attempt_hot_swap` | `learning` | Each step becomes an `action.proposed` → Guardian → Execution message; gates become `verify.requested` |
| `src/main.py` `discover_creative_improvements`, `discover_creative_project`, `_creative_agenda_already_covered` | `curiosity` (+ `planning` for dedupe on `task.created`) | Diversified sampling now asks `world.env.query(capability_map)` and `self.gaps` |
| `src/main.py` `run_task`, `_next_task`, `_resolve_project_task`, `_maybe_roll_up_project`, `_reconsider_blocked_tasks`, `work_on_next_task`, `plan_goal`, `research_command`, `project_command` | `planning` (queue, DAG, rollup, retry policy) + `orchestration` (Worker loop) | `run_task` splits: Planning owns status transitions; Orchestration owns the loop |
| `src/main.py` `_autonomous_action`, `build_cognition_router`, budget constants | `kernel` scheduler (`system.tick.idle`) + `curiosity` + `cognition` config | `DEFAULT_CLAUDE_CODE_MAX_CALLS` etc. → `[cognition.providers.*]` config |
| `src/main.py` `_vitals_snapshot`, `_print_vitals`, `VitalsMonitor` | `interface` | A projection over `persona.state.changed`, `memory.stored`, `task.*`, `learn.*`, `system.metrics` |
| `src/orchestrator/router.py` (`SubAgent`, `Router`) | retired; sub-agents become subsystems or Workers | `AgentRequest/Response` → `cognition.think` + `persona.voice` |
| `src/memory/shared_bus.py` (`SharedMemoryBus`) | `persona` (state owner) + Bus events | Mood pub/sub becomes `persona.state.changed` on the system Bus |
| `src/orchestrator/persona_state.py`, `src/agents/emotion/base.py`, `src/orchestrator/socializing.py`, `src/agents/logic/base.py` (`mood_phrase`, `_IDENTITY_PREFIX`, `_CAPABILITY_REFERENCE`) | `persona` (state, emotion, voice, sharing) + `cognition` (prompt assembly consumes `persona.voice`) | `LogicAgent`'s tool loop itself → `orchestration` turn session |
| `src/agents/logic/base.py` conversational markers (PROPOSE/PATCH/BATCH/PLAN/EVOLVE/USE/NEWS/GROWTH/FETCH/RUN/READ/LIST/RECALL/REMIND) | `orchestration` turn session emits `intent.goal.stated` / `action.proposed` / `task.created` | Same gates; markers are parsed by `cognition`'s tool-call protocol into `tool_calls`, never a separate path |
| `src/agents/interests.py` (`InterestTracker`, `RssWorldFeed`) | `curiosity` (interests) + `execution` (web fetch tool) | |
| `src/cognition/provider.py`, `budget.py`, `claude_code_provider.py`, `gemini_provider.py` | `cognition` | `Provider` protocol in contracts; `BudgetGuard` becomes per-provider budget accounting reported as `cognition.provider.status` and enforced by Guardian for cost limits |
| `src/cognition/tool_protocol.py` (`parse_marker`, `first_line_argument`, `extract_code`, `is_valid_python`, `safe_read_file`, `safe_list_dir`, `read_file_for_patch`, `preview`, `ToolCapabilities`, `select_provider`) | `cognition` (marker/tool-call parsing, preview) + `execution` (safe read/list tools) | Path-safety boundary is now a tool property checked by Guardian scope + Execution |
| `src/orchestrator/audit.py` (`AuditGate`, `PROTECTED_SUBJECTS`, adaptive immunity, `REJECTED_KIND`) | `guardian` | Sandboxed smoke run for new skills moves to `verification` as a check; Guardian keeps denylist/immunity/protected/scope/mode/budget |
| `src/orchestrator/apply.py`, `git_ops.py` | `execution` (tools: `apply_source_patch`, `apply_skill`, `git_commit`, `git_revert`) | Scope enforcement duplicated as Guardian scope rule + tool-level check (defense in depth kept) |
| `src/sandboxing/sandbox.py`, `src/tools/web_fetch.py` | `execution` (tools: `run_python_sandboxed`, `web_fetch`) | SSRF guard stays in the tool |
| `src/orchestrator/self_patch.py` (`SelfPatchAgent`, `draft_patch`, SEARCH/REPLACE mode, `_docstring_regression_reason`, `check_main_py_invariants`, `run_isolated_test_suite`, `relaunch`) | `learning` (drafting loop as a Worker sub-flow) + `verification` (regression/invariant/test-suite checks) + `execution` (relaunch tool) | Protected: `learning` can never modify `guardian`, `execution`, `contracts`, `kernel`, `SOUL.md` — Guardian's protected list |
| `src/orchestrator/deployment.py` (`DeploymentManager`, hot-swap) | `learning` (experiments) + `execution` (hot-swap tool) | |
| `src/orchestrator/verification.py` | `verification` | Keep the "scan lines for YES/NO, defer on silence" behavior |
| `src/orchestrator/tasks.py`, `projects.py`, `discovery.py` | `planning` | `Task` gains `depends_on`, `mode`, `risk`, `origin`; event shapes preserved as `task:*` streams |
| `src/orchestrator/research_task.py` | `orchestration` (research Worker profile) + `memory` (finding storage) | |
| `src/orchestrator/capability_map.py` | `worldmodel` (env facet) | |
| `src/orchestrator/reflection.py`, `health.py` | `reflection` | `OutcomeLog` → `learn.outcome.recorded` events; `HealthMonitor` watches `persona.state.changed` |
| `src/orchestrator/consolidation.py` | `memory` (+ `system.tick.sleep`) | |
| `src/orchestrator/autonomy.py` (`ActivityClock`, `AutonomyController`, circuit breaker, digest) | `kernel` (idle clock, ticks) + `guardian` (failure-streak tightening) + `interface` (digest) | The breaker becomes trust-posture tightening; `autonomous on/off` → `system.pause/resume` scoped to autonomous work |
| `src/orchestrator/activity_log.py` | `ledger` (`trace:*`, `activity` stream) + `interface` (`log` command) | |
| `src/orchestrator/reminders.py` | `kernel` scheduler (`percept.time.scheduled`) | |
| `src/orchestrator/console_style.py` | `interface` | |
| `src/orchestrator/soul.py`, `docs/SOUL.md` | `guardian` (directives as rules) + `persona` (identity text) | SOUL.md unchanged; loaded by both, never editable by the system |
| `src/agents/skills/*.py` (applied skills), `registry.py`, `research.py`, `scheduler.py` | `learning` (skill library, research agent) + `execution` (skills registered as tools) | Skills keep their sandboxed execution |

## 3. Lessons that must survive (with their tests)

| Lesson (EVOLUTION milestone) | New home | Test to carry |
|---|---|---|
| `--bare` broke Claude Code CLI auth (66) | cognition provider adapter | `test_never_passes_bare_flag` |
| Models ramble past `READ:` — take the first line (marker fix) | cognition tool-call parsing | rambling-marker tests |
| Sandbox smoke run is unwinnable for self-patches (84) | verification: sandbox check only for new skills | `test_self_patch_subject_skips_the_sandbox…` |
| `relaunch()` must reconstruct `-m` invocation (85) | execution relaunch tool | `test_reconstructs_module_invocation…` |
| Self-patches silently dropped docstrings (87) | verification check | `TestDocstringRegressionReason` |
| Large files need SEARCH/REPLACE edit blocks (90) | learning drafting loop | `TestParseSearchReplaceBlocks`, `TestApplySearchReplaceBlocks` |
| Reviewer non-answer is not a rejection (92) | verification | `test_a_rambling_answer_that_never_states_a_verdict_defers_to_true` |
| Commit can report "nothing to commit" after a real write (93, unresolved) | execution git tool | keep the documented anomaly; add a check that the written file differs from HEAD before committing and log both outcomes |
| Pinned terminal panel fought readline (94) | interface | never in-place cursor control; scrolling blocks only |
| Idea repetition → diversified sampling + fuzzy dedupe (95) | curiosity + planning | repetition regression test |
| Autonomous project proposals must not lose the "attempted" signal (96) | curiosity | provider-sink OR test |
| Circuit breaker on failure streaks; budgets protect the subscription | guardian trust posture; cognition budgets | breaker tests; budget window tests |

## 4. Procedure (strangler pattern)

```
Step 0  Phase 0 lands: simorgh/{contracts,bus,ledger,kernel}. src/ untouched. Suite green.
Step 1  For each v1 module M being ported to subsystem S:
        a. Copy M's logic into simorgh/S/…; adapt to messages; move M's tests to tests/simorgh/S/.
        b. Replace M's body in src/ with an adapter: same public names, delegating to simorgh/S
           (or re-exporting), so every v1 import site and test still passes.
        c. Run both suites. Commit.
Step 2  Kernel boots v2 in `observe` mode alongside v1: v2 subsystems consume percepts mirrored
        from v1 (interface adapter publishes percept.text.received for each CLI turn) and produce
        messages, but Guardian denies all actions. Compare v2's decisions to v1's in the trace.
Step 3  Flip to `guarded` for read-only actions; then reversible; then the full v1 auto-apply
        policy once Guardian's tests ⊇ test_audit.py and the token path is proven.
Step 4  Move the CLI entry point: sim.sh → python -m simorgh run. src/main.py becomes an adapter
        that starts the Kernel.
Step 5  Remove adapters whose v1 tests have been fully moved. Delete src/. Update docs.
```

Each step is one or more commits; the suite is green after every commit.

## 5. Data migration

- `~/.simorgh/memory.jsonl` (v1 event-sourced records of many kinds) is
  imported once by a `simorgh migrate-v1` Kernel command that replays
  each record into the corresponding Ledger stream: `task_event` →
  `task:<id>`, `applied_source_patch`/`applied_skill` → `learn`,
  `llm_spend` → `cognition.budget`, `interest` → `curiosity`,
  `research_finding` → `memory:semantic`, everything else → `memory:episodic`.
- `~/.simorgh/cli_history` and `relaunch_context.json` are read by
  Interface/Orchestration unchanged.
- The import is idempotent (each v1 record id becomes the event's
  idempotency key).

## 6. Cutover checklist

- [ ] Flows 1–9 integration tests green on `memory`; durability smoke on `sqlite`
- [ ] Guardian tests ⊇ v1 `test_audit.py`; forged-token test; paused-denies-all test
- [ ] v1 CLI commands mapped (table in `interface` spec) and E2E tests ported
- [ ] `simorgh migrate-v1` run on the creator's real data dir with a backup
- [ ] `docs/architecture.md` rewritten to describe v2; v1 doc archived as `docs/archive/architecture-v1.md`
- [ ] `EVOLUTION.md` cutover milestone
- [ ] `src/` removed; `sim.sh` updated
