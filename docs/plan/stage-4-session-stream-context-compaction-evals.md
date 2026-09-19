# Stage 4 -- Session stream, ContextBuilder, compaction, evals package

Status: **in progress** (2026-09-19: items 1-3 done) · Depends on: stages 1 and 2 · Estimated: 3 weeks · Modules touched: contracts, orchestration, cognition, memory, interface, voice, kernel, benchmark, tools, simloader

## Outcome

Every session kind (chat, voice, task, project, sub-agent) is a typed transcript persisted as a `session:<id>` ledger stream, resumable after a restart and replayable for evals. One ContextBuilder in Orchestration owns prompt assembly with a stable, cacheable prefix. Compaction is driven by measured token pressure: old tool results age into re-fetchable stubs, then the existing progress note. Budgets are in tokens, dollars and wall-clock. Agent definitions are Guardian-protected files. Benchmark, the trial harness and the observer kit become `simorgh/evals/`, and the loader's bless runs it.

## Why

Evaluation L3 (no cacheable prefix), L5 (crash-resume restores steps but not context), L7/W8 (the 72-tool chat profile), C8 (the conversation is not a session), L9 (lease protocol for one worker), P1/P2/P3/P6 (the gate certifies shape), section 8.1 rows orchestration, cognition, evals, interface.

## Before you start

Stage 0 item 30's gate must exist and have before-numbers. Read `orchestration/session.py` (`_run`, `_think`, `_reground`, `_wrap_up`), `orchestration/context.py`, `orchestration/resume.py`, `orchestration/profiles.py`, `orchestration/scaffolds.py`, `cognition/assembler.py`, `cognition/compaction.py`, `interface/service.py:943` (the per-line uuid), `tools/trial.py`, `tools/trial_suite.py`, `tools/observer_kit.py`, `simorgh/benchmark/`.

## Action items

Done 2026-09-19: item 1 (`contracts/session.py`), item 2 (`orchestration/transcript.py`; a resumed session gets its messages back), item 3 (a conversation per (channel, person) on `session:conv:...`; recall scenario 2/3 -> 3/3). The reply-correlation id stays per line, so Interface and Voice did not change; the plan's wording (stop minting a uuid per line) is met by the conversation id instead.

