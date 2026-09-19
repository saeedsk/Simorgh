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
| Verification's own pytest runs inherited Sim's full environment (every provider key) with no resource limits; one of the three runs executes the model's own tests on a copy of the task's tree (the other two run tests already on main, which the agent's report overstated) | verification | `fa12464` |

## Open, by what they risk

Updated 2026-09-19 (later the same night): everything below was fixed or deliberately closed except the first item.

**Safety and correctness**

- Still open on purpose: `verification/service.py` `_paused` is written and never read, so verifications run while paused. Deferring one would run into Orchestration's 300 s verification wait and risk accepting a task unverified. Decide with stage 4's budgets.
- Fixed: Planning's plans under review survive a restart (`planning:plans` stream).
- Fixed: `config_path()` and the Kernel resolve the same `simorgh.toml` (`SIMORGH_RUNTIME_DATA_DIR`).
- Fixed: `[runtime] subsystems` and `disabled` choose what boots; `bus`, `ledger`, `guardian` always do.

**Dead or misleading code** (all fixed in one sweep, one commit per module; three agents in worktrees, merged by the coordinator)

- ledger: `publish_health()` deleted (the Kernel publishes health); the stream listing runs off the event loop. `read_snapshot` is still a synchronous read.
- cognition: `produces` exact; `availability_poll_seconds` now drives the status tick.
- kernel: `since_last_idle_tick` reports the gap.
- bus: a traced message is sampled once.
- reflection: docstring honest, `SELF_STREAM` gone, duplicate tool recording gone. `register_monitor`/`raise_alert` still have no live caller; CONTRACT.md says so.
- curiosity: `any_free` gone; `novelty_score` measured against recent candidates. The follow-up reply still says `items_found: 0` because nothing has been read at reply time; the real count arrives on `curiosity.interest.updated`.
- persona: `user_model_min_confidence` removed with its uncalled reader; docstring fixed.
- verification: `review_require_real_provider` honoured; four keys settable from `simorgh.toml`.
- learning: six retired PatchPipeline keys removed.
- execution: `produces` exact (a local `topics as _topics` alias hid seven requests from every scan, which also hid `memory.forget`'s producer); `readable_root_files` reaches `pathsafety`.
- orchestration: `lease_seconds` removed (the lease is Planning's); two docstrings fixed.
- voice: `overheard_hours` removed (retention is fixed in `contracts/overheard.py`); the `aec*` keys are documented as Pipeline-only (V7).
- interface: `shell_timeout_s` bounds a typed `!command`.
- benchmark: `concurrency` removed (cases run one at a time by design).
- memory, guardian: comments corrected.
- tests: `test_tidy.py` moved to the contracts tier.

## What this says about the method

The evaluation's 201 agents looked for architectural problems and found them. Five agents asked to describe each module exactly, table by table, found a different class: the small, specific places where the code and its own promises disagree. Both kinds of reading were needed. A contract is only useful if it is true, and writing one made the author check every claim, which is what surfaced these. Repeating the exercise after each stage is cheap and worth scheduling.
