# refute:correctness:`contracts` has become a utility package

*Workflow: review · Phase: Refute · Agent id: `a04a19bcfca6e9521` · Tool calls: 6*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "`contracts` has become a utility package with IO and process-global state; the tool registry is module-level",
    "kind": "right-design-undermined",
    "severity": "low",
    "claim": "The package described as the frozen Phase 0 contracts now contains five modules that run git, write log files under a threading.Lock, and read/write simorgh.toml, plus four of the codebase's nine module-level mutable singletons; and orchestration keeps its tool registry in module globals that already caused cross-kernel leakage.",
    "evidence": [
      "grep -l 'subprocess|threading|open(' simorgh/contracts/*.py: checkout.py console.py overheard.py places.py settings.py (5 of 26 modules, 4,588 lines total); overheard.py:68 `_lock = threading.Lock()`; console.py:76 `global _since_check`; places.py:40,51,115 `_cache`.",
      "Module-level mutable state scan (9 hits): contracts/compat.py:25 _TRANSLATORS, contracts/places.py:40 _cache, contracts/registry.py:66 _REGISTRY, contracts/overheard.py:68 _lock, execution/media/androidtv.py:54 _PENDING, orchestration/tools.py:559 _DYNAMIC_TOOLS, :569 _REGISTERED, orchestration/scaffolds.py:35 _UNAVAILABLE, guardian/rules.py:408 _bandit_cache.",
      "orchestration/tools.py:562-569 comment: 'using it as \"what exists\" made every later harness test offer the model nothing ... so one kernel's tools never leak into the next'.",
      "registry.py:7-10: subsystems were 'built concurrently by separate tracks against the frozen Phase 0 contracts'."
    ],
    "why_it_matters": "None of this breaks the bus-only import rule (the matrix shows no subsystem imports another), but it is state and side effects that live outside any Context: invisible to config, to the supervisor, and to the per-subsystem data-dir discipline, and `contracts` is imported by everyone so its IO runs in everyone.",
    "recommendation": "Move checkout/console/overheard/places/settings into a `simorgh/support` (or `platform`) package that the boundaries test treats like contracts; make the Orchestration tool registry an attribute of its Service (or a small object passed via ctx) instead of module globals.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Check contracts modules for IO and module-level state |  26 simorgh/contracts/checkout.py simorgh/contracts/console.py simorgh/contracts/overheard.py simorgh/contracts/places.py simorgh/contracts/settings.py 441 simo |
