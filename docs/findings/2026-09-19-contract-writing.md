# 2026-09-19: what writing the contracts found

*Recorded by Claude Code (Claude Opus 5) after stage 0 item 31. Five agents wrote the prose of all 19 `simorgh/<module>/CONTRACT.md` files in parallel, each reading its modules' code end to end. Between them they reported about 45 problems the 2026-09-18 evaluation had not catalogued. This file indexes them. Every one is also recorded under "Known issues" in the relevant CONTRACT.md, which is where to look when working on that module.*

## How the parallel run went

Five general-purpose agents, 19 modules split by layer. Each edited only its own CONTRACT.md files; the coordinating session held every module lock and did all commits, because agents sharing one checkout must not run git or edit the lock file concurrently (index races). About 10 minutes each, 1.4M tokens in total. Every contract came back with no TODO left and a contract-test list that `python tools/modtest.py --tier contract <module>` resolves. For the next parallel run of code changes (not docs), give each agent its own worktree (`isolation: "worktree"`) so it can commit under its own lock.

## Fixed the same night

| Finding | Module | Commit |
|---|---|---|
| Retention on long-lived streams with a colon in the name did nothing (compaction chose delete-vs-truncate by name); the 2026-09-18 retention fix was ineffective | ledger | `6ce1c78` |
| A restart reset Guardian's posture to baseline (never replayed from `guardian:trust`), and Sim may request a restart | guardian | `eff2620` |
| A classifier's ALLOW would have settled HumanOnlyRule and PhysicalRule escalations | guardian | `eff2620` |
| `/api/dash/data` still listed every camera, stream, Ring camera and event without the token | interface | `618191e` |
| Subscriptions made through a handler table were invisible to the manifest test (curiosity, planning, interface's HTTP layer) | contracts, curiosity, planning, interface | `d945d82`, `618191e` |
| Persona read `docs/SOUL.md` relative to the cwd; booted elsewhere, Sim lost its identity | persona | `d945d82` |
| `reflection:alerts` had no retention | ledger | `d945d82` |
| A blocked chat turn was still recorded as an `unknown` outcome | learning | `51420c5` |
| The retired pipeline's Correlators, dead handlers and two manifest entries were still in Learning | learning | `51420c5` |
| Execution's `stop()` crashed if `start()` had not set `_vision` | execution | `51420c5` |
| Chat's 90 s think cap never applied (every think ran against 180 s) | cognition | `3a441a5` |
| Scheduled jobs fired while the system was paused | kernel | `3a441a5` |
| `cognition:calls` grew forever, read by nothing | ledger | `3a441a5` |
| The benchmark runner resolved checkouts against the cwd | benchmark | `3a441a5` |
| No test pinned that a landing publishes `learn.self_patch.applied` | orchestration | test added |
| `verification` was a namespace package, invisible to the tools, with no contract | verification | `8b7e4dd` |
| Verification's own pytest runs inherited Sim's full environment (every provider key) with no resource limits; one of the three runs executes the model's own tests on a copy of the task's tree (the other two run tests already on main, which the agent's report overstated) | verification | this commit |

## Open, by what they risk

**Safety and correctness (do first)**

- `verification/service.py:108`: `_paused` is written and never read; verifications run while the system is paused. Left open on purpose: deferring one would run into Orchestration's 300 s verification wait and risk accepting a task unverified, which is worse. Decide together with stage 4's budgets.
- `planning/planmode.py:1-8`: plans under review or waiting for a person are held in memory only; the `plan:<id>` stream the docstring describes is never written, so a restart loses them.
- `contracts/settings.py:161-171` vs `kernel/config.py:157`: `config_path()` and the Kernel can resolve different `simorgh.toml` files when the data dir is not the default (the B11 shape).
- `kernel/config.py`: `[runtime] subsystems` and `disabled` are parsed and never applied, so no subsystem can be switched off by config.

**Dead or misleading code (cheap, per module)**

- ledger: `Service.publish_health()` has no caller; `run_compaction`'s `scandir`+`stat` of every stream still runs on the event loop (smaller B1).
- cognition: `Service.produces` omits `ui.notice` and the assembler's three requests; `availability_poll_seconds` unread.
- kernel: `since_last_idle_tick` is always 0 (`scheduler.py:305-308`).
- bus: a traced message is sampled twice (`client.py:189`, `trace.py:87`), harmless while rates are 0 or 1.
- reflection: `register_monitor` and `raise_alert` have no callers, so the alert and digest path runs only in tests; docstring says it never proposes actions (it proposes `notify`); `SELF_STREAM` never written; a duplicated tool-recording block (`service.py:256-261`).
- curiosity: `_BudgetState.any_free` is dead since the C9 fix; `novelty_score` is always 1.0; the follow-up request computes an unused value and always answers `items_found: 0`.
- persona: `user_model_min_confidence` is parsed and has no effect; a docstring says nothing publishes `curiosity.share.proposed` (Curiosity does).
- verification: `review_require_real_provider` has no effect (`_think` hardcodes False); four keys cannot be set from `simorgh.toml`.
- learning: six config keys belonged to the retired pipeline.
- execution: `Service.produces` omits most of what its tools publish; `pathsafety.py:58` hardcodes `ROOT_FILES` instead of reading `readable_root_files`.
- orchestration: `lease_seconds` is never read; two docstrings drift from the code.
- voice: `overheard_hours` does nothing; the four `aec*` keys matter only on the unused `Pipeline` path (V7).
- interface: `shell_timeout_s` is unread and `configcheck` does not know it.
- benchmark: `concurrency` is declared and never read.
- memory, guardian: a few stale comments (WorkingMemory "has no producer"; the split `physical_always_human_tools` comment).
- tests: `tests/simorgh/cognition/test_tidy.py` tests `contracts/tidy.py` and runs in the wrong module tier.

## What this says about the method

The evaluation's 201 agents looked for architectural problems and found them. Five agents asked to describe each module exactly, table by table, found a different class: the small, specific places where the code and its own promises disagree. Both kinds of reading were needed. A contract is only useful if it is true, and writing one made the author check every claim, which is what surfaced these. Repeating the exercise after each stage is cheap and worth scheduling.
