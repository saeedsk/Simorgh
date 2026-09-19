# refute:proportionality:full_suite_ran fails 90% of the time bec

*Workflow: review · Phase: Refute · Agent id: `a49ef6ad25a366f03` · Tool calls: 13*

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
| 1 | Bash | Locate the cited check file and loader trial output | simorgh/verification/checks/fullsuiteran.py simorgh/verification/checks/fullsuiteran.py simorgh/verification/checks/fullsuiteran.py decisions.jsonl last_green.j |
| 2 | Bash | Read the check, the trial output, and the loader's gate selection | Exit code 1 1 """`full_suite_ran`: a patch that changes code has to be checked against 2 the WHOLE suite, not whatever slice the model chose to run. 3 4 `Isolat |
| 3 | Bash | Read the whole-suite matcher, the trial output, and the loader gate selection | 83 _WHOLE_SUITE_TARGETS = frozenset({"tests", "tests/", "'tests'", "'tests/'"}) 84 # `execution/tools.py::RunTestsTool` deliberately reports `ok=True` when 85 # |
| 4 | Bash | Check trial timestamps, ledger location, and read the baseline attribution helper | Sep 18 14:00:32 2026 .simorgh_loader/last_trials.txt Sep 17 19:23:22 2026 .simorgh_loader/last_green.json {"commit": "93764b7468dfd41cd77886b276ee4eb8f3a1afaf", |
| 5 | Bash | Find where check verdicts land in the ledger | Exit code 1 action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl action%3A00085e844cff.jsonl action%3A0009062c07cc.jsonl action%3 |
| 6 | Bash | List ledger stream kinds and find verification streams | 88356 trace 26737 action 2431 task 350 verify 310 reflect 5 memory 5 curiosity 5 cognition 3 persona 2 guardian 2 execution 1 voice 1 system.jsonl 1 schedule.js |
| 7 | Bash | Tally full_suite_ran verdicts in the live ledger with dates and detail | 0 Counter() |
| 8 | Bash | Inspect the shape of one verify event mentioning the check | /Users/saeed/.simorgh/ledger/streams/verify%3A08b2daa9f8a9.jsonl { "causation_id": null, "idempotency_key": null, "payload": { "checklist": [], "feedback": { "i |
| 9 | Bash | Tally full_suite_ran verdicts by reason and date | total 62 Counter({'failed': 56, 'passed': 6}) 09-09 21:27 failed 58e8df74cc37 \| no run_tests call in this session at all -- this change was never checked agains |
| 10 | Bash | Date the attribution fix, read run_tests tool limits, and check whether the cast tests are marked live | efd1301 2026-09-11 Two seams the first live landings found: a bus deadline and a blamed flake bf0bc61 2026-09-10 Attribution had switched itself off, and a prob |
| 11 | Bash | Check whether the patch scaffold tells the model up front to run the whole suite | (eval):1: no matches found: simorgh/orchestration/scaffolds/*.py __init__.py __pycache__ api.py claims.py config.py context.py profiles.py progress.py README.md |
| 12 | Bash | Check the patch scaffold prompt text about running the whole suite | 68: "run_tests": "run the test suite (or a subset) and get the result back", 254:3. Run run_tests. If it fails, fix it and run it again. 279: import it and call |
| 13 | Bash | Read the patch scaffold's test instruction | 245 ) 246 247 248 _PATCH = """\ 249 You are changing your own source. Work in this order and do not stop early: 250 251 1. Find the code. Use search_code before |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The headline number (56/62 = 90% failing) is reproducible but does not mean what the finding says. The verdicts are per revision round, not per task, and decomposing the 56 failures by detail string shows 46 of them are the check doing its job: 25 'run_tests was called on a narrower target' and 21 'no run_tests call in this session at all' -- the model never ran the suite, so no oracle choice would have passed. Only 10 are 'the whole suite was run and it FAILED' with no attribution, and all 10 fall in a 37-minute window on 2026-09-10 15:50-16:27, BEFORE the attribution fix landed (git: bf0bc61 2026-09-10 'Attribution had switched itself off'; efd1301 2026-09-11). Since then, every case where the suite ran and was red for unrelated reasons ended in a PASS via attribution: 5 of 5 (09-13 x3, 09-16 x2), zero unattributed suite-red failures. The 'ends in blocked' evidence (last_trials.txt 150-158) is the `breaks-the-suite` trial, whose EXPECTED outcome is blocked -- the harness marks it `PASS  breaks-the-suite  blocked`; it is proof the check works. The other trials cited (lines 8, 96, 122) all had media tests red for unrelated reasons and all LANDED (create-a-file PASS; already-done and continues-across-attempts 'completed'). The claim that attribution 'still needs a second full run' is false: _baseline.py:19-29 explicitly re-runs only the failing node ids at base_ref, cost proportional to failures, not the suite. The recommendation's second half (persist the last green gate's failure set per machine and consult it) is exactly the cache _baseline.py:19-29 argues against (invalidated by every commit, every uncommitted edit and the clock) and at one-laptop scale the measurement approach is the simpler one. What survives: (1) 'whole suite' really is two different sets -- fullsuiteran.py:83 accepts only 'tests' and RunTestsTool defaults to 'tests' (execution/tools.py:1243), while simloader.py:529-554 blesses on CORE with `-m not live` and --ignore of execution/{home,media,...}; so each patch task pays ~1.8 min (last_trials lines 8, 26, 96, 122) plus a baseline re-run to learn that test_cast.py is red for reasons the loader would never even look at. Pointing the in-task oracle at gate_selection() is a proportionate, small change. (2) The 46 'never ran the whole suite' rounds trace to scaffolds.py:254 ('3. Run run_tests. If it fails, fix it and run it again.') which never says 'with no target'; a one-line prompt fix would remove most of the wasted rounds -- that is the cheaper, materially new fix the finding missed. Classification: right design, implementation cost is higher than it needs to be (two definitions of the suite + a prompt that invites the narrow target); not a bug and not a high-severity gate failure.

### evidence

- Ledger tally (python over ~/.simorgh/ledger/streams/verify*.jsonl, payload.mechanical.full_suite_ran): total 62, failed 56, passed 6; by reason: 25 ('failed','narrower'), 21 ('failed','no run_tests'), 10 ('failed','suite FAILED (no attribution)'), 5 ('passed','passed-attributed'), 1 ('passed','passed').
- All 10 unattributed 'suite FAILED' verdicts are timestamped 09-10 15:50 .. 09-10 16:27; every suite-red verdict after that date is 'passed ... every failing test also fails at <base_ref> -- this change introduced none of them' (09-13 14:57, 09-13 15:09, 09-13 15:10, 09-16 18:17, 09-16 18:36).
- git log -- simorgh/verification/checks/_baseline.py: bf0bc61 2026-09-10 'Attribution had switched itself off, and a probe order put a dead tool back'; efd1301 2026-09-11 'Two seams the first live landings found: a bus deadline and a blamed flake'.
- .simorgh_loader/last_trials.txt:156 `PASS  breaks-the-suite         blocked       71s` -- the trial the finding cites at lines 150-158 as a failure mode is one whose expected outcome is blocked; line 158 `3/7 clean`.
- .simorgh_loader/last_trials.txt:8-13: run_tests target='tests' failed 4 (test_cast.py) 1.8m, then git_commit ok, worktree_land ok, `PASS  create-a-file  completed 299s` -- attribution passed the task despite the red media tests. Same shape at lines 96-110 and 122-125 (both 'completed').
- simorgh/verification/checks/_baseline.py:19-29: 'Why this is not a full baseline suite run ... This module runs only the node ids that actually failed -- typically a handful ... The cost is proportional to the failures, not to the suite, there is nothing to cache and so nothing to invalidate' -- refutes 'still needs a second full run' and pre-empts the 'persist the failure set' recommendation.
- simorgh/verification/checks/fullsuiteran.py:83 `_WHOLE_SUITE_TARGETS = frozenset({"tests", "tests/", "'tests'", "'tests/'"})` and :425-426 pass only on that; simorgh/execution/tools.py:1243 `target = (args.get("target") or "").strip() or "tests"` -- in-task 'whole suite' is the full tree.
- simloader.py:529-544 CORE_TESTS / CORE_IGNORE (execution/{home,media,energy,pim,knowledge,security}) and :547-554 gate_selection() returns `-m not live` + CORE paths; the loader's bless set excludes exactly the media tests that were red in-task. This part of the finding is confirmed.
- simorgh/orchestration/scaffolds.py:254 `3. Run run_tests. If it fails, fix it and run it again.` -- the patch scaffold never says 'with no target'; 46 of the 56 failed rounds are the model picking a narrow target or none.
- simorgh/orchestration/profiles.py:129 patch profile `max_steps=20, max_revisions=2`; simorgh/orchestration/session.py:474 `VERIFY_TIMEOUT_S = 300.0`; _baseline.py:80 `BASELINE_TIMEOUT_S = 90.0`.

**severity adjustment:** lower

**corrected claim:** The full_suite_ran check is sound and, since the 2026-09-10/11 attribution fix, no longer blocks tasks when the suite is red for unrelated reasons (5/5 such cases since 09-13 passed; the 10 unattributed suite-red failures all predate the fix). The 56/62 'failed' figure is per revision round and 46 of those are the model running a narrow target or no tests at all, which the check is meant to catch. What remains wrong is cost and duplication, not correctness: 'the whole suite' inside a task means the full `tests` tree (execution/tools.py:1243, fullsuiteran.py:83) -- ~1.8 min plus a baseline re-run per patch task -- while the loader blesses on a curated CORE selection with `-m not live` and the feature suites ignored (simloader.py:529-554). Two cheap fixes: have run_tests' default/whole-suite target use simloader.gate_selection() so the in-task oracle is the 45-second set the loader trusts, and change scaffolds.py:254 to say 'run run_tests with no target' so the model stops burning revision rounds on narrow targets. Do not add a persisted per-machine failure cache; _baseline.py:19-29 already gives the right reason not to at this scale.

