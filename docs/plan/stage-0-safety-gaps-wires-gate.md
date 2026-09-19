# Stage 0 -- Close the safety gaps, wire what exists, promote the gate

Status: **in progress** (started 2026-09-18 evening; items 1-24 and 27 done, 28 partly, 25-26 and 29-31 open) · Depends on: nothing · Estimated: 2 weeks · Modules touched: guardian, execution, learning, worldmodel, curiosity, ledger, interface, memory, orchestration, contracts, kernel, cognition, reflection, voice, simloader, tools, shared, docs

## Outcome

The house cannot be acted on without a person, whatever the code switch says. Every wire the evaluation found designed-but-unconnected is connected or deleted, and a contract test fails the build on the next one. The loop features that were built and off are on where the data supports them. Every module has a contract document and a test tier an agent can run in under a minute, and the repository has nothing in it that describes a system other than the one that runs. A measured gate exists (trial suite, benchmark, a recall scenario, a kill-and-resume trial) with before-numbers recorded, so every later stage has something to beat.

## Why

Evaluation ids: S1, S2, S3, S4, S5, S6, S8, S9, S15/V2 (safety at the edges); C1, C2, C4, C7, C9, C12, C13, C14 (the open growth loop and cheap bugs beside it); C8 (no conversation); B1, B3, B10, B11, B15, B16, B19, B21 (substrate hygiene); L10 (loop features off); W7 (one-sided topics); W9/P5 (docs and tests larger than the code); V1, V4, V6, V7, V8, V11 (surfaces hygiene). Capability unlocked: the first increments of every program in evaluation section 9 (routing by tier, parallel reads, delegation, a conversation window, a Self Model that knows its tools and gaps).

## Before you start

Read `docs/AGENTS.md` and `docs/testing.md`. Lock the module of the item you take. The before-numbers for this stage were taken on 2026-09-18 and are in `docs/findings/2026-09-19-stage-0.md` once written (item 30); until then, the evaluation's section 2 table is the baseline: suite 6,652 tests / 16:40; ledger 118,215 files / 1.4 GB; 0 human escalations in 26,737 decisions; 91% of outcomes `unknown`; `capabilities["tools"]` empty; 25 one-sided topics.

## Action items

Each item is one commit. **Done** items record the commit so a reader can diff them. *Parallel* items may be taken by different agents at once.

### Done (2026-09-18/19)

