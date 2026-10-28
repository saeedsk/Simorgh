# Stage 19 -- Code-first problem solving: Sim reaches for a program when a job is data, and learns which way works

Status: **in progress** (2026-10-28: plan written; items 1-3 (execution), 4-7 (orchestration) and 8-9 (evals) started in parallel) · Depends on: stage 7 (child sessions), stage 14 (evals runner), stage 18 (spawn, background crews) · Modules touched: execution (items 1-3), orchestration (4-7), evals (8-9), docs

## Why

The creator, 2026-10-28, after three turns in which Sim "counted" the top promotional senders of a month from the 67 lines of a listing it could see: "why doesn't it write code to query emails in multiple iterations, put them in a spreadsheet or a database? Is Sim equipped to write code and chunk complex tasks into smaller tasks and use coding to solve them?" Then: "this is generic feedback ... solve this lack of intuitive thinking for all cases", and "you oversimplified the rules for Sim, I expect a more advanced system".

A per-tool fix (`mail_search group_by=sender`, 2026-10-28) answers one question. The failure is general, and it has two halves.

1. **Code cannot touch Sim's world.** `run_python_sandboxed` runs `python -I` in an empty temp directory with an empty environment: no tool results, no files, no way to call a tool, and nothing kept between calls. For a household job (mail, calendar, files, the ledger, the house, the web) a program has nothing to work on, so the model does the arithmetic in its head over whatever page fits its context. Every structured result is already stored in full as `results/<action_id>.json`, but no code tool can read it.
2. **Nothing chooses the method.** Neither the chat prompt nor the supervisor asks *how* a job should be done. "Count over a month", "for each of these 40 senders", "compare two years" and "find every file that ..." are all programs, or a plan of child tasks, but the turn treats each as one more tool call followed by an answer. Nothing learns from a supervisor verdict either. The same mistake recurs the next evening.

## Outcome

- Any job over more items than one tool page, any count, rank, join, dedupe or statistic, and any per-item repetition is done by **a program over the full data**, never by the model reading a listing.
- The program can **call Sim's read-only tools in a loop** (paginate, per-item fetch), with Guardian gating every call, and it can **keep a SQLite database and CSV files** for the job across steps.
- A job larger than one turn's budget is **decomposed**: a plan of smaller tasks, run as background crew members with code, and checked against measurable criteria.
- On voice, such a job is **escalated to the background** with a spoken acknowledgement, and the result is delivered when it is done.
- The supervisor **chooses the approach** at bar-setting time, **checks it at review**, and **keeps lessons**: each below-bar verdict becomes a short rule recalled for similar jobs later.
- An eval across **at least four domains** proves the behaviour is general, and per-domain prompt rules do not count as passing it.

## Definitions (shared by every item; do not rename)

**Workbench.** `simorgh/execution/workbench.py`, tool name `run_analysis`, `read_only = True` for its own effects. Each workbench run has a workdir, `results/work/<job>/`, where `<job>` is the session or task id from `ToolContext`. The workdir persists across calls in one job and is swept after `workbench_keep_days` (default 7). Each run is a fresh `python -I` subprocess with the same rlimits as `run_python_sandboxed`, cwd = the workdir, and `sim.py` importable. Args:
- `code` (string, required).
- `inputs` (array of result refs: an action id, `results/<id>.json`, or `"last"` for the newest result in this job). Each is copied read-only to `inputs/<id>.json`.
- `timeout_s` (optional, capped by config).

Module `sim` inside the run (stdlib only):
- `sim.rows(ref) -> list[dict]`: rows of an input or any result file of this job.
- `sim.db() -> sqlite3.Connection`: `work.db` in the workdir; it persists across calls.
- `sim.call(tool, **args) -> dict`: `{ok, output, rows, ref}`. It calls one of Sim's tools through the bridge: read-only tools only, at most `workbench_max_calls` (default 50) per run, each one a real `action.request` that Guardian sees.
- `sim.save(name, rows_or_text) -> str`: a `.csv`, `.json` or `.md` file in the workdir. It returns the path, which goes back to the model as a ref.

The result's output is the program's stdout, and its rows are whatever the program passed to `sim.result(rows)`, if it called it.