1. **Turn and Block contracts.** *Lock `contracts`.* `Session{id, agent, channel, person_id, parent_id, depth, budget{turns, tokens, usd, wall_s}, state}`, `Turn{seq, role, blocks[], ts, meta{provider, model, in/out tokens, cached_input_tokens, cost}}`, `Block = Text | ToolUse{id, name, input} | ToolResult{tool_use_id, content, is_error, ref, bytes_total} | Image{ref}`; stream events `session.turn.appended`, `session.compacted{summary, dropped_seq_range}`, `session.snapshot`; stream name `session:<id>` in `streamnames.py`. Acceptance: schema tests; both-sides test updated.
2. **The session stream.** *Lock `orchestration`, `ledger`.* `SessionRunner` appends one event per turn (not per block); a snapshot every 50 turns; `resume.py` folds the stream into `session.messages` (fixes L5: a resumed session has its context). Acceptance: kill a task mid-step in a booted-Kernel test and resume with the same messages.
3. **One persistent session per (channel, person).** *Lock `interface`, `voice`, `orchestration`.* Interface stops minting a uuid per typed line for the *session* (the reply-correlation key stays per message); Voice uses the same session per speaker; the stage-0 `WorkingMemory` feed becomes a read of the session stream (keep `conversation_key`). Acceptance: the 30-turn recall scenario passes from the transcript alone with memory recall disabled.
4. **ContextBuilder.** *Lock `orchestration`, `cognition`, `contracts`.* One builder in `orchestration/contextbuilder.py` with a fixed prefix order (constitution → persona voice → self summary → person digest → agent body → tool specs → skills catalog), the compacted transcript, and per-turn material (memory recall, world now, time, notices) at the head of the latest user turn; explicit token budget per section; unavailable sections rendered as an honest note. Persona, self and memory are read through `contracts.protocols` reader interfaces the Kernel injects in-process in single mode (bus-backed adapters otherwise) instead of 0.25 s bus RPCs. `cognition/assembler.py` is deleted; `cognition.think` stays on the bus for Planning, consolidation and Verification. The clock and the budget hint leave the system prompt. Acceptance: two consecutive turns share a byte-identical system prefix; prompt tokens per turn recorded; `cached_input_tokens` > 0 on a caching provider.
5. **Compaction by token pressure.** *Lock `orchestration`, `cognition`.* Layer A at 70% of the provider's window: tool results older than `keep_recent_turns` become `[result of read_file <args>, N chars, ref session:<id>#<seq>]` re-fetchable via a `recall_result` built-in; layer B at 85%: the existing ProgressNote over everything but the prefix and the last M turns (a "conversation so far" flavour for chat that preserves facts about people); a PreCompact hook lets an agent definition add "preserve X". `reground_every_steps` stays off (measured no gain). Acceptance: a 100-turn scripted task keeps context tokens under the window without `context_too_large`.
6. **Budgets in tokens, USD, wall-clock.** *Lock `orchestration`.* `Budget` gains `max_tokens`, `max_usd`, `max_wall_s`; the step cap becomes a sanity bound; "step budget exhausted" becomes "budget exhausted: <which>". Acceptance: benchmark harness reports which budget ended a case.
7. **Agent definitions as files.** *Lock `orchestration`, `guardian`.* `agents/<name>.md` with frontmatter (tools allowlist with globs, model_tier, max_turns, max_tokens, max_cost_usd, max_wall_s, max_parallel_tools, verify, isolation, compaction thresholds, hooks, channels) and the scaffold as body; `profiles.py` + `scaffolds.py` become the loader; `agents/` joins Guardian's protected subjects. CHAT becomes read-only plus `start_task`; writing tools move to task agents (S10, L6). Acceptance: the six current profiles round-trip through files; a chat turn cannot `apply_source_patch`.
8. **One Stop hook, one trajectory check.** *Lock `orchestration`, `verification`.* A generic Stop hook: "final text claims an effect and this turn has no successful mutating ToolResult" bounces once naming the tools that could do it; Verification's trajectory check over the session stream replaces `claimed_to_commit`, `claimed_tv_act`, `promised_behaviour` on native paths (each police function deleted there when its span counter reads zero for a bless cycle). Acceptance: the police tests move to the hook.
9. **`simorgh/evals/`.** *Lock `benchmark`, `tools`, `simloader`.* Merge `benchmark/`, `tools/trial.py`, `tools/trial_suite.py`, `tools/observer_kit.py`, `tools/bench_instance.py`; suites: household (the recall scenario; lights/TV/reminders/mail/camera against fake devices), conversation, tool-use (BFCL), research (GAIA), code (SWE-bench Verified slice), long-task (60 turns; kill -9 and resume), voice (50 recorded turns); ≥3 repeats and a bootstrap CI; floor-answered cases skipped; a replay tier with a `FixtureProvider` keyed by session turn seq and tool_use id; `simloader.py bless` runs the suite by default with a post-handoff watch counting SLO breaches. Acceptance: `python -m simorgh.evals run household --repeats 3` prints a table; the loader's decision log records the eval result.
10. **Lease protocol behind a flag.** *Lock `orchestration`.* (L9) With `workers=1` on the memory bus, claims and heartbeats are skipped; the code stays for `local-multi`. Acceptance: task streams stop carrying lease events in single mode.
11. **Findings entry.**

## Measurements after

| Number | Target |
|---|---|
| Resume-after-kill: continues without redoing a step or repeating an irreversible action | 100% on the long-task suite |
| Context tokens per turn over 100 turns | plateaus below the window |
| Prompt-cache hit rate on a caching provider | > 60% of prompt tokens |
| Recall scenario from the transcript alone | passes |
| A chat turn editing the live checkout | impossible (profile) |

## Risks and mitigations

- Largest behavioural diff so far: land as file moves separated from behaviour changes, trial suite after each; one item at a time.
- Ledger growth per turn: per-turn appends and snapshots; retention on `session:` (90 d) from day one.
- Voice privacy today is a tag filter in recall; it must become a session property (item 3) before the old filter goes: the recall scenario's cross-person case is the gate.

## Definition of done

- [ ] Items 1-10 with tests; CONTRACT.md for every touched module updated; `agents/` protected.
- [ ] `simloader.py bless` runs the evals suite.
- [ ] Findings entry with the table.