1. **v1 deleted; test tiers and locks.** `src/`, `tests/test_*.py` (881 tests, 1,637 s of the suite), `games/`, tracked toys; code that named `src/` (planning source roots, a verification invariant, Guardian's protected list); `tools/modtest.py`, `tools/modlock.py`, `docs/modules/locks.toml`, `pyproject.toml` markers, `CLAUDE.md`, `docs/AGENTS.md`, `docs/testing.md`. Commit `a4bf8d1`.
2. **PhysicalRule and `[guardian.physical]`.** `guardian/rules.py::PhysicalRule` before `ReversibilityRule`; recomputes the class from arguments via `contracts/home/policy.classify_call`; `human` escalates in every posture; `physical.auto_approve` is the only switch and `sim.sh` never sets it. Drill in `tests/simorgh/guardian/test_physical_rule.py`. Commit `8916e82`. (S1, S6, S8)
3. **Outcomes refuse `unknown`; PatchPipeline retired.** `learning/outcomes.py` skips and counts untyped turns; `learning/pipeline.py` deleted; Learning's health reports ok. Commit in `stage 0: five wires closed`. (C2, C14)
4. **`compute_gaps` and `capabilities["tools"]`.** `worldmodel/selfmodel.py::compute_gaps` ranks the least-known task types; `worldmodel/service.py::_sync_tools` writes the tool list from `tool.registered` once at `system.started` and on every change. Same commit. (C1 part)
5. **Curiosity reads the real budget fields; skipped ticks are edge-triggered.** `curiosity/service.py`. Same commit. (C9, C4)
6. **Retention on every timer-driven stream.** `ledger/compaction.py::DEFAULT_RETENTION`. Same commit. (B3, B19)
7. **The cameras are never open.** `interface/httpapi.py` gates `/api/dash/streams`, `/cameras/snap/`, `/tv/hls|media/`; a non-loopback bind without a token serves only the open routes; `tests/simorgh/interface/test_httpapi_token_boundary.py`. Same commit. (S15, V2)
8. **A conversation window per (channel, person).** `contracts/settings.py::conversation_key`; Memory feeds `WorkingMemory` from `turn.completed`; `orchestration/context.py::_working_block` renders the last six turns before the memory block. Commit `stage 0: a conversation window per person`. (C8)
9. **The landing path publishes `learn.self_patch.applied`.** `orchestration/session.py::_land`; `Session.landed_commit` from the `worktree_land:<sha>` side effect; the schema's `tests` field optional. Same commit. (C1)
10. **A topic with one side fails the build.** `tests/simorgh/contracts/test_topics_have_both_sides.py` with an allow-list that names the stage connecting each entry and fails when an entry gains its other side; `learn.pipeline.*` deleted. Commit `contracts: a topic with one side fails the build`. (W7)
11. **The Supervisor supervises.** `kernel/supervisor.py::run_ticker`, a restart that restarts with a fresh Context, `system.health` on change; `kernel/cli.py::_configure_logging`; `mcp approve` writes `contracts.settings.config_path()`. Commit `kernel + interface: the Supervisor supervises`. (B10, B21, B11)
12. **Live config switches.** `~/.simorgh/simorgh.toml`: `[orchestration] delegation=true, parallel_read_tools=4, escalate_from_attempt=1`; `[cognition.routes] strong/decompose/review/verify -> together_strong` (GLM-5.3, capped at $3/day); `[guardian.physical] auto_approve=false`. Backup at `simorgh.toml.bak-2026-09-18`. (L10; evaluation 9.1/9.2 first increments)
13. **Rebirth.** `~/.simorgh/ledger` moved to `ledger.pre-rebirth-2026-09-18` (delete when nothing is missed); voice recordings, overheard store and camera stills removed; five stale `sim/task-*` worktrees and branches pruned.
14. **Docs.** Old blueprint, plans, evolution log, knowledge base, module map removed; `docs/README.md`, `ARCHITECTURE.md`, `plan/README.md`; reviews under `docs/reviews/2026-09-18/`. Commit `docs: one map, the reviews in one place`.
15. **CONTRACT.md drafts** for every module from `tools/contract_skeleton.py` (tables filled, prose TODO). Same commit.
16. **Boot gate green** after all of the above: `python tools/modtest.py --tier core` 3,348 tests in 42 s.

### Done (2026-09-19, second session)

17. **Machine paths protected.** `.simorgh/secrets.toml`, `.simorgh/vault`, `.simorgh/ledger`, `.git/hooks`, `.ssh`, `.aws`, `.gnupg` are Guardian protected subjects; `run_shell` refuses to read them or dump the keychain. Commit `19f69ce`. (S2)
18. **The landing gate uses the loader's verdict.** `RunTestsTool.gate` re-judges a green run with `simloader.unit_verdict` from the main checkout; whole-suite baseline 5,762 recorded. Commit `c009699`. (S5)
19. **Installing a skill always asks.** `HumanOnlyRule` with `[guardian] human_only_tools = ["apply_skill"]`, every posture; `apply_skill` relabelled irreversible. Commit `8fb3d21`. Not done: scanning a skill call's arguments (they are data for the skill, and the denylist would misfire on them). (S4)
20. **Immunity remembers shell commands.** Same commit. (S9)
21. **Critiques are procedural memory**; task sessions recall them, chat does not. Commit `aa05475`. (C7)
22. **Cognition's two bugs**: the no-real-provider clock starts at the first floor; the rolling budget reads its stream once. Same commit. (C12, C13)
23. **Ctrl-C under the loader is orderly.** Commit `fd27fc7`. (B16)
24. **Blob sweep off the event loop**; `blobs_swept` in the compaction record. Commit `aa05475`. (B1, B9)
27. **Persona announces decay on real change** (`decay_announce_delta` 0.02 from the last announced state). Commit `aa05475`. (V6)
28. *Partly:* V1 fixed (a superseded quiet turn no longer drops the newer answer, commit `1f68f37`); V11 fixed (kept recordings bounded to 7 days / 500 MB, commit `eb207dc`). Open: V8 (three per-turn facts on the session), V7 (wire or delete the echo canceller).

### Open

17. **Protected subjects cover the machine, not only the repo.** *Parallel; lock `guardian`, `execution`.*
    - What: writes to the data directory's secrets and ledger, the git hooks, `~/.ssh`, `~/.aws` are denied; reads of the vault by `run_shell` are refused.
    - Files: `simorgh/guardian/config.py` (`DEFAULT_PROTECTED_SUBJECTS` gains `.simorgh/secrets.toml`, `.simorgh/ledger`, `.git/hooks/`, `/.ssh/`, `/.aws/`); `simorgh/execution/shell.py` (`DEFAULT_SHELL_REFUSALS` gains a read refusal for `secrets.toml`, `.ssh/`, `.aws/` -- `cat`, `head`, `less`, `python -c open(...)` shapes); `simorgh/execution/pathsafety.py` already refuses `_CREDENTIAL_DIRECTORIES` for file tools.
    - How: substrings, lower-cased, matched the way `ProtectedRule` already matches; for reads, a regex table entry with the reason the model is told.
    - Acceptance: `tests/simorgh/guardian/test_rules.py` gains a case per new subject (a `run_shell` `echo x > ~/.simorgh/secrets.toml` is denied at the `protected` layer); `tests/simorgh/execution/test_shell.py` gains `cat ~/.simorgh/secrets.toml` refused with the reason.
    - Rollback: revert the two tables.
18. **`tests/` is tier 2: a patch that touches tests runs the baseline check.** *Lock `execution`.* (S5)
    - What: the landing gate uses the loader's verdict function, so pytest exit 5, a shrinking count and a red summary all fail it.
    - Files: `simorgh/execution/worktree.py` (`WorktreeManager._land`, the gate call), `simorgh/execution/tools.py` (`RunTestsTool._run_isolated`), `simloader.py::unit_verdict` (import it: `simloader` is stdlib-only and importable from the repo root; add `sys.path` handling in one helper).
    - How: after the suite runs in the worktree, call `unit_verdict(returncode, output, baseline=read_baseline(repo))` and refuse to land unless it is green; the baseline is `.simorgh_loader/unit_baseline-core.json`.
    - Acceptance: `tests/simorgh/execution/test_worktree_land_gate.py`: a worktree whose only change deletes half the tests is refused with "count shrank"; exit 5 is refused; a green run lands.
    - Rollback: the old boolean check stays behind a config flag for one bless cycle.
19. **Skills: first install asks, runs are sandboxed.** *Lock `guardian`, `execution`.* (S4)
    - What: `apply_skill` is `irreversible` (a person sees the first install of a skill); `skill:<name>` tools run under the same rlimits and empty environment as `run_python_sandboxed`, and their arguments are scanned by the denylist.
    - Files: `simorgh/execution/tools.py` (`ApplySkillTool.reversibility`, `SkillTool.run`), `simorgh/guardian/rules.py` (`_CODE_ARG_KEYS` includes the skill's argument), `simorgh/orchestration/tools.py` (`_TOOL_POLICY` entries).
    - Acceptance: a new skill proposal reaches `needs_human` in the default config; a `skill:x` call carrying `subprocess.Popen` in its argument is denied by `denylist`.
    - Rollback: the two labels.
20. **Adaptive immunity remembers shell commands.** *Lock `guardian`.* (S9) `guardian/service.py::_remember_rejection` reads `command` as well as `code`. Acceptance: a denied `run_shell` is re-proposed reworded and denied by `immunity`.
21. **Reflection's critiques stay out of family chat.** *Lock `reflection`, `memory`.* (C7) Critiques are stored with `kind="critique"` (or tagged `source:reflection`) and excluded from the chat recall in `orchestration/context.py`. Acceptance: a stored critique does not appear in a voice turn's memory block.
22. **Cognition's two cheap bugs.** *Lock `cognition`.* (C12, C13) `_no_real_provider_since` is set on the first floor reply and cleared on a real one; `RollingWindowBudget.status()` keeps a running window in memory and replays the stream once at start. Acceptance: existing `test_service.py` health cases plus one for the window.
23. **SIGINT under the loader is orderly.** *Lock `simloader`.* (B16) `simloader.launch_sim` forwards SIGINT/SIGTERM to the child and waits `stop_grace_s` before killing. Acceptance: `tests/simorgh/test_simloader.py` case that a child receiving SIGINT gets `stop_grace_s` to exit.
24. **Compaction's blob sweep off the event loop.** *Lock `ledger`.* (B1) `sweep_unreferenced_blobs` runs in `asyncio.to_thread` and is skipped when the retention pass removed nothing. Acceptance: a test that a sweep with a slow reader does not block a concurrent bus handler.
25. **Interface's manifest is generated and tested.** *Lock `interface`, `shared`.* (V4) A test that `Service.consumes`/`produces` equal the topics the package actually subscribes/publishes (reuse `tools/contract_skeleton.py::scan`); fix the tuples. Then generalise the test to every module.
26. **`getattr(config, ...)` is forbidden.** *Lock `shared`, `execution`, `voice`.* (B15) `tests/simorgh/test_config_is_read_typed.py` fails on `getattr(<config>, "x", default)` outside an allow-list; replace the 123 sites with attribute reads, module by module under each lock.
27. **Persona publishes on significant change only.** *Lock `persona`.* (V6) A mood delta below `significance` (config, default 0.02) is neither published nor ledgered. Acceptance: a 5 s decay loop of 100 ticks produces fewer than 10 events.
28. **Voice hygiene.** *Lock `voice`.* (V1, V8, V11, V7) `_stay_quiet` checks the turn id before flipping to LISTENING; `_last_speech_s`, `_last_pcm`, `_last_skip` move onto the turn record; `keep_audio` gets retention by age and size (default 7 d / 500 MB) and defaults off in the code as it already does; the NLMS canceller is either wired into `VoiceSession` or deleted (decide by measuring echo false-positives with it on; record in findings).
29. **Test-suite consolidation, one directory at a time.** *Parallel per module; lock the module.* Using `docs/testing.md` section 3 and the per-directory analysis in `docs/reviews/2026-09-18/tests/` when it exists: mark `slow`, `integration`, `contract`; merge duplicate shape tests; delete tests that test a mock or a constant; name the contract tier in the module's `CONTRACT.md`. Target: full tier under 5 minutes; module tier under 60 s for every module. Acceptance: `python tools/modtest.py --tier full` time recorded in findings.
30. **The gate, and the findings entry.** *Lock `tools`, `docs`.* Run `tools/trial_suite.py` (3 repeats), one GAIA slice via the benchmark unit, and write the two new scenarios: a 30-turn household recall script built from the machine-names and birthday failures (`tools/recall_scenario.py`, driving `_handle_line` the way `test_cli_end_to_end.py` does, with a fake provider that echoes facts), and a kill-and-resume trial (`tools/trial.py --kill-at-step N`). Record before/after for items 8 and 12 in `docs/findings/2026-09-19-stage-0.md` with the suite time, ledger file count and the escalation count from the physical drill.
31. **CONTRACT.md prose.** *Parallel per module; lock the module.* Fill Purpose, the Files "For" column, the Consumes/Produces "Does/When" columns, Invariants, the contract-test list with what each pins, Known issues (catalogue ids) and Planned changes (stage numbers). The tables are generated; correct any over-match (a topic listed under Consumes that the module only publishes).

## Measurements after

| Number | Before (2026-09-18) | Target |
|---|---|---|
| Full suite | 6,652 tests, 16:40 | under 5:00 |
| Module tier, worst module | n/a | under 60 s |
| Ledger files after one day of use | 118,215 (44k/day) | under 5,000 |
| Human escalations for a `human`-class physical action | 0 of 26,737 | 100% (the drill) |
| Outcomes typed `unknown` | 91% | 0% |
| One-sided topics without a reason | 25 | 0 (test) |
| `capabilities["tools"]` | empty | 98 |
| Recall scenario: machine names at turn 14 and 19; birthday correction wins | fails | passes |
| Trial suite score | recorded by item 30 | no regression |

## Risks and mitigations

- The strong-tier route costs money: capped at $3/day in the live config; `escalate_from_attempt=1` only escalates retries.
- Delegation and parallel reads change what the model sees: the trial suite before/after is the gate (item 30); both are one-line config reverts.
- The conversation window changes the first thing the model reads: run the recall scenario before raising `_WORKING_K`.
- Test consolidation can delete a test that was the only pin of a real behaviour: delete only what `docs/testing.md` section 3 calls a shape test, one module per commit, module tier green.

## Definition of done

- [x] Items 1-16.
- [ ] Items 17-28 committed, each with its test.
- [ ] Item 29: full tier under 5 minutes; every module's contract tier named.
- [ ] Item 30: `docs/findings/2026-09-19-stage-0.md` with the table above filled in.
- [ ] Item 31: no `TODO` left in any `CONTRACT.md`.
- [ ] `python tools/modtest.py --tier full` green; `python simloader.py bless`.