**Approach.** One of `direct | compute | parallel | decompose | background`, set by the supervisor at bar-setting:
- `direct`: one or a few tool calls answer it.
- `compute`: a program over full data (the workbench).
- `parallel`: independent parts (per-item fan-out, several sources or options, wall-clock beyond one sequential agent). Every member is spawned at once without asking, the person sees each member's progress, and the results are collected and reviewed as one answer. The creator, 2026-10-28: "speed matters ... at intake Sim should determine if parallel agents will help and, if yes, without hesitation run them, split the work, track their progress (showing it to the user), collect the results and complete the job."
- `decompose`: a plan of 2 to 6 child tasks with dependencies, each with its own measurable criterion; parts without a dependency between them run in parallel.
- `background`: longer than this turn allows; spawn it, acknowledge it, deliver later.

The criteria JSON gains `"approach"` and `"why"`.

**Lesson.** `{situation, rule, evidence_ref, principle, created_at, hits}`, written when a review is `below_bar` and the next review of the same turn is `meets_bar`. In other words, the fix worked, so the lesson is what changed. Lessons are stored on the ledger stream `supervisor:lessons` and recalled by text similarity, using memory's lexical scorer, for the bar-setting prompt: at most 3, newest first on ties.

## Items

### Execution (lock `execution`)

1. **Workbench tool.** Build `workbench.py`, register `run_analysis`, and add the config keys `workbench_dir`, `workbench_max_calls`, `workbench_timeout_s` and `workbench_keep_days`. *Accept:* a test stores a 200-row result, and a program counts rows by a column over `inputs/` and gets the exact count. `work.db` written in one call is read in the next. Files outside the workdir and the job's results are not readable.
2. **Tool bridge.** `sim.call` from the child process sends a JSON line on a pipe, and the parent runs the tool through the same gated path a model call takes (Guardian, ledger, the full-rows store). Only `read_only` tools are allowed, and an irreversible or unknown tool is refused by name. A per-run cap applies. *Accept:* a program that paginates a fake source with 1200 items in pages of 200 gets every item. Each call is logged as its own action with the workbench run as the parent. A write tool is refused.
3. **Results refs everywhere.** Every structured result's model text ends with `ref: <id> (N rows) -- use run_analysis inputs=[<id>] to compute over all of it`. The cut note of 2026-10-28 survives (orchestration keeps the closing notes). *Accept:* a test over three different tools.

### Orchestration (lock `orchestration`)

4. **Approach at bar-setting.** The criteria prompt teaches the four approaches with general triggers, never domain names: "more items than one page", "a count/rank/aggregate/compare", "the same step per item", "joins two sources", "more steps than this turn has". `parse_criteria` returns the approach, and `criteria_message` gives Sim the approach with a concrete next step (for `compute`: the `run_analysis` shape, with refs to the results already in hand). *Accept:* parse tests, and the four approaches render.
5. **Review checks the method.** Add a principle check: an aggregate that comes from the model reading a listing, not from a program over the full data, is `below_bar` with the next step "run_analysis over ref X". Do not add a domain rule. *Accept:* a review over a trajectory of a listing followed by an answer with counts gives an order naming `run_analysis`.
6. **Lessons.** As defined above: write them on the below-to-meets transition, and recall them into the criteria prompt. *Accept:* a lesson written in one session is recalled in a second session for a differently-worded but similar request, and is not recalled for an unrelated one.
7. **Parallel, decompose and background.** `parallel` spawns every subtask as a concurrent crew member (stage 18 `spawn`, `max_children_concurrent`), streams `crew.message` progress to the person (a line per member on chat, one ack and one delivery on voice), awaits all of them and assembles one reviewed answer. *Accept:* three members provably overlap in time, progress is emitted, and all three reports are in the answer. `decompose` makes the turn spawn a crew member for each subtask, with its criterion and its approach, and the CHAT profile's code tools, then await and assemble them. `background` (and any non-direct approach on voice, where the step budget is 6) spawns one background member, says a short acknowledgement, and delivers the result through the stage-18 background-report path. *Accept:* a test in which a voice turn's approach is `compute` spawns, acknowledges and delivers. CHAT and VOICE_CHAT both offer `run_analysis`.

