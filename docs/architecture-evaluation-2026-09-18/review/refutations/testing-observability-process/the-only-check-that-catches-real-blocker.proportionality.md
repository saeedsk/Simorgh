# refute:proportionality:The only check that catches real blocker

*Workflow: review · Phase: Refute · Agent id: `a616aaa731a4915a5` · Tool calls: 7*

## Task given to the agent

```text
You are reviewing the ARCHITECTURE of Simorgh, a self-improving personal AI agent written in Python (stdlib-first) at /Users/saeed/ws/Simorgh. The creator built it from scratch: ~87k lines in simorgh/, 18 subsystems (one package each) composed by a Kernel, talking only via typed messages on an async Bus, all state in an append-only Ledger of events, a Guardian that is the sole approver of every effect (HMAC token re-verified by Execution), worktree-isolated self-patching, a bootloader (simloader.py) that gates the checkout with the unit suite and rolls back. It chats (CLI/TUI/HTTP/Telegram/WhatsApp), talks (voice pipeline), controls the house (Home Assistant, Reolink cameras, Ring, Cast/Android TV), and runs benchmarks (GAIA/BFCL/SWE-bench).
  
  The creator asked: "review its architecture, evaluate it, tell me where I went wrong and how to improve it."
  
  Ground rules for you:
  - Read the CODE, not the docs, to establish what is true today. docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since. Do not report a historical finding as current state.
  - Previous reviews already exist and you must NOT simply repeat them. Already known (do not re-report unless you have something materially new to add): cameras use local ffmpeg/HLS instead of Home Assistant; self_patch.draft tool is named in learning/pipeline.py but not registered; Self Model capabilities["tools"] is never populated; no in-prompt sliding dialogue buffer for chat turns (orchestration/context.py); Ledger default backend is JSONL and ~1.4 GB; CHAT profile binds 34 tools; STT latency degrades under self-inflicted load; "unconnected wire" (designed slot, one side implemented, nobody writes it) is the project's dominant bug shape; test coverage thin in persona/learning/worldmodel; sim.sh auto-approve flips one boolean. Read docs/architecture-review-2026-09-18.html and docs/architecture-audit-2026.md quickly if you want the full list.
  - Useful orientation docs (read briefly, then go to code): docs/module-map.md, docs/architecture.md, docs/blueprint/02-system-architecture.md, docs/blueprint/03-contracts-and-messaging.md.
  - Every finding MUST cite file:line evidence you actually read, and where feasible a command whose output you quote. If a claim depends on runtime behaviour, try to establish it by a cheap command (python -c import + inspect, grep, wc, reading ~/.simorgh/simorgh.toml, listing ~/.simorgh/ledger). Do NOT boot the full system, do NOT run the full test suite, do NOT run anything that calls a paid model, do NOT modify any file in the repo.
  - Think like a senior systems architect. Distinguish (a) a design decision that is wrong or over-built for this system's real scale (one laptop, one family), (b) a design that is right but the implementation undermines it, (c) a genuine bug. Say which.
  - Your final text is data for an orchestrator, not a message to a human. Return only the structured output.
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "testing-observability-process". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "The only check that catches real blockers is optional and is being skipped",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "The loader's own docstring says a known-good tag is earned by 'the unit suite plus the scored trial suite', but run_gate only runs trials under --full, and the decision log shows the creator blessing four commits unit-only right after a full bless was refused for trial failures.",
    "evidence": [
      "simloader.py:26-29: 'The gate that earns one is the unit suite plus the scored trial suite -- because this week 2,600 passing tests sat on top of a system that could not write a file, and the trial suite is the check that would have caught it.'",
      "simloader.py:609-611: `if not full: return True, f\"unit suite green ({unit_why})\"` -- trials never run on `run`, only on `bless --full`.",
      ".simorgh_loader/decisions.jsonl tail: `{\"ts\": 1789765232, \"kind\": \"bless_refused\", \"commit\": \"e317076\", \"why\": \"trial suite had failures\"}` followed 187s later by `{\"ts\": 1789765419, \"kind\": \"blessed\", \"commit\": \"e317076\", \"tag\": \"sim-good-0020\", \"why\": \"unit suite green (3348 tests ran, none failed)\"}`; sim-good-0021, 0022, 0023 all 'unit suite green'.",
      ".simorgh_loader/last_green.json: `{\"commit\": \"93764b7...\", \"full\": false, \"all_tests\": false}`.",
      ".simorgh_loader/last_trials.txt: `3/7 clean`; FAIL edit-an-existing-file (blocked), research-a-question (blocked), already-done, continues-across-attempts; trial wall times 299+181+236+45+374+327+71 = 1533s; Together 503s mid-run ('cognition.provider_failed provider=together ... Service unavailable')."
    ],
    "why_it_matters": "The bootloader's promise is that a sim-good tag means independently verified; today it means 'the unit suite that has never caught a real blocker was green'. Sim's self-patches and the creator's own edits both roll forward on that tag. The trial suite is 25 minutes, costs money and fails on third-party outages, so the human rationally skips it, and the design silently degrades to exactly the gate the docstring says is insufficient.",
    "recommendation": "Make a cheap trial subset part of `bless` by default: two trials (create-a-file and breaks-the-suite, ~6 min) with autonomy off and a `--unit-only` flag that must be typed to skip them. Record the trial verdict (n/7 clean) in the tag's decision note and refuse to tag when it is worse than the previous tag's. Treat a provider 503 as 'not judged' rather than FAIL so an outage cannot block a bless, and cache the last trial verdict per source hash the way gate_reused already caches the unit result.",
    "confidence": 0.95
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read loader docstring and run_gate | for one reason this file has to honour above all others: **the loader never runs the code it is judging.** So: - This file is stdlib only. It does not import `s |
| 2 | Bash | Read loader decision log and trial record | {"ts": 1789695519.4761002, "kind": "gate_skipped", "commit": "9315cd1", "why": "skipped by the operator during the unit suite"} {"ts": 1789696030.501576, "kind" |
| 3 | Bash | Check bless defaults, sim.sh usage, and whether landing depends on the tag | 9:unit tests successfully, we accept this run and tag it ... if the code is 557:def run_gate(repo: Path, *, full: bool, timeout_s: float, notes: Path \| None = N |
| 4 | Bash | Read cmd_bless, trial verdicts, and trial suite definitions | def cmd_bless(repo: Path, notes: Path, *, full: bool, timeout_s: float) -> int: rule("bless") if is_dirty(repo): say("refusing: the working tree has uncommitted |
| 5 | Bash | Check what depends on sim-good tags in the landing path | sim-good-0023 sim-good-0022 sim-good-0021 sim-good-0020 sim-good-0019 ---- (eval):1: no matches found: simorgh/execution/tools/*.py ---- __init__.py __pycache__ |
| 6 | Bash | Read trial definitions, outage handling, and the failed trial narrations |  # check now catches the attempt after it has already made the edit, # and the correct ending is `blocked` with that edit still sitting # uncommitted in the tre |
| 7 | Bash | Check whether trial failures were real regressions and what tags record | tools/trial.py:100: max_steps: int = 0, attempts: int = 1) -> int: tools/trial.py:132: if max_steps: tools/trial.py:133: payload["max_steps"] = max_steps tools/ |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited fact checks out against the code and the loader's own notes. simloader.py:26-29 states the gate is "the unit suite plus the scored trial suite"; run_gate (simloader.py:606-607) returns "unit suite green" before the trial block whenever `full` is False, and `--full` is an opt-in store_true flag (simloader.py:1067), so plain `bless` never runs trials. cmd_bless's own comment (simloader.py:821-826) calls the trial suite "the gate that has actually caught every real blocker in this project". The decision log shows bless_refused for e317076 ("trial suite had failures") at ts 1789765232 and a unit-only bless of the same commit 187s later as sim-good-0020, then 0021-0023 unit-only; `git tag -n1` confirms the tag messages read "unit suite green (3348 tests ran, none failed)". last_green.json has full=false.

Two things the finding under- or mis-states, which matter for the recommendation. First, the trial failures the creator blessed over were mostly NOT provider-outage failures. Reading .simorgh_loader/last_trials.txt: `already-done` FAILED because Sim committed and landed a docstring change it was told not to make ("committed a change it should not have made", expect_no_change=True at trial_suite.py:108); `continues-across-attempts` FAILED because a task given max_steps=4 (trial_suite.py:118, forwarded at :219-220) ran ~9 tool steps and finished in one attempt ("finished in one attempt, so the continuation path was never exercised"), i.e. the step budget is not being honoured; `edit-an-existing-file` blocked on unrelated pre-existing full-suite failures in test_cast.py / test_a_patch_land inside the worktree; only `research-a-question` (verification judged after max revisions) is plausibly model/provider noise. So real behavioural regressions, of exactly the kind the docstring says the unit suite cannot see, were tagged known-good. This strengthens the finding. Second, the recommendation to treat a 503 as "not judged" contradicts a deliberate choice in tools/trial_suite.py:77 and :280 ("a provider outage ... still counts as a problem"), and this run's evidence does not show outages caused the FAILs, so that sub-recommendation is unsupported. Also, degradation is not fully "silent": the tag annotation honestly records "unit suite green", though `run`'s rollback target selection (good_tags, simloader.py:458) does not distinguish full from unit-only tags.

Scale lens: this is a process problem where usage undermines the design, not over-engineering. The fix proposed (a default 2-trial subset with a typed `--unit-only` escape) is modest; the log shows create-a-file at 299s and breaks-the-suite at 71s, so "~6 min" is roughly right but each trial embeds a 1.8-minute full pytest run and a paid model call, so it is a real per-bless tax for a developer blessing four times a day. Given the self-improving premise rests on the tag meaning something, and given real regressions were blessed, severity stays high.

### evidence

- simloader.py:26-29 docstring: 'The gate that earns one is the unit suite plus the scored trial suite -- because this week 2,600 passing tests sat on top of a system that could not write a file'
- simloader.py:606-607: `if not full: return True, f"unit suite green ({unit_why})"` -- trials only run under --full
- simloader.py:1067: `parser.add_argument("--full", action="store_true", ...)` -- opt-in, default off for bless and run
- simloader.py:821-826 comment in cmd_bless: 'the trial suite -- the gate that has actually caught every real blocker in this project -- was skipped in silence (2026-09-08)'
- .simorgh_loader/decisions.jsonl: bless_refused e317076 'trial suite had failures' at ts 1789765232.6; blessed e317076 sim-good-0020 'unit suite green' at ts 1789765419.2 (187s later); sim-good-0021/0022/0023 all 'unit suite green'
- `git tag -n1 sim-good-0020 sim-good-0023` -> both 'simloader: unit suite green (3348 tests ran, none failed)'
- .simorgh_loader/last_green.json: {"commit": "93764b7...", "full": false, "all_tests": false}
- .simorgh_loader/last_trials.txt line 158: '3/7 clean'; line 110 'FAIL already-done completed 374s - committed a change it should not have made'; line 125 'FAIL continues-across-attempts completed 327s - finished in one attempt, so the continuation path was never exercised'; line 37 'FAIL edit-an-existing-file blocked 181s' after 'run_tests([ran target=tests] [failed 2: tests/simorgh/integration/test_a_patch_land...'
- tools/trial_suite.py:108 already-done has expect_no_change=True; :118 continues-across-attempts has max_steps=4, expect_attempts_at_most=4; :219-220 forwards max_steps into the task payload -- so those two FAILs are behavioural regressions, not outage noise
- tools/trial_suite.py:77 and :280: a blocked status from 'a crash, a provider outage, a fabricated-completion catch' 'still counts as a problem' -- outage-as-FAIL is deliberate, contradicting the '503 = not judged' sub-recommendation
- simloader.py:458 good_tags() and cmd_run's rollback loop select tags by number only; nothing distinguishes a --full tag from a unit-only tag as a rollback target

**severity adjustment:** keep

**corrected claim:** The loader's docstring and cmd_bless comments define the known-good gate as unit suite plus trial suite and call the trial suite the only check that has caught real blockers, yet run_gate runs trials only under an opt-in --full flag and every current sim-good tag (0019-0023) was earned unit-only, including sim-good-0020 tagged 187s after a --full bless of the same commit was refused. The refused trial run (3/7 clean) failed mostly on real behavioural regressions -- Sim committed a change under expect_no_change, and a max_steps=4 task ran to completion in one attempt -- not on Together 503s, so the '503 should not block a bless' part of the recommendation is unsupported and contradicts trial_suite.py's deliberate outage-counts-as-failure rule. The tag annotation does record 'unit suite green', so the degradation is recorded rather than silent, but rollback target selection ignores the distinction.

