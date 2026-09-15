# Long runs: context, delegation and model tiers

The creator, 2026-09-15, after the first ten-copy benchmark wave: "what
architecture changes do you suggest to address Sim's ability to handle long-run
projects and benchmark tests?", then "go ahead: write the design doc and project
plan and proceed with developing and deploying it". The same conversation asked
for model tiering: "does it make sense to give Sim the ability to up-level its
LLM model when it performs complex stuff, then switch back to less expensive
models?", with Together's model list as the menu.

This document is written so the next session can build from it without
re-deriving anything. Line numbers are as of commit `b7aa40e`.

## 1. What stands today

**One session = one growing transcript.** `SessionRunner._run`
(`orchestration/session.py:704-951`) loops THINK → one tool → result. Every
THINK sends the memory block, the task text, an optional retry note, then
**all of `session.messages`** (`context.py:130-187`). Messages are appended at 16
sites and never removed. Tool results are cut at 8,000 characters each
(`_MODEL_RESULT_CHARS`, `session.py:1105`), but the transcript as a whole is not
bounded. Cognition compacts, and summarises only for chat
(`cognition/compaction.py`, `allow_summarize` set only for chat). A long task
that overflows gets `context_too_large`, which `_run` reports as "blocked: no real
provider" (`session.py:737-740, 1045-1072`), a misleading reason.

**Retries restart with a mechanical note.** `orchestration/resume.py`: a new
attempt gets a fresh budget and an empty transcript, plus `carried_note`. That
note is one line per earlier step, built from ledger summaries (at most 220
characters each, 6,000 in total, oldest attempts dropped). It is placed as one
user turn after the task (`context.py:170-184`). Nothing written by the model
survives between attempts.

**No delegation.** `start_task` (`execution/tools.py:1712-1837`):
- refuses inside a task ("fork bomb");
- sends no `parent_id`;
- never waits for the created task.

Planning's intake ignores `parent_id` and `depends_on` (`planning/intake.py:125-170`),
although `TaskStore.create` supports both. `max_depth`/`max_children_concurrent`
exist in `orchestration/config.py` and are read by nothing. Projects decompose
into children, but the project task is marked COMPLETED the moment its children
exist; no session waits on them. With `workers = 1` a task session is the one
in-flight delivery of `task.available`, so **a session that waited on its own
child through the queue would deadlock** (`worker.py:160-163, 215-271`).

**The spec already wants most of this.** `docs/blueprint/subsystems/16-orchestration.md`:
- §1 and §5 describe `delegate` (fresh/fork sub-sessions, summary-only return,
  depth ≥ `max_depth` withholds the tool).
- §3.5 sets `reground_every_steps = 3`.
- §4 describes a `context.snapshot` blob.
- §7 says "Orchestration does not compact".

`orchestration/README.md` lists all of these as not built.

**One model, one effort.** Every purpose goes to `together` →
`claude_code_cli` → `gemini` → `floor` (`cognition/config.py:48`), and in
practice to GLM-5.3-Flash with `reasoning_effort: "low"` on every call
(`providers/together.py:55`). Purposes differ only in token and cost budgets.

**What the benchmark wave measured** (`docs/benchmark-analysis-2026-09-14.md`):
- The reviewer's verdict does not track correctness: 111 correct and 111 wrong
  answers rejected.
- Research tasks (GAIA, BFCL) are not revised; patch tasks (SWE-bench) revise
  in-context, up to twice.
- 11 of 18 wrong SWE-bench cases produced no patch.
- GAIA level 3 scored 0 of 7.
- 53 cases were lost to provider timeouts and truncation.

## 2. Principles

1. **The transcript is working memory, not the record.** The record is the task
   stream on the ledger. The model's context should hold the goal, a progress
   note and the last few steps, not everything that ever happened.
2. **Only summaries cross a boundary.** Between steps (re-grounding), between
   attempts (retries) and between tasks (delegation), what passes is a short,
   structured note. Raw tool output never passes.
3. **Measure each change on the same cases.** Keep a change only if it wins on
   the long-run slice (§8).
4. **Cheap by default, strong on evidence.** A stronger model or more effort is
   spent where the purpose or a failure signal asks for it, and it is logged.

## 3. Change A: the progress note and re-grounding

**What.** Each task session keeps a `ProgressNote`:
- **goal:** the task restated in one or two sentences, written once;
- **done:** a bulleted list of facts established or edits made;
- **learned:** things that turned out true or false, including dead ends;
- **next:** the immediate plan;
- **open questions.**

It is stored as a ledger event `task.progress` on `task:<id>`, so it is durable,
resumable and visible. That follows the `task.edits_kept` precedent: a
ledger-only record type.