| 2 | Bash | Read cited IO and state lines in contracts modules |  4588 total --- 11:`git_commit: nothing_to_commit` (`workspace/` is gitignored, so from 18:own test command inside the project's own container, and its git tool |
| 3 | Bash | Check tool registry globals, registry docstring, importers, boundaries test | # Filled at runtime from Execution's `tool.registered` announcements # (`orchestration/service.py::_on_tool_registered`) -- MCP servers, # acquired skills, and  |
| 4 | Bash | Check quote provenance, importers, service cleanup, boundaries test, known findings | --- importers 2 benchmark 4 execution 2 interface 1 memory 1 orchestration 1 verification 2 voice --- service 16:from .tools import forget_registered, note_regi |
| 5 | Bash | Locate quoted phrase, check known reviews, import-time IO, and singleton scan | simorgh/kernel/registry.py:9:built concurrently by separate tracks against the frozen Phase 0 --- known-contracts 69:- **Bus topology enforcement** ([`contracts |
| 6 | Bash | AST scan for module-level empty mutable containers and locks | 8 simorgh/contracts/compat.py:25 _TRANSLATORS simorgh/contracts/registry.py:66 _REGISTRY simorgh/contracts/overheard.py:68 _lock simorgh/orchestration/tools.py: |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The substance holds against the code today: five of the 26 `simorgh/contracts/` modules do real IO and hold process state (checkout runs git via subprocess, console appends a log file with a module-level counter, overheard writes under a module-level threading.Lock, places caches and mutates simorgh.toml's [household] section, settings reads simorgh.toml and writes a hand-off file), an AST scan of module-level empty mutable containers/locks reproduces exactly the nine sites the finding lists (four in contracts), and orchestration's tool registry is still two module globals (_DYNAMIC_TOOLS, _REGISTERED) whose own comment records the cross-kernel leakage and the clear-on-stop workaround (forget_registered() at service.py:240). The boundaries test only enforces that contracts imports stdlib, so nothing stops IO living there. It is not in the known-findings list; the existing reviews mention contracts only for topics.py topology enforcement. Three evidence defects keep it from 'confirmed': (1) '4,588 lines total' is the whole 26-module package, the five IO modules are 1,197 lines; (2) the 'built concurrently by separate tracks against the frozen Phase 0 contracts' quote is from simorgh/kernel/registry.py:9, not contracts/registry.py:7-10 (that file says 'sixteen independently-built subsystems' instead); (3) 'contracts is imported by everyone so its IO runs in everyone' overstates it: importing all five modules performs no IO (verified by import), and only 7 packages import these specific modules, with IO occurring only when their functions are called. The leakage the finding cites is historical (2026-09-07) and now mitigated, but the module-global design that permitted it is unchanged, so 'right design undermined' at low severity is fair.

### evidence

- `grep -lE 'subprocess|threading|open\(' simorgh/contracts/*.py` -> checkout.py console.py overheard.py places.py settings.py (5 of 26 modules); `wc -l` of those five = 1,197 lines; `wc -l simorgh/contracts/*.py | tail -1` = 4588 total for all 26 (finding's 4,588 figure is the whole package, not the five)
- simorgh/contracts/checkout.py:32 `import subprocess`; :181 `git = shutil.which("git")` (runs git)
- simorgh/contracts/console.py:54-56 `_CHECK_EVERY = 200` / `_since_check = 0`; :76 `global _since_check`; :59 `console_log_path()` -> settings_home()/interface/console.log written by `record()`
- simorgh/contracts/overheard.py:68 `_lock = threading.Lock()`
- simorgh/contracts/places.py:40 `_cache: tuple[float, dict] | None = None`; :51 `global _cache`; :115-116 `global _cache; _cache = None`; docstring: reads `[household]` from the settings file, cached on mtime
- simorgh/contracts/settings.py:22 `import tomllib`; :42-47 `write_handoff()` writes a JSON hand-off file; :162-170 `config_path()` resolves simorgh.toml
- AST scan of module-level empty mutable containers/locks across simorgh/ (excluding tests) -> 8 hits: contracts/compat.py:25 _TRANSLATORS, contracts/registry.py:66 _REGISTRY, contracts/overheard.py:68 _lock, orchestration/tools.py:559 _DYNAMIC_TOOLS, :569 _REGISTERED, orchestration/scaffolds.py:35 _UNAVAILABLE, guardian/rules.py:408 _bandit_cache, execution/media/androidtv.py:54 _PENDING; plus places.py:40 _cache (None-initialised) = the finding's nine
- simorgh/orchestration/tools.py:561-568 comment: 'using it as "what exists" made every later harness test offer the model nothing (full-suite-only failures, 2026-09-07). The Orchestration service fills this on each announcement and empties it when it stops, so one kernel's tools never leak into the next.'; simorgh/orchestration/service.py:16 imports forget_registered/note_registered; :169,:226 note_registered(...); :240 forget_registered()
- Quote 'built concurrently by separate tracks against the frozen Phase 0 contracts' is at simorgh/kernel/registry.py:8-10, NOT simorgh/contracts/registry.py:7-10 (that file's lines 5-10 say 'across sixteen independently-built subsystems')
- `python3 -c 'import simorgh.contracts.checkout, ...console, ...overheard, ...places, ...settings'` -> 'imports ok, no exception' (no import-time IO); importers of these five modules by package: benchmark 2, execution 4, interface 2, memory 1, orchestration 1, verification 1, voice 2 (not 'everyone')
- tests/simorgh/test_module_boundaries.py:7 rule 2 '`simorgh.contracts` imports only the standard library (and itself)'; :67-70 `_is_allowed` — the boundary test constrains imports only, not IO or state
- Known-findings check: docs/architecture-third-opinion-2026-09-18.md:69 mentions contracts only for topics.py topology enforcement; docs/architecture-review-2026-09-18.html has no sentence pairing 'contracts' with IO/state/global/utility — finding is not already reported

**corrected claim:** Five of the 26 modules in simorgh/contracts/ (checkout, console, overheard, places, settings; 1,197 of the package's 4,588 lines) perform IO and hold process-global state: checkout.py shells out to git, console.py appends a log file with a module-level counter, overheard.py writes under a module-level threading.Lock, places.py caches and rewrites the [household] section of simorgh.toml, and settings.py reads simorgh.toml and writes a hand-off file. Four of the codebase's nine module-level mutable singletons live in contracts (compat._TRANSLATORS, registry._REGISTRY, overheard._lock, places._cache). The boundaries test only requires contracts to import stdlib, so it permits this. None of this runs at import time and only seven packages import these five modules, so the cost is state outside any Context rather than IO in every subsystem. Orchestration's tool registry remains two module globals (tools.py:559 _DYNAMIC_TOOLS, :569 _REGISTERED); the cross-kernel leakage they caused (2026-09-07) is now mitigated by forget_registered() on service stop (service.py:240), but the module-global design that permitted it is unchanged. (The 'frozen Phase 0 contracts' quote is from kernel/registry.py:9, not contracts/registry.py.)

**severity adjustment:** keep

