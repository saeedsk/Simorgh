# Stage 0 -- Close the safety gaps, wire what exists, promote the gate

Status: **in progress** (started 2026-09-18 evening; items 1-28 and 31 done except V7, 30 partly, 29 open, plus the follow-ups from contract writing) · Depends on: nothing · Estimated: 2 weeks · Modules touched: guardian, execution, learning, worldmodel, curiosity, ledger, interface, memory, orchestration, contracts, kernel, cognition, reflection, voice, simloader, tools, shared, docs

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

25. **Manifests match the code; the both-sides test reads the running bus.** 28 manifest discrepancies fixed; `tests/simorgh/test_manifests_match_the_code.py`; the both-sides test now reads subscriptions from a booted system. Commit `b5c2671`. (V4, W7)
30. *Partly:* `tools/recall_scenario.py` (18 turns, floor provider, 1.5 s, deterministic) with baseline **2 of 3** (the fact asked about in different words 13 turns later is not seen); pinned in `tests/tools/test_recall_scenario.py`. Commit `96e328d`. Open: the kill-and-resume trial and a trial-suite + GAIA run, both of which need a real model.

26. **No config fallback contradicts its default; `getattr(config, ...)` reads only go down.** Ten contradicting fallbacks aligned (`shell` keeps a safer one, allow-listed); `tests/simorgh/test_config_is_read_typed.py` ratchets the count at 127. Commit `f8195fe`. (B15)
28. **Voice.** V1 (`1f68f37`), V11 (retention), V8 (per-turn facts keyed by turn id, `68e5ea4`). Open: V7 below.

31. **CONTRACT.md for every module**, written by five parallel agents from the code; no TODO left; every contract-test list resolves. Commits `3588e97`, `f1dd4fe`, `c840d24`. Package READMEs removed (`723c9e3`). The agents found ~45 uncatalogued problems; 16 fixed the same night (`docs/findings/2026-09-19-contract-writing.md`).

### Open

28. **The echo canceller.** *Lock `voice`.* (V7) The NLMS canceller is built only in `Pipeline`'s speak path, which the live `VoiceSession` never runs: wire it into `VoiceSession` or delete it. Decide by measuring echo false-positives with it on and off on speakers (needs the microphone; record in findings).
29. **Test-suite consolidation, one directory at a time.** (Done so far: v1 tests deleted; full tier 1:34-1:52; module tier skips `slow`; the 30 s cast test takes 0.2 s.) *Parallel per module; lock the module.* Using `docs/testing.md` section 3 and the per-directory analysis in `docs/reviews/2026-09-18/tests/` when it exists: mark `slow`, `integration`, `contract`; merge duplicate shape tests; delete tests that test a mock or a constant; name the contract tier in the module's `CONTRACT.md`. Target: full tier under 5 minutes; module tier under 60 s for every module. Acceptance: `python tools/modtest.py --tier full` time recorded in findings.
30. **The rest of the gate.** *Lock `tools`, `docs`.* A kill-and-resume trial (`tools/trial.py --kill-at-step N`: kill -9 mid-task in a repo copy; the resumed task must not redo a step or repeat an irreversible action) and a trial-suite run (3 repeats) plus one GAIA slice through the benchmark unit, all with the real model; record the numbers with the recall scenario's in `docs/findings/`.
32. **Follow-ups from contract writing, safety first.** *Lock the module.* Verification's `_baseline.py` runs the model's tests with `subprocess.run` outside Guardian and the sandbox; Verification ignores pause; Planning's plans under review are lost on restart; `config_path()` and the Kernel can disagree on which `simorgh.toml`; `[runtime] subsystems/disabled` are not applied. Then the dead-code list in `docs/findings/2026-09-19-contract-writing.md`, module by module.

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