**When.** Every `reground_every_steps` steps (config, default 6; the spec's 3 is
too frequent for 14-30-step tasks), and whenever the assembled prompt passes a
size threshold. At the top of the loop, after the pause and cancel checks
(`session.py:717`), the session:

1. **Asks for a note:** one THINK with purpose `reground`, given the current
   note, the task, and the messages since the last re-ground. It returns the
   updated note as JSON, validated and length-capped.
2. **Records it:** `step{phase:"gather", summary:"reground"}` plus `task.progress`
   on the ledger.
3. **Replaces the transcript:** `session.messages` becomes the rendered note plus
   the last `keep_recent_steps` (default 2) step exchanges.

The task text and the `task_rules` scaffold are untouched; both are assembled
separately every step.

**Failure.** If the reground THINK fails, is truncated or returns an invalid
note, keep the transcript as it is and try again at the next interval. A failed
re-ground never loses context.

**Also fixes.** When `context_too_large` comes back, force a re-ground and retry
the step once. Only if that still fails, block, with the true reason: "context
too large".

**Tests.**
- The cadence: a note is produced at N and 2N steps.
- The transcript is replaced, and the goal and the last steps survive.
- A failed re-ground keeps the transcript.
- `context_too_large` triggers a forced re-ground, then a retry.
- The ledger has `task.progress`.
- The assembled prompt for a 30-step scripted session stays under a bound.

## 4. Change B: clean retries

A retry starts from the last `task.progress` note on the ledger when one exists,
not from `carried_note`. It gets: the note, one line "Attempt n-1 ended
<status>: <reason>", and the uncommitted-tree note. `carried_note` stays as the
fallback for tasks that never re-grounded. A crash resume, the same attempt
continuing, also restores the note and the last `keep_recent_steps` steps rather
than an empty transcript.

The same idea applies to patch revisions (`_verify_then_finish`,
`session.py:1221-1324`): a revision THINK gets the note, the current diff, the
failing test output and the objection, not the whole transcript. It sits behind
`[orchestration] clean_revisions`, so it can be compared with the
`review_benchmark = false` baseline (commit `b7aa40e`).

**Tests.**
- A retry after a re-grounded attempt carries the note, not step lines.
- A retry without a note falls back to `carried_note`.
- A crash resume restores the note and the recent steps.
- A clean revision's messages hold no pre-revision tool results.

## 5. Change C: fresh-context helper tasks (`delegate`)

**Tool.** `delegate(job, kind=research|patch|test, steps=N, files=[...])`. It is
offered to task profiles only while `session.depth < max_depth`, the spec's §12
Q4.

**Execution.** Delegation runs the child **in-process in the same Worker**, the
spec's §5 option. There is no queue round trip, so there is no deadlock and no
preemption.
1. `task.create{parent_id, kind, origin:"delegate", depth+1, max_steps}` is
   recorded for the ledger and Planning's view. It needs a new origin, so that
   human-origin preemption never cancels the parent.
2. A child `Session` is built with `for_task(kind)`, `depth+1`, and a user text
   of *only* the job brief, the parent's goal line and any named files.
3. `SessionRunner.run(child)` runs inline, bounded by `steps` and a wall-clock
   limit.
4. The parent receives a structured summary as the tool result:
   `{ok, answer, findings[], files_touched[], tests: {passed, failed}, steps, cost}`,
   capped at about 1,500 characters.
5. The child's own steps live only on `task:<child>`.

`Worker.current_task_id` gets a stack, so a nested run does not clear the
parent's (spec §12 Q7). Concurrency is 1 in the first build; parallel children
are Change F.

**Guardrails.**
- depth ≤ `max_depth` (3);
- the child budget comes out of the parent's wall clock;
- children inherit the parent's worktree for patch jobs, so edits land in one
  branch;
- Guardian sees every child tool call as usual;
- the child's cost counts against the parent's.

**Tests.**
- The parent's transcript holds only the summary (spec Flow 6).
- depth ≥ max withholds the tool.
- A child failure comes back as `ok:false` with a reason and does not crash the
  parent.
- The ledger has a separate child stream.
- There is no deadlock with `workers = 1`.

## 6. Change D: a test-first patch loop

For `patch` tasks that name failing tests (SWE-bench always does), the scaffold
and a session check ask for:
1. run the named tests first, through a `test` helper, and record that they fail;
2. edit;
3. run the named tests plus the test file they live in, through a helper that
   returns only status changes;
4. do not finish while a test that passed before now fails.

The check reuses `run_tests` and the checkout manifest from the SWE-bench path.

**Tests.** A scripted patch session that breaks a previously passing test is
refused `final` until it is fixed or the budget ends. The summary names the
regressions.

## 7. Change E: model tiers and escalation

**Serverless availability**, probed 2026-09-15 with a real 16-token request per
model:

