# refute:correctness:full_suite_ran fails 90% of the time bec

*Workflow: review · Phase: Refute · Agent id: `a2dbdb4bfcdbe13bd` · Tool calls: 13*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "testing-observability-process". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "full_suite_ran fails 90% of the time because 'the whole suite' is the wrong oracle inside a task",
    "kind": "right-design-undermined",
    "severity": "high",
    "claim": "The load-bearing gate for self-patching demands a run of `tests` (all 6,000 tests, ~2 minutes, including v1 and feature suites that are environment-sensitive) inside every patch task, and it fails 56 of the 62 times it has run in the live ledger.",
    "evidence": [
      "Live ledger probe: `('full_suite_ran', 'failed') 56`, `('full_suite_ran', 'passed') 6`.",
      ".simorgh_loader/last_trials.txt line 8: `run_tests([ran target='tests'] [failed 4: tests/simorgh/execution/media/test_cast.py:...  ✗ 1.8m` inside the create-a-file trial; the same file on the host: `python3 -m pytest -q tests/simorgh/execution/media/test_cast.py` -> `32 passed, 2 warnings in 32.41s`, i.e. the lab's suite was red for reasons unrelated to the change.",
      "last_trials.txt lines 150-158: `verification fail: mechanical check failed -- run_tests was called on a narrower target` three times, then `blocked in 70s -- verification failed after max revisions`.",
      "checks/fullsuiteran.py:31-60 describes the 'objection that could not be answered' and adds baseline attribution, which still needs a second full run to answer it.",
      "simloader.py:530-554 already defines the curated 45-second CORE selection with `-m \"not live\"`; the in-task check does not use it."
    ],
    "why_it_matters": "Verification's job is to give a patch a fast, attributable yes/no. A two-minute oracle that is red on this machine for unrelated reasons, running inside a step budget, converts the check into a revision loop that ends in 'blocked' -- the last_trials output shows exactly that. The creator then sees tasks blocked and blesses without trials (finding 1). The check is right; the suite it points at is the loader's `--all-tests` set, not the loader's gate.",
    "recommendation": "Define the suite once: expose simloader.gate_selection() (or a tests/core.txt it reads) and have run_tests' 'whole suite' mean that CORE selection, so the in-task oracle is the same 45-second set the loader blesses on. Persist the last green gate's failure set per machine and have _baseline consult it before re-running anything. Mark the feature suites (media, home, voice engines) `live` or keep them out of CORE so they cannot make the oracle red.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read loader trial log cited by the finding | decisions.jsonl last_green.json last_rollback.json last_trials.txt last_unit.txt unit_baseline-core.json unit_baseline.json 158 .simorgh_loader/last_trials.txt  |