8a. **The supervisor holds Sim to the approach.** The approach and the split are part of the bar (`Session.approach`, `Session.split`). Early, at the first steps after the bar is set, and once per counter: if Sim's actions do not match the approach (a `parallel` job whose first call is not `spawn`, a `compute` job answered by reading, a voice job not sent to the background), the supervisor sends an order naming the missing step. At review, the members spawned (how many, and whether they overlapped) and the `run_analysis` runs are evidence, and a mismatch is `below_bar` under Bias for Action (it did not start what it was told to) or Customer Obsession (the person waited longer than needed). The creator, 2026-10-28: "the supervisor should be aware of when a multi-agent run is expected and hold Sim accountable to follow that model". *Accept:* a parallel job done serially gets an early order naming spawn; a fully spawned one passes; the order does not repeat.

### Interface (lock `interface`)

8b. **The agents panel.** The creator, 2026-10-28: "the TUI should have full support for multi/parallel agent runs: in one view the user sees all the ongoing agents and their progress; the screen divides, with a right panel dedicated to the agents running in the background: their output, progress, status, token use, input/output". When a crew is active and the terminal is wide enough, the TUI splits. The transcript and prompt stay on the left. The right panel lists every member, each with:
- its brief (input);
- its status and elapsed time;
- its step count;
- its last progress line, plus a few lines of the newest output;
- tokens in/out and cost;
- at the end, its report (output).

The panel updates live from the `crew.*` topics and the budget events. A key or command toggles it and focuses a member to read its full output. A narrow terminal keeps today's inline tree. *Accept:* a render test of three members at 160 columns, a narrow fallback at 90, a live update from a progress event, and the toggle.

7b. **Persistence guardrails.** The creator, 2026-10-28: "I have not observed Sim retry; it just ignores, bails out and sits idle ... I expect a higher bar on agentic guardrails". The ledger agrees. On `task:6b0c6c98`, six voice steps went:
- a capped search;
- an off-task grep of Sim's own tests;
- the identical search again;
- a shell run that printed nothing, counted `ok`;
- a stop-hook bounce;
- a give-up answer ("I can start that if you say so").

Nothing resumed the job. The retries that exist (a transient provider error retried once, 3 nudges for a malformed call) are plumbing, not persistence. Build these, each named in `ablate`:
- (a) **No identical retry:** the same tool with the same args in a turn is not run; Sim is told to change strategy.
- (b) **Empty success is not evidence:** an `ok` with no output or no rows is not counted as evidence.
- (c) **Replan after a failure, a cap or a `below_bar`:** the strategies tried are listed for the model, and two distinct ones are required before `blocked`.
- (d) **Running out of steps or time with criteria unmet continues the job in the background, never as a give-up.**
- (e) **Open jobs** (`orchestration:open_jobs`) are resumed after a restart or by a heartbeat, or reported once as blocked.
- (f) **An off-task step is flagged early.**

*Accept:* a replay of that six-step trajectory ends in a background continuation and never repeats the search.

### Evals (lock `evals`)

8. **Code-first suite.** Scenarios in at least four domains with fakes big enough that a page cannot answer them:
- mail: top senders over 30 days in 1000 messages;
- calendar: hours in meetings per weekday over a quarter;
- files: the largest 10 files by type under a tree of 3000;
- ledger or telemetry: failures per tool over a week.
- A fifth case needs a per-item loop: "for each of these 25 senders, the date of the latest message".

Exact answers are scored. A separate check counts whether the answer came from a program (a `run_analysis` action) or from reading. *Accept:* the suite runs offline with a scripted model and is wired into `python -m simorgh.evals`.
9. **Measure (paid, within the session budget).** Run the suite before and after items 1-7 on the live provider order. Record the results in `docs/findings/2026-10-28-code-first.md`.

## Definition of done

- [ ] Items 1-8 merged, `--tier core` green.
- [ ] Item 9 measured: exact answers from 0-1 of 5 to at least 4 of 5, with a program behind each.
- [ ] No domain-specific rule in any prompt this stage adds.

## Rollback

Set `[orchestration] supervisor_approach = false` and `[execution] workbench = false`. Each restores the tool and prompts of 2026-10-27.