| Model | $/1M in/out | Serverless? | Notes |
|---|---|---|---|
| `Prism-ML/Ternary-Bonsai-27B` | free | yes | reasoning model; a 16-token cap returned nothing |
| `openai/gpt-oss-20b` | 0.05 / 0.20 | yes | reasoning model; a 16-token cap returned nothing |
| `deepseek-ai/DeepSeek-V4-Flash-0731` | 0.14 / 0.28 | yes | answered directly, 1M context |
| `zai-org/GLM-5.3-Flash` (today) | 0.15 / 0.50 | yes | reasoning, 1M context |
| `zai-org/GLM-5.3` | 1.40 / 4.40 | yes | same family as today's model, 1M context |
| `deepseek-ai/DeepSeek-V4-Pro-0813` | 1.32 / 3.96 | yes | 1M context |
| `Qwen/Qwen3.8-Flash`, `Qwen/Qwen3.7-Max` | 0.15 / 0.47, 2.50 / 7.50 | streaming only | Sim's provider does not stream |
| other "free" (MiniMax-M2, Qwen3.5-35B, gemma-4, GLM-5.3-FP8, Llama-3.3-70B, Nemotron-3-Super), `Kimi-K2.7-Code` | — | **no** | "non-serverless": dedicated endpoints only |

The "free" list in Together's `/v1/models` is mostly models you can deploy on a
dedicated endpoint, not call per token.

**Tiers.**

| Tier | Model and effort | Used for |
|---|---|---|
| T0 | GLM-5.3-Flash `low` (or DeepSeek-V4-Flash) | chat, courtesy and background classification, tool steps, reground notes |
| T1 | GLM-5.3-Flash `medium`/`high` | `draft`, `research`, `review`, helper tasks |
| T2 | GLM-5.3 (full) `medium` | escalation only |

T2 is DeepSeek-V4-Pro if GLM-5.3 underperforms.

**Mechanism.**
- **Config:** `CognitionConfig.routes: {purpose: {provider, model, reasoning_effort}}`,
  with escalation rules.
- **Provider:** `TogetherProvider` already takes `model` and `reasoning_effort`
  per instance. Register several named instances (`together`, `together_strong`)
  and let the router pick per purpose, with the existing order as the fallback.
- **Escalation signals** (a session asks Cognition for `tier: "strong"` on its
  next THINK):
  - attempt ≥ 2;
  - two `finish_reason='length'` truncations in the step;
  - the same failing test after two edits;
  - a helper returned `ok:false`;
  - the task marked hard (GAIA level 3, or a plan with more than 5 steps).
- **Guardrails:**
  - a daily cost cap per strong instance (the existing `RollingWindowBudget`);
    when it is spent, drop to T1 and say so;
  - every escalation is a `cognition.escalated{purpose, reason, model}` ledger
    event.

**Tests.**
- Purpose routing picks the configured instance.
- An escalation signal routes one call to the strong tier, then back.
- A spent strong budget falls back, and the event is logged.

## 8. Change F (later): plan-first and parallel helpers

For tasks flagged long, a short PLAN session writes checkpoints first. Each
checkpoint runs as a delegated helper, and the parent checks each result before
the next. Parallel helpers for independent sub-jobs come only after A-E prove
out.

## 8a. Change G: the model scout

The creator, 2026-09-15: "I feel we need a daemon or code to handle Together's available AI models, research which one suits our need better, since the list dynamically changes and new models get added; test them, consider cheaper options, and for more advanced usage suggest better options."

**Why code, not a one-off check.** The 2026-09-15 probe showed that Together's own list misleads:
- Most "$0" models are dedicated-endpoint only ("non-serverless").
- Two strong, cheap models only answer with streaming.
- Several reasoning models return nothing under a small token cap.

Only real calls find this out, and the list changes weekly.

**Pieces.**
1. **Catalog** (`cognition/scout/catalog.py`), daily, free:
   - fetches `/v1/models` from `api.together.ai`, with a User-Agent;
   - stores `~/.simorgh/models/catalog.json`: id, organisation, type, context length, input and output price, first and last seen;
   - diffs against yesterday: new, removed, price changed.
2. **Probe** (`cognition/scout/probe.py`), for each new or changed chat model, a few tokens each. It records:
   - serverless or not;
   - streaming-only or not;
   - whether it reasons: a 16-token cap empties the content, or `reasoning_content` is present;
   - latency and whether `reasoning_effort` is accepted.

   Results are cached per model, so nothing is probed twice without cause.
