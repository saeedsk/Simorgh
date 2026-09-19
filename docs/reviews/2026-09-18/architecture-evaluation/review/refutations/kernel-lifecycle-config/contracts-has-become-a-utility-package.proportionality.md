# refute:proportionality:`contracts` has become a utility package

*Workflow: review · Phase: Refute · Agent id: `a4e2dc7dd1c7e4d9b` · Tool calls: 4*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "kernel-lifecycle-config". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Verify contracts package IO modules and module-level state citations |  26 simorgh/contracts/checkout.py simorgh/contracts/console.py simorgh/contracts/overheard.py simorgh/contracts/places.py simorgh/contracts/settings.py 441 simo |
| 2 | Bash | Check package size, tool registry comment, who imports the IO modules, and boundaries test |  4588 --- # acquired skills, and open-source adapters (`execution/external.py`) # become routable without a hand edit here. A hand-written entry above # always  |
| 3 | Bash | Check importers of the five modules, import-time side effects, boundaries test, and registry lifecycle | checkout: benchmark execution verification console: execution interface overheard: execution voice places: execution orchestration settings: contracts execution |
| 4 | Bash | Check registry lifecycle in the service and IO call sites in the five modules | simorgh/orchestration/service.py:16:from .tools import forget_registered, note_registered, register_tool_policy simorgh/orchestration/service.py:36: topics.PERC |

## Structured reply

**refuted:** False

**verdict:** partly-true

**corrected claim:** Five of the 26 modules in simorgh/contracts (checkout, console, overheard, places, settings; 1,197 lines, not 4,588 -- that figure is the whole package) do IO on call: git subprocesses, an append-only log under a Lock, simorgh.toml read/write. None of them is loaded by `import simorgh.contracts`, and none has an import-time side effect beyond `_lock = threading.Lock()` and `_cache = None`, so the claim that "its IO runs in everyone" is false. They live in contracts because each is shared by 2-5 packages (settings by 5, checkout by benchmark/execution/verification) and test_module_boundaries.py:67-70 makes contracts the only package everyone may import. The Orchestration tool registry is module-level, but the cross-kernel leakage the finding cites was already fixed: service.py:240 calls forget_registered() on stop, which clears `_REGISTERED` (tools.py:603-604). What is actually stale is the contracts/__init__.py docstring ("no logic that belongs to a subsystem"), i.e. a documentation/naming drift, not an architectural defect.

**reasoning:** The raw observations check out (five IO modules, module-level singletons at the cited lines, the tools.py comment), but the two load-bearing consequences do not. (1) "contracts is imported by everyone so its IO runs in everyone": `python3 -c "import simorgh.contracts; ..."` shows none of checkout/console/overheard/places/settings is imported by the package; the only module-level statements are a Lock and a None cache; all IO happens inside functions called by a specific subsystem that wanted it. (2) The registry "already caused cross-kernel leakage": the comment at tools.py:562-569 describes a 2026-09-07 bug and its fix -- service.py:240 `forget_registered()` on stop, tools.py:603-604 `_REGISTERED.clear()`. The finding cites the fix as if it were the problem. At the scale lens: production runs one Kernel per process (kernel/service.py:108; only tests build several), so a module-level set with clear-on-stop is adequate; converting it to a Service attribute means threading ctx into session.py:32/762 and every unit test that fills `_DYNAMIC_TOOLS` directly, for no behavioural gain. The `simorgh/support` move is cheap (rename + one allow-rule in test_module_boundaries.py:_is_allowed) but purely cosmetic: the boundaries rule already forbids subsystem-to-subsystem imports, so a shared helper has to live in the one universally importable package whatever it is called. The real, small defect is that contracts/__init__.py:1-13 still says the package holds "no logic that belongs to a subsystem" while five helper modules do; fixing the docstring (or the rename) is a housekeeping item, not a design finding.

### evidence

- grep -lE 'subprocess|threading|open\(' simorgh/contracts/*.py -> checkout.py console.py overheard.py places.py settings.py (5 of 26); wc -l of those five = 1,197 lines; cat simorgh/contracts/*.py | wc -l = 4,588 (whole package -- the finding's figure)
- python3 -c 'import sys, simorgh.contracts; print([m for m in sys.modules if m.startswith("simorgh.contracts.") and any(x in m for x in ("checkout","console","overheard","places","settings"))])' -> none of the five loaded
- grep -nE '^(subprocess|_lock|_cache|with open|open\()' over the five modules -> only places.py:40 `_cache: ... = None` and overheard.py:68 `_lock = threading.Lock()`; all subprocess/open calls are inside functions (checkout.py:187-190,232-235,302-306; overheard.py:112; settings.py:222; console.py:82)
- Importers per module (grep over simorgh/): checkout <- benchmark, execution, verification; console <- execution, interface; overheard <- execution, voice; places <- execution, orchestration; settings <- contracts, execution, interface, memory, voice
- tests/simorgh/test_module_boundaries.py:67-70: `if target_pkg == "contracts": return True  # everyone may import contracts`; `if importer_pkg in {"contracts","bus","ledger"}: return False` -- subsystems may not import each other, so contracts is the only home for a shared helper
- simorgh/contracts/__init__.py:1-13 docstring: 'No logic that belongs to a subsystem, no imports beyond the standard library' -- the stale statement
- simorgh/orchestration/service.py:16 imports forget_registered; service.py:240 `forget_registered()` on stop; tools.py:603-604 `def forget_registered(): _REGISTERED.clear()` -- the leakage described in tools.py:562-569 is already fixed
- simorgh/orchestration/session.py:32,762 import and call `known_tools()` from the module -- the recommendation would require plumbing ctx into the session and rewriting the tests that fill `_DYNAMIC_TOOLS` directly
- grep 'class Kernel' simorgh/kernel/*.py -> kernel/service.py:108 only; no production code constructs more than one Kernel per process

**severity adjustment:** lower