| 2 | Bash | Check trial suite expectations for the cited trials | 64: # is expected to continue across attempts (`orchestration/resume.py`). 68: # idea (`breaks-the-suite`), the *good* outcome is no longer "the 83: "create-a-f |
| 3 | Bash | Read trial definitions and the edit-an-existing-file trial output |  expect_file: str \| None = None # A per-attempt step cap for this task (`task.create.max_steps`). max_steps: int \| None = None # How many attempts the task may  |
| 4 | Bash | Read the full_suite_ran check | simorgh/verification/checks/fullsuiteran.py ---- 491 simorgh/verification/checks/fullsuiteran.py 1 """`full_suite_ran`: a patch that changes code has to be chec |
| 5 | Bash | Read loader CORE selection and find ledger location | # ------------------------------------------------------------------ gate # The gate's tests: what Sim needs to boot, think, act safely and change # its own cod |
| 6 | Bash | List ledger streams, inspect run_tests tool, check known-findings docs | action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl action%3A000947307a9 |
| 7 | Bash | Inspect run_tests target handling and find where verification verdicts are recorded |  return self._config.test_timeout_s + 30.0 async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult: target = (args.get("target") or "").strip() or "t |
| 8 | Bash | Probe ledger for full_suite_ran outcomes by date and reason | verdict events 350 full_suite_ran {} --- reasons |
| 9 | Bash | Inspect a verify event's shape and the verdict payload builder | {"causation_id":null,"idempotency_key":null,"payload":{"checklist":[{"answer":"yes","evidence":"YES\n\nThe extracted assignment list pairs \"Fred Rebecca,\" sho |
| 10 | Bash | Probe mechanical check outcomes in ledger, count tests, check live marker and config | verdict events 350 full_suite_ran {'failed': 56, 'passed': 6} 2026-09-09 {'failed': 4} 2026-09-10 {'failed': 34, 'passed': 1} 2026-09-13 {'failed': 7, 'passed': |
| 11 | Bash | Detail the whole-suite-red verdicts with dates and attribution evidence; read the known-findings mention | Sep 18 14:00:32 2026 .simorgh_loader/last_trials.txt Sep 17 19:23:22 2026 .simorgh_loader/last_green.json ('09-10 00:11', 'passed', 'the whole suite ran and pas |
| 12 | Bash | Date the attribution fix and locate trial sandbox judging logic | efd1301 2026-09-11 Two seams the first live landings found: a bus deadline and a blamed flake bf0bc61 2026-09-10 Attribution had switched itself off, and a prob |
| 13 | Bash | Confirm baseline attribution re-runs only the failing tests | 25:more than `contracts/pytestfailures._MAX_IDS` -- against the tree as it 65:from simorgh.contracts.pytestfailures import failing_nodeids 80:BASELINE_TIMEOUT_S |

## Structured reply

**refuted:** True

**verdict:** partly-true

**reasoning:** The headline number is real but the causal story attached to it is wrong, and the mechanism the finding describes was fixed on 2026-09-10 and is demonstrably working in the live ledger since.

1. The count is confirmed: 56 failed / 6 passed for `full_suite_ran` across 350 verdict events in ~/.simorgh/ledger/streams/verify:*. But the failure reasons (read from `payload.mechanical.full_suite_ran.detail`) refute "because the whole suite is the wrong oracle": 21 are "no run_tests call in this session at all", 25 are "run_tests was called on a narrower target" -- i.e. 46 of 56 (82%) are the model not running the suite at all, which is exactly the false-pass this check exists to catch and says nothing about the suite being red. Only 10 of 56 are "the whole suite was run and it FAILED".

2. Those 10 are all timestamped 2026-09-10 15:50-16:27, the same day the attribution fix landed (`git log -- simorgh/verification/checks/_baseline.py`: dbf04c3 and bf0bc61 on 2026-09-10, efd1301 on 2026-09-11). Since then there has been ZERO "whole suite FAILED" block; every whole-suite-red case (09-13 x3, 09-16 x2) resolved to `passed` with "every failing test also fails at <base_ref> -- this change introduced none of them". The "revision loop that ends in blocked" is a history the check's own docstring records (fullsuiteran.py:29-53) and the ledger shows it no longer occurs.

3. The finding's claim that attribution "still needs a second full run" is false: `_baseline.failing_at_base` re-runs only the failing nodeids at base_ref (_baseline.py:179-224, BASELINE_TIMEOUT_S = 90), not the suite.

4. The trial evidence is misread. In `.simorgh_loader/last_trials.txt` line 8 the create-a-file task ran `tests`, got 4 test_cast.py failures, and then `git_commit` succeeded, `worktree_land` succeeded, and the trial is scored `PASS create-a-file completed` -- attribution rescued it, the opposite of the claimed outcome. Lines 150-158 are the `breaks-the-suite` trial, whose task is designed to break the parser tests; tools/trial_suite.py:121-124 sets `allow_safety_block=True` and lines 281-285 require `full_suite_ran` to have failed for the trial to PASS. It is scored `PASS breaks-the-suite blocked` -- the guard working as designed, not a broken oracle. The one trial that did block with a red suite (edit-an-existing-file, lines 27-37) shows a Together HTTP 503 failover mid-task and a final block reason of "finished with uncommitted changes" (the model answered without committing), not a full_suite_ran block.

5. What survives: (a) the oracle for in-task `run_tests` and `worktree_land.gate()` is literally `tests` (execution/tools.py:1243, 1271-1274), ~6,400 tests including the v1 top-level tests/*.py, while simloader.gate_selection() (simloader.py:528-553) runs a curated `-m "not live"` CORE set; the two "whole suite" notions do differ, and a ~1.8-2 min in-task run under a 300s test_timeout_s is real cost. That is a legitimate, modest consistency/latency point, not a high-severity "fails 90% of the time" defect. (b) The already-known-findings list and docs/architecture-review-2026-09-18.html:237 already discuss FullSuiteRanCheck in the context of failing-test-first; the suite-size mismatch itself is new but minor.

### evidence

- Ledger probe (python over ~/.simorgh/ledger/streams/verify%3A*.jsonl, field payload.mechanical.full_suite_ran): totals {'failed': 56, 'passed': 6}; reasons: 21 'no run_tests call in this session at all', 19+6=25 'run_tests was called on a narrower target', 10 'the whole suite was run and it FAILED', 5 passed via 'every failing test also fails at <base>', 1 'the whole suite ran and passed'
- Same probe by date: all 10 'whole suite was run and it FAILED' verdicts are 2026-09-10 15:50-16:27 (tasks 268012f5, 3c96a5e6, 45eb1ea5, 4fd89fac, 50e2aa01, 5208ae87); every whole-suite-red verdict on 09-13 (ecd5ea42, 3a4b68e6 x2) and 09-16 (bf15e939, 842145ae) is status=passed via attribution
- git log --date=short -- simorgh/verification/checks/_baseline.py: dbf04c3 2026-09-10, bf0bc61 2026-09-10, efd1301 2026-09-11 -- the attribution fix postdates or coincides with every 'suite FAILED' block
- simorgh/verification/checks/_baseline.py:179-224 failing_at_base runs pytest on the failing nodeids only, BASELINE_TIMEOUT_S = 90.0 (line 80) -- not a second full run
- simorgh/verification/checks/fullsuiteran.py:425-471: whole-suite-red path calls _attribution and returns passed when introduced and owned are both empty
- .simorgh_loader/last_trials.txt lines 8-13: run_tests target='tests' failed 4 (test_cast.py) then git_commit ✓, worktree_land ✓, 'PASS  create-a-file  completed  299s' -- the cited red suite did NOT block the task
- .simorgh_loader/last_trials.txt lines 150-158 are the breaks-the-suite trial, scored 'PASS  breaks-the-suite  blocked  71s'; tools/trial_suite.py:121-124 declares it expect_no_change=True, allow_safety_block=True and lines 281-285 require full_suite_ran to have failed for a PASS
- .simorgh_loader/last_trials.txt lines 27-37 (edit-an-existing-file): 'cognition.provider_failed provider=together ... HTTP 503', then 'answered as finished with 1 uncommitted edit(s)' and block reason 'finished with uncommitted changes' -- not a full_suite_ran block
- simorgh/execution/tools.py:1243 target defaults to 'tests'; :1271-1274 gate() for worktree_land runs 'tests'; simloader.py:528-553 CORE_TESTS + gate_selection(-m 'not live') -- the two 'whole suite' definitions do differ (this part is true)
- grep -rho 'def test_' tests | wc -l -> 6396; tests/ top level holds ~40 v1 test_*.py files that 'tests' includes and CORE excludes
- docs/architecture-review-2026-09-18.html:237 already references FullSuiteRanCheck (failing-test-first recommendation)

**corrected claim:** full_suite_ran has failed 56 of 62 times in the live ledger, but 46 of those failures are the model never running the whole suite (21 no run_tests call, 25 narrower target) -- the check catching exactly what it was built for -- and the 10 'suite was red' blocks all date from 2026-09-10, the day baseline attribution (_baseline.py) landed; since 2026-09-13 every red-suite case (5/5) has passed via attribution, which re-runs only the failing nodeids, not the suite. What remains is a modest inconsistency: the in-task run_tests default and worktree_land's gate run the literal `tests` tree (~6,400 tests incl. v1 and feature suites, ~2 min), while simloader gates on a curated `-m "not live"` CORE selection, so a self-patch is judged against a larger, slower, more environment-sensitive set than the loader blesses on. Severity: low-to-medium, design-consistency, not a failing gate.

**severity adjustment:** lower