3. **Eval pack** (`cognition/scout/evals.py`), weekly, cost-capped, only on serverless candidates in a tier's price band. It reuses the benchmark unit's datasets and scorers:

   | Check | What it tests | Tier it serves |
   |---|---|---|
   | 10 BFCL parallel cases | tool calls | T0 and T1 |
   | 10 GAIA level 1 cases | research answers | T1 |
   | Sim's own progress-note prompt on a canned transcript | valid JSON and the facts kept | re-grounding |
   | the QUIET/answer judgement on 20 labelled room lines from `voice:turns` | staying quiet correctly | T0 voice |

   Each check records accuracy, cost per case, latency and truncations.
4. **Recommendations**: for each tier (T0 cheap, T1 default, T2 strong), the best model by accuracy per dollar within a latency limit. It is written to `~/.simorgh/models/recommendations.json`, and the creator is told through `notify` or the dashboard:
   - "DeepSeek-V4-Flash matches GLM-5.3-Flash on the T0 pack at 45% of the cost";
   - "new: X, strongest T2 candidate".
5. **Apply**: never automatic for T1 or T2. A proposal is a one-line command (`models use t0 deepseek-ai/DeepSeek-V4-Flash-0731`) that writes `[cognition] routes` through `contracts/settings.persist`. A later option: T0 may switch on its own when the candidate is at least as accurate on the pack and cheaper, with the change announced and one command to undo it.

**Where it runs.** A kernel periodic job, like reflection's timed pass, gated by `[cognition.scout] enabled` and `daily_budget_usd` (default $0.50 for evals; the catalog diff is free). It is also available on demand: `models scan`, `models test <id>`, `models recommend`.

**Guardrails.**
- A hard dollar cap per run, and cases stop the moment it is reached.
- Probes and evals send no personal data: fixed public prompts and benchmark cases only.
- Every result is kept on the ledger stream `models:scout`, so a recommendation can be traced to its numbers.

**Depends on** change E's per-purpose routes, since a recommendation has to have somewhere to go. Adding streaming to `TogetherProvider` also opens the streaming-only models.

## 9. Measurement

**Long-run slice**, fixed and repeatable, all run with `tools/bench_instance.py`:
- all GAIA level 2 and 3 cases;
- the 15 SWE-bench Verified cases already run (offsets 0-17);
- 10 GAIA level 1 cases as a control.

**Per arm**, record:
- solve rate;
- skipped (floor);
- steps and wall time per case;
- cost per case;
- "step budget exhausted";
- "context too large";
- escalations.

**Arms, in order:**
1. **Baseline:** today, with `review_benchmark = false`.
2. **+A** (re-ground).
3. **+A+B** (clean retries and revisions).
4. **+A+B+C** (delegate).
5. **+E purpose routing.**
6. **+E escalation.**

## 10. Project plan

| # | Deliverable | Done when |
|---|---|---|
| 0 | `review_benchmark` switch | shipped, `b7aa40e` |
| 1 | This document | committed |
| 2 | **A**: `ProgressNote`, `task.progress`, re-ground hook, `context_too_large` handling, config `reground_every_steps`/`keep_recent_steps` | **done 2026-09-15**: `orchestration/progress.py`, `tests/simorgh/orchestration/test_reground.py`; off by default |
| 3 | **B**: note-based retries and crash resume; `clean_revisions` flag | **done 2026-09-15**: `resume.py` carries the latest `task.progress` note plus later steps; crash resume opens with the note; `[orchestration] clean_revisions` (off); `tests/simorgh/orchestration/test_clean_retries.py` |
| 4 | Benchmark arms 1-3 on the slice | results appended to `docs/benchmark-analysis-2026-09-14.md` |
| 5 | **C**: `delegate` tool, in-process child sessions, Worker task stack, `delegate` origin | **v1 done 2026-09-15**: read-only `research` helpers run in-process by `SessionRunner._delegate`, off by default (`[orchestration] delegation`, `delegate_max_steps`, `max_depth`); only the report returns (`tests/simorgh/orchestration/test_delegate.py`). The Worker stack and `delegate` origin were not needed: the child never goes through `Worker.run` or Planning. **Still to do:** patch helpers sharing the parent's worktree, and parallel helpers. |
| 6 | **D**: test-first patch check | tests green; pushed |
| 7 | **E**: per-purpose routes, strong instance, escalation signals, cost cap, `cognition.escalated` | tests green; pushed |
| 8 | Benchmark arms 4-6 | results appended; defaults set from the winners |
| 9 | **F**: plan-first, parallel helpers | only if 8 shows long tasks still stall |
| 10 | **G**: the model scout (section 8a) | catalog, probe and eval run on a schedule; proposals reach the creator; nothing applied without approval |

**Deploy.** Each deliverable is pushed to `main` when its tests pass. The live
Sim picks it up on `restart`, through the loader gate. Behaviour changes that
alter answers (A, B, C, E) ship **off by default** behind config switches, until
their benchmark arm wins. Then the default flips in a separate commit that
names the numbers.
