# refute:correctness:The only check that catches real blocker

*Workflow: review · Phase: Refute · Agent id: `a12841f154164eb7f` · Tool calls: 4*

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
| 1 | Bash | Read loader docstring and gate function | #!/usr/bin/env python3 """The Sim loader: a bootloader for a program that edits its own source. The creator, 2026-09-07: "at start up we should have an independ |
| 2 | Bash | Check loader decision log, last green, trial output, and bless flags | {"ts": 1789695519.4761002, "kind": "gate_skipped", "commit": "9315cd1", "why": "skipped by the operator during the unit suite"} {"ts": 1789696030.501576, "kind" |
| 3 | Bash | Check trial verdicts, bless command, sim.sh routing, and known-findings docs | 6:[32m ⏺ apply_source_patch(wrote simorgh/greeting.py) ✓ 1.7s[0m 7:[31m ⏺ run_tests([ran target='tests/simorgh/greeting'] refused: 'tests/simorgh/greeting' d |
| 4 | Bash | List trial verdicts, tagging code, and check known-findings docs for overlap | 13: PASS create-a-file completed 299s 37: FAIL edit-an-existing-file blocked 181s 67: PASS write-a-skill completed 236s 83: FAIL research-a-question blocked 45s |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line is accurate today. simloader.py:26-29 states the gate is "the unit suite plus the scored trial suite"; run_gate at simloader.py:606-607 returns `True, "unit suite green (...)"` whenever `full` is false and only reaches the trial block (609-637) under --full; --full is an opt-in store_true flag (1067) and sim.sh:57 exec's `simloader.py run "$@"` with no --full. The decision log shows exactly the sequence claimed: bless_refused for e317076 ("trial suite had failures") at ts 1789765232, then blessed sim-good-0020 187s later as "unit suite green", and 0021/0022/0023 all unit-only. last_green.json is {"full": false, "all_tests": false} -- so the `run` path gate is not even the full unit suite but the "core tests" subset (run_gate line ~566: scope "core" unless --all-tests). last_trials.txt ends "3/7 clean" with PASS create-a-file/write-a-skill/breaks-the-suite, FAIL edit-an-existing-file (blocked), research-a-question (blocked), already-done, continues-across-attempts; per-trial times sum to 1533s; multiple Together 503 provider_failed lines appear mid-run. The code is self-aware of the gap (cmd_bless 820-828 says "that tag is from the unit suite alone ... the gate that has actually caught every real blocker in this project") and the tag message honestly records the unit-only `why`, but that does not weaken the claim: the default gate is the one the docstring says is insufficient, and the human has demonstrably routed around the trial gate immediately after it refused. Not in the known-findings list (no mention of the trial suite/--full in the audit, review, or third-opinion docs). Classification "right design undermined" is apt: A/B-image loader is a sound design; the verification standard silently degraded to core-tests-only.

### evidence

- simloader.py:26-29 -- docstring: 'The gate that earns one is the unit suite plus the scored trial suite -- because this week 2,600 passing tests sat on top of a system that could not write a file'
- simloader.py:606-607 -- `if not full: return True, f"unit suite green ({unit_why})"`; trial block begins at 609 `rule("gate: scored trial suite")`
- simloader.py:1067 -- `parser.add_argument("--full", action="store_true", help="gate with the trial suite too, not just unit tests")`; sim.sh:57 `exec "$PYTHON_BIN" simloader.py run "$@"` (no --full)
- simloader.py:820-828 -- cmd_bless on an already-tagged commit: 'that tag is from the unit suite alone ... the trial suite -- the gate that has actually caught every real blocker in this project -- was skipped in silence (2026-09-08)'
- tail .simorgh_loader/decisions.jsonl: bless_refused e317076 'trial suite had failures' ts 1789765232; blessed e317076 sim-good-0020 'unit suite green (3348 tests ran, none failed)' ts 1789765419 (187s later); sim-good-0021 5a2b71c, 0022 6bd5229, 0023 47753fa all 'unit suite green'
- .simorgh_loader/last_green.json: {"commit": "93764b7...", "full": false, "all_tests": false} -- the `run` gate is the core-test subset, narrower still than the claim states
- .simorgh_loader/last_trials.txt lines 13,37,67,83,110,125,156: PASS create-a-file 299s; FAIL edit-an-existing-file blocked 181s; PASS write-a-skill 236s; FAIL research-a-question blocked 45s; FAIL already-done 374s; FAIL continues-across-attempts 327s; PASS breaks-the-suite 71s; line 158 '3/7 clean'; lines 28,58,75,98,136 'cognition.provider_failed provider=together ... Service unavailable'
- grep -in 'trial suite|--full|unit-only' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md -> no matches (not previously reported)
- git tag -l sim-good-* | tail: sim-good-0019..0023; HEAD 38a9049 is one commit past sim-good-0023 (47753fa)

**severity adjustment:** keep

**corrected claim:** As stated, with one sharpening: the sim.sh `run` path gates with the "core tests" subset (last_green.json all_tests=false), not even the full unit suite, so the tag Sim boots from and rolls back to is earned by less than the claim describes.

