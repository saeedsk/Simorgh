# refute:proportionality:11.5k lines of tests and a verification

*Workflow: review · Phase: Refute · Agent id: `ac6a2a272ba449d83` · Tool calls: 8*

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
    "title": "11.5k lines of tests and a verification invariant guard the dead v1 tree",
    "kind": "over-engineering",
    "severity": "medium",
    "claim": "The 41 top-level tests/test_*.py files (887 tests) import only src/, which nothing under simorgh/ imports, yet they remain in `--all-tests`, in the 'all' baseline, and one Verification invariant still protects src/main.py.",
    "evidence": [
      "`grep -l 'from src' tests/test_*.py | wc -l` -> 39; `grep -l 'simorgh' tests/test_*.py | wc -l` -> 0; `grep -rl 'from src' simorgh/ simloader.py sim.sh` -> nothing.",
      "src/: 16,441 lines; last commit touching src/ 2026-09-09, tests/test_*.py 2026-09-06.",
      "simloader.py:551-552 `if all_tests or not paths: return [\"tests\"]`; .simorgh_loader/unit_baseline.json `{\"tests\": 5969}` vs core 3348.",
      "simorgh/verification/config.py:28-31 `_DEFAULT_INVARIANTS = {\"src/main.py\": [\"AuditGate(\", ...], ...}`; simorgh/execution/ invariant `verifier.verify(` matches exactly 1 file of the package (grep -rl -> 1), so the prefix rule would fail any other execution/ file if it ever applied.",
      "tests/test_e2e_cli.py:1-9 is the only process-boundary e2e in the repo and it spawns `python -m src.main`."
    ],
    "why_it_matters": "A quarter of the suite by test count and 13% by lines is maintenance weight that verifies nothing the running system does, inflates the 'suite larger than the code' number, and keeps `--all-tests` at ~20 minutes. The only genuine process-level e2e pattern in the repo lives in that dead tree instead of being ported.",
    "recommendation": "Move src/ and tests/test_*.py to an archive branch or delete them (git keeps them), drop the src/main.py invariant, and port test_e2e_cli.py's pattern to v2 as a single CORE test that spawns `python -m simorgh --self-check` with a 60s timeout and asserts exit 0.",
    "confidence": 0.93
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Verify counts of v1 tests and src imports | --- test_*.py count 40 --- from src 39 --- import src 39 --- mention simorgh 2 --- src imported by simorgh/ (end) --- src lines 16441 total --- tests/test_*.py  |
| 2 | Bash | Check simloader baseline, verification invariants, and e2e tests | --- simloader 540-560 "tests/simorgh/integration/test_a_patch_lands_through_a_worktree.py", "tests/simorgh/test_module_boundaries.py", "tests/simorgh/test_simlo |
| 3 | Bash | Count tests, inspect baselines, core selection and invariant usage | --- baseline files decisions.jsonl last_green.json last_rollback.json last_trials.txt last_unit.txt unit_baseline-core.json unit_baseline.json .simorgh_loader/u |
| 4 | Bash | Trace invariant consumer, gate timings, and any live src references | --- invariant consumer (eval):1: no matches found: --include=*.py --- last_unit.txt tail /opt/homebrew/anaconda3/lib/python3.12/site-packages/openpyxl/writer/ex |
| 5 | Bash | Find invariant checker, src commit content, and gate timing evidence | --- invariant consumer simorgh/verification/checks/__init__.py:5:from .invariants import InvariantsCheck, invariant_violations simorgh/verification/checks/invar |
| 6 | Bash | Read invariant check logic and locate any existing self-check test | --- invariants.py """`invariants`: a generalization of `check_main_py_invariants` from `src/orchestrator/self_patch.py`. A narrow, cheap substring check, not a  |
| 7 | Bash | Measure invariant prefix-rule blast radius and self-check scope | --- guardian files with Pipeline( 1 9 --- execution py files 67 --- self-check body async def _cmd_self_check() -> int: result = await run_selfcheck() print(res |
| 8 | Bash | Confirm the invariants check is wired into the verification pipeline | 5:from .invariants import InvariantsCheck, invariant_violations 13:ALL_CHECKS = [ 20: InvariantsCheck(), 27:__all__ = [ 28: "ALL_CHECKS", 33: "InvariantsCheck", |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The factual core holds: tests/test_*.py is a v1-only tree (40 files, not 41; 881 `def test_`, not 887; 39 import `src`, the 40th spawns `python -m src.main`), nothing under simorgh/, simloader.py, sim.sh or tools/ imports src, src/ is 16,441 lines with its last commit a 4-line tweak on 2026-09-09, and simorgh/verification/config.py:28 still lists src/main.py in _DEFAULT_INVARIANTS. simloader.py:552-553 does fall back to `["tests"]` under --all-tests. But the cost framing is overstated at this system's scale: CORE_TESTS (simloader.py:529-545) excludes tests/test_*.py entirely, the default gate runs 3,348 tests in 45s (.simorgh_loader/last_unit.txt, unit_baseline-core.json), and .simorgh_loader/decisions.jsonl shows exactly 1 of 23 blessings ever used the all-tests path (sim-good-0004, 5969 tests) -- the stale unit_baseline.json is from that one run. The "~20 minutes" figure has no evidence anywhere in the repo (unit_baseline.json carries no `seconds`, no findings doc records it). So the dead tree is inert weight the developer already routed around, not a drag on the daily loop; deleting/archiving it is a five-minute git mv and worth doing for honesty of the 'suite vs code' number, but it is a housekeeping item, not a medium architectural problem. What IS materially new and more important than the headline: the invariant table is applied by prefix (simorgh/verification/checks/invariants.py:16-21, `subject_path.startswith(prefix)`), it is registered in ALL_CHECKS (checks/__init__.py:20) and run by Verification service.py:171, and it applies to any self-patch carrying a path+candidate. Only 1 of 67 simorgh/execution/*.py files contains `verifier.verify(` and only 1 of 9 simorgh/guardian/*.py contains `Pipeline(`, so a self-patch to any of the other 74 files in those packages is refused with "no longer visibly wires ..." -- a genuine latent bug (category c), not over-engineering, which the reader buried as a sub-bullet. The recommendation's e2e port is reasonable but its target is weaker than implied: `--self-check` (kernel/cli.py:71-74) runs run_selfcheck(), which per tests/simorgh/integration/test_kernel_boots_all_sixteen_subsystems.py:13 "deliberately uses two small inline" subsystems, so `exit 0` would not prove the real composition boots; and an in-process line-typed e2e (tests/simorgh/integration/test_cli_end_to_end.py) plus a full build_factories() boot test already exist in v2, so the "only genuine e2e pattern lives in the dead tree" claim is only true for the process boundary specifically.

### evidence

- `ls tests/test_*.py | wc -l` -> 40; `grep -lE '^(from|import) src' tests/test_*.py | wc -l` -> 39; `grep -l simorgh tests/test_*.py` -> only test_git_ops.py and test_e2e_cli.py (word mentions, no import); `grep -hE 'def test_' tests/test_*.py | wc -l` -> 881
- `grep -rlE '^(from|import) src' simorgh/ simloader.py sim.sh tools/` -> nothing; `find src -name '*.py' | xargs wc -l` -> 16441; `cat tests/test_*.py | wc -l` -> 11574
- `git log -1 -- src/` -> e23f689 2026-09-09 (src/memory/long_term.py, 4 insertions 2 deletions); `git log -1 -- 'tests/test_*.py'` -> 3371e74 2026-09-06
- simloader.py:529-545 CORE_TESTS lists only tests/simorgh/... paths; simloader.py:552-553 `if all_tests or not paths: return ["tests"]`
- .simorgh_loader/unit_baseline-core.json {"tests": 3348, "seconds": 45.67}; .simorgh_loader/last_unit.txt tail `3348 passed, 16 warnings in 45.08s`; .simorgh_loader/unit_baseline.json {"tests": 5969, "ts": 1789389608} with no seconds field
- .simorgh_loader/decisions.jsonl: 1 of 23 bless records ran 'every test' (sim-good-0004, 5969 tests); the last three (sim-good-0021..0023) each say '3348 tests ran'; last_green.json `"all_tests": false`
- simorgh/verification/config.py:28-31 `_DEFAULT_INVARIANTS = {"src/main.py": [...], "simorgh/execution/": ["verifier.verify("], "simorgh/guardian/": ["Pipeline("]}`; ~/.simorgh/simorgh.toml has no [invariants] override
- simorgh/verification/checks/invariants.py:16-21 `if subject_path.startswith(prefix): missing.extend(s for s in required if s not in new_content)`; checks/__init__.py:20 `InvariantsCheck(),` in ALL_CHECKS; verification/service.py:171 iterates ALL_CHECKS
- `grep -rl 'verifier.verify(' simorgh/execution/` -> 1 file (service.py) of 67 .py files; `grep -rl 'Pipeline(' simorgh/guardian/ | wc -l` -> 1 of 9 .py files
- simorgh/kernel/cli.py:27 `--self-check` flag, :71-74 `_cmd_self_check` -> `run_selfcheck()`; tests/simorgh/integration/test_kernel_boots_all_sixteen_subsystems.py:13 'the CLI's own --self-check (which deliberately uses two small inline' subsystems
- tests/simorgh/integration/test_cli_end_to_end.py:1-25 boots real registry.build_factories() in-process and drives _handle_line; no v2 test spawns `python -m simorgh` as a subprocess (`grep -rn '-m simorgh\|sys.executable' tests/simorgh` shows only docstrings and unrelated fixture uses)
- tests/test_e2e_cli.py:1-9 spawns `python -m src.main` -- the only process-boundary e2e in the repo

**severity adjustment:** lower

**corrected claim:** The 40 tests/test_*.py files (881 tests, 11.5k lines) and src/ (16.4k lines) are a dead v1 tree nothing in simorgh/, simloader.py, sim.sh or tools/ imports, but the default gate already excludes them (CORE_TESTS, 3,348 tests in 45s) and the --all-tests path that would collect them has been used once in 23 blessings; the '~20 minutes' cost is unevidenced. Archiving them is cheap housekeeping, not a medium-severity architectural problem. The materially new issue is the prefix-matched invariant table (verification/checks/invariants.py:16-21): 'simorgh/execution/' requires `verifier.verify(` and 'simorgh/guardian/' requires `Pipeline(`, substrings present in only 1 of 67 and 1 of 9 files respectively, so Verification refuses any self-patch to the other 74 files in those packages -- a latent bug that restricts self-improvement, and worth fixing on its own. A subprocess test of `python -m simorgh --self-check` is reasonable but would only prove the two-inline-subsystem self-check, not the real composition, which an in-process test already covers.

