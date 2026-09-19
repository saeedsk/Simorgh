# refute:correctness:11.5k lines of tests and a verification

*Workflow: review · Phase: Refute · Agent id: `a78999a8e6d18b129` · Tool calls: 7*

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
| 1 | Bash | Count test files, src imports, line counts and last commits | --- top-level test files: 40 --- from src in tests/test_*.py: 39 --- 'simorgh' in tests/test_*.py: 2 --- 'from src' / 'import src' under simorgh/, simloader.py, |
| 2 | Bash | Check src import sites, simloader test selection, invariants and e2e test | --- src matches in simorgh/: simorgh/guardian/config.py:43:# Ported verbatim from src/orchestrator/audit.py's _DENYLIST_PATTERNS -- simorgh/execution/pathsafety |
| 3 | Bash | Check pytest config, e2e spawns, invariant usage and prior reviews | --- pytest config: --- conftest at tests/: --- process-boundary spawns of simorgh in tests/simorgh: tests/simorgh/test_simloader.py:3:`simloader.py` is delibera |
| 4 | Bash | Check invariant matching rule, baselines, prior review mentions, and subprocess e2e tests | --- invariant usage anywhere: simorgh/verification/checks/__init__.py:5:from .invariants import InvariantsCheck, invariant_violations simorgh/verification/check |
| 5 | Bash | Read invariant rule, core baseline, CORE_TESTS and subprocess e2e tests | --- invariants.py: """`invariants`: a generalization of `check_main_py_invariants` from `src/orchestrator/self_patch.py`. A narrow, cheap substring check, not a |
| 6 | Bash | Confirm invariant check is wired, last gate timing, and no live src references | --- InvariantsCheck registration: --- self_patch verify subject carries path: (eval):1: no matches found: simorgh/orchestration/self_patch*.py --- last_green: { |
| 7 | Bash | Check whether the invariants check is actually run and fed a self-patch path | --- how checks are registered: simorgh/verification/checks/__init__.py:5:from .invariants import InvariantsCheck, invariant_violations simorgh/verification/chec |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every load-bearing part of the claim holds against the code today. The top-level tests/test_*.py files import only src/ (39 of 40 contain `from src`; the only 'simorgh' mentions are in strings/test names), and nothing under simorgh/, simloader.py or sim.sh imports src (the two grep hits are docstring/comment 'ported from src/...' notes in guardian/config.py:43 and execution/pathsafety.py:1). simloader.gate_selection (simloader.py:547-554) returns ["tests"] under --all-tests, so the whole v1 suite is inside the 'all' baseline (unit_baseline.json: 5969 tests) while the core baseline is 3348 tests in ~45s (unit_baseline-core.json, last_unit.txt: '3348 passed ... in 45.08s'). The creator already knows the v1 code is excluded from core (simloader.py:524-528 comment names 'the v1 code'), but it is still carried by --all-tests and the all-baseline. verification/config.py:29 still lists "src/main.py" as an invariant target, and InvariantsCheck is live: it is in ALL_CHECKS (checks/__init__.py:20) and runs for any subject with a path and candidate (checks/invariants.py:28-31). The evidence item about the "simorgh/execution/" prefix is also correct and is arguably a separate genuine bug: invariant_violations uses startswith on the prefix (invariants.py:16-21) and requires `verifier.verify(` in the candidate, but only simorgh/execution/service.py contains that string, so a self-patch to any other execution/ file would be refused by the invariants check. No test in tests/simorgh spawns `python -m simorgh` (subprocess uses there are git or mocked; test_simloader imports simloader via importlib), so tests/test_e2e_cli.py (spawning `python -m src.main`) is indeed the only process-boundary e2e. None of the three prior review docs or module-map.md mention src/ at all (grep count 0), so this is not already known. Minor inaccuracies: 40 files not 41, 881 `def test_` definitions not 887 (pytest may collect slightly differently), and the '~20 minutes' for --all-tests was not verified (last_green.json shows only core runs). Classification: (a) maintenance weight that is over-built for the running system, plus one (c) genuine bug in the execution/ invariant prefix.

### evidence

- `ls tests/test_*.py | wc -l` -> 40; `grep -l 'from src' tests/test_*.py | wc -l` -> 39; `grep -l simorgh tests/test_*.py` -> only test_e2e_cli.py (docstring/marker string) and test_git_ops.py (test names)
- `grep -rlE 'from src|import src' simorgh/ simloader.py sim.sh` -> simorgh/guardian/config.py:43 ('# Ported verbatim from src/orchestrator/audit.py...') and simorgh/execution/pathsafety.py:1 (docstring 'ported from src/cognition/tool_protocol.py') -- comments only, no live import
- `find src -name '*.py' | xargs wc -l` -> 16441 total; `wc -l tests/test_*.py` -> 11574 total; `git log -1 -- src/` -> 2026-09-09 e23f689; `git log -1 -- 'tests/test_*.py'` -> 2026-09-06 3371e74
- simloader.py:547-554 gate_selection: `if all_tests or not paths: return ["tests"]`; simloader.py:524-528 comment: 'The feature suites (... the v1 code) are not here ... `--all-tests` runs everything.'
- .simorgh_loader/unit_baseline.json -> {"tests": 5969}; .simorgh_loader/unit_baseline-core.json -> {"tests": 3348, "seconds": 45.67}; last_unit.txt tail: '3348 passed, 16 warnings in 45.08s'
- simorgh/verification/config.py:28-32 `_DEFAULT_INVARIANTS = {"src/main.py": ["AuditGate(", "audit_gate.review(", "apply_proposal("], "simorgh/execution/": ["verifier.verify("], "simorgh/guardian/": ["Pipeline("]}`
- simorgh/verification/checks/invariants.py:16-21 `for prefix, required in table.items(): if subject_path.startswith(prefix): missing.extend(...)`; checks/__init__.py:20 `InvariantsCheck(),` in ALL_CHECKS; verification/service.py:171 runs every check whose applies() is true
- `grep -rl 'verifier.verify(' simorgh/execution/` -> simorgh/execution/service.py only (so the prefix rule would refuse a patch to any other execution/ file)
- tests/test_e2e_cli.py:1-2 docstring: 'spawn the real `python -m src.main` process'; `grep -rn '"-m", "simorgh' tests/simorgh` -> no matches; subprocess.run calls in tests/simorgh are all git invocations or mocked Popen
- `grep -ciE '\bsrc/' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md docs/module-map.md` -> 0 for each (not previously reported)
- simorgh/kernel/cli.py:27 `parser.add_argument("--self-check", ...)` and :376-377 -- the recommended `python -m simorgh --self-check` target exists
- Counted `def test_` in tests/test_*.py -> 881 (claim said 887; file count claim of 41 is actually 40)

**severity adjustment:** keep

**corrected claim:** The 40 top-level tests/test_*.py files (~881 test functions, 11,574 lines) import only src/ (16,441 lines, 72 tracked files), which nothing under simorgh/, simloader.py or sim.sh imports (only two 'ported from src/...' comments). The core gate deliberately excludes them (simloader.py:524-528 names 'the v1 code'), but `--all-tests` still returns ["tests"] (simloader.py:552) so they sit in the 'all' baseline (5969 vs core 3348), and verification/config.py:29 still carries a src/main.py invariant. Separately, the "simorgh/execution/" invariant requiring `verifier.verify(` matches only execution/service.py, so InvariantsCheck (live in ALL_CHECKS) would refuse a self-patch to any other execution/ file -- a genuine bug worth its own finding. tests/test_e2e_cli.py is the only test that spawns a real process of the agent, and it spawns `python -m src.main`; no test spawns `python -m simorgh`. The '~20 minutes' for --all-tests is not verified by any file in .simorgh_loader/.

