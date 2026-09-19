# refute:proportionality:Logging is never configured: structured

*Workflow: review · Phase: Refute · Agent id: `ae92e31327dcac919` · Tool calls: 4*

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
    "title": "Logging is never configured: structured INFO logs are dropped and [runtime] log_level / log_to_ledger are inert",
    "kind": "missing",
    "severity": "low",
    "claim": "No code calls logging.basicConfig/dictConfig or attaches a handler, so `_StdlibLogger.info/debug` from every subsystem is discarded by Python's default root logger and only WARNING+ reach stderr via the last-resort handler; the documented `log_to_ledger` path is not wired.",
    "evidence": [
      "grep -rn --include='*.py' 'basicConfig|dictConfig|addHandler|StreamHandler|FileHandler' simorgh/: only two third-party setLevel calls (cognition/providers/gemini.py:91, execution/media/cast.py:109).",
      "simorgh/kernel/context.py:26-31 `_StdlibLogger` docstring: 'section 4's log_to_ledger is a *separate*, additive path the Kernel service wires on top' -- grep 'log_to_ledger' outside kernel/config.py and kernel/api.py: only that docstring; api.py:48-49 defaults log_level='info', log_to_ledger=True."
    ],
    "why_it_matters": "When something goes wrong the creator has the ledger and the TUI but no log; and two runtime settings that look like the knob for it do nothing.",
    "recommendation": "One `logging.basicConfig(level=runtime.log_level.upper(), handlers=[RotatingFileHandler(data_dir/'simorgh.log')])` in `_cmd_run`, and either implement log_to_ledger as a WARNING+ handler that appends to a `log` stream or delete the field.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Search for logging configuration and runtime log settings | ---log_to_ledger--- simorgh/kernel/config.py:82: "stop_grace_s": float, "allow_backend_fallback": bool, "log_level": str, "log_to_ledger": bool, simorgh/kernel/ |
| 2 | Bash | Read logger context, runtime config, log usage counts, and runtime setup | """Builds the `Context` handed to one subsystem's `Service.start()` (docs/blueprint/subsystems/03-kernel.md section 5). Each subsystem gets its own `BusClient`  |
| 3 | Bash | Count logger calls by level, check run path for logging setup, config, tests, and alternative observability | === logger usages by level (ctx.logger / self._log etc) === 2 _logger.debug( 2 _logger.error( 5 _logger.info( 15 _logger.warning( 32 logger.info( 51 logger.warn |
| 4 | Bash | Confirm runtime log fields are never read, inspect root logger state, and list ledger streams | === attribute reads of runtime log fields === simorgh/kernel/config.py:121: log_level=str(section.get("log_level", RuntimeConfig.log_level)), simorgh/kernel/con |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every factual element of the claim checks out against the code. (1) No handler or logging configuration exists anywhere in simorgh/, sim.sh or simloader.py: `grep -rnE 'basicConfig|dictConfig|addHandler|StreamHandler|FileHandler|lastResort'` returns nothing. (2) Importing simorgh.kernel.cli and simorgh.kernel.service leaves the root logger with `handlers []`, level WARNING, and the `simorgh.kernel` logger at effective level WARNING, so `_StdlibLogger.info/debug` (simorgh/kernel/context.py:42-46) are discarded and only WARNING+ reach stderr through `logging.lastResort`. (3) `log_level` and `log_to_ledger` are parsed in simorgh/kernel/config.py:121-122 into RuntimeConfig (simorgh/kernel/api.py:48-49) and never read again: the only attribute accesses of `.log_level` / `.log_to_ledger` in the whole tree are those two constructor lines. The context.py:30 docstring promises the Kernel service "wires on top" a log_to_ledger path; nothing does. This is the project's documented "unconnected wire" shape, instance (c) a genuine small bug plus a dead config field. Skeptic lens on proportionality: the practical loss is small and the severity "low" is right. There are only ~39 info/debug call sites in 87k lines (5 `_logger.info`, 2 `_logger.debug`, 32 `logger.info`, spread one-per-subsystem), versus ~70 warning/error sites that DO reach stderr today, and the system's real observability is the ledger (118,215 stream files under ~/.simorgh/ledger/streams) plus the bus trace/metrics writers. So the creator is not blind, just missing the INFO tier. The recommendation is a handful of lines in `_cmd_run` (simorgh/kernel/cli.py:172) and is not disproportionate; the "delete the field" alternative is equally cheap. Not already in the known-findings list. One nuance to the wording: "from every subsystem" overstates how much INFO logging exists; the concrete loss is ~39 sites.

### evidence

- grep -rnE --include='*.py' 'basicConfig|dictConfig|addHandler|StreamHandler|FileHandler|lastResort' simorgh/ sim.sh simloader.py -> no output
- python3 -c 'import logging, simorgh.kernel.cli, simorgh.kernel.service; ...' -> root handlers [] level WARNING; lastResort <_StderrHandler <stderr> (WARNING)> 30; simorgh.kernel effective WARNING
- grep -rnE '\.log_level|\.log_to_ledger' simorgh/ simloader.py -> only simorgh/kernel/config.py:121-122 (the parse); no consumer
- simorgh/kernel/api.py:48-49: log_level: str = "info"; log_to_ledger: bool = True
- simorgh/kernel/context.py:26-31 docstring: 'section 4's log_to_ledger is a *separate*, additive path the Kernel service wires on top' -- no such wiring exists; grep 'log_to_ledger' hits only config.py, api.py and this docstring
- simorgh/kernel/context.py:42-46: debug/info route to self._logger.debug/info with no handler installed
- sed -n 172,260p simorgh/kernel/cli.py | grep logging -> nothing; no 'import logging' in kernel/cli.py, kernel/service.py, simloader.py
- logger call sites by level: 2 _logger.debug, 5 _logger.info, 32 logger.info (13 subsystems, ~1-3 each) vs 15 _logger.warning, 51 logger.warning, 2 _logger.error -> WARNING+ still reach stderr; INFO tier (~39 sites) is lost
- ~/.simorgh/simorgh.toml has no [runtime] log_* keys (grep 'log' returns nothing); no ~/.simorgh/*.log or logs/ directory exists
- ls ~/.simorgh/ledger/streams | wc -l -> 118215 (the ledger, not logging, is the system's actual observability path)
- docs/blueprint/subsystems/03-kernel.md:200-201 documents log_level = "info" / log_to_ledger = true as runtime settings

**severity adjustment:** keep

**corrected claim:** No code configures Python logging (no basicConfig/dictConfig/handler anywhere in simorgh/, sim.sh or simloader.py), so the ~39 info/debug call sites behind `_StdlibLogger` are discarded and only the ~70 warning/error sites reach stderr via logging.lastResort. `[runtime] log_level` and `log_to_ledger` are parsed into RuntimeConfig (kernel/config.py:121-122, kernel/api.py:48-49) but never read by anything; the context.py:30 docstring's promised log_to_ledger wiring does not exist. Practical impact is limited because the ledger and bus trace/metrics carry the system's real observability; the fix is a few lines in `_cmd_run` or deleting the two dead fields.

