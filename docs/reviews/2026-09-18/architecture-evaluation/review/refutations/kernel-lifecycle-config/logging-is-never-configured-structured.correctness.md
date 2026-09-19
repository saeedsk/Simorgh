# refute:correctness:Logging is never configured: structured

*Workflow: review · Phase: Refute · Agent id: `a17747a30e13560bb` · Tool calls: 5*

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
| 1 | Bash | Grep for logging configuration and runtime log settings | ---setLevel--- simorgh/cognition/providers/gemini.py:91: logging.getLogger("google_genai").setLevel(logging.ERROR) simorgh/execution/media/cast.py:109: logging. |
| 2 | Bash | Read logger wrapper, runtime config and log call sites | """Builds the `Context` handed to one subsystem's `Service.start()` (docs/blueprint/subsystems/03-kernel.md section 5). Each subsystem gets its own `BusClient`  |
| 3 | Bash | Check logger call sites, runtime field reads, docs mentions, and ledger for a log stream | === ctx.logger / self._logger / self._log usage counts === 32 45 simorgh/benchmark/service.py:96: ctx.logger.info("benchmark.started", suites=len(datasets_mod.S |
| 4 | Bash | Confirm Python default log routing, check entrypoints and TUI stderr handling, read blueprint spec | === python default behaviour === WARN-shown? root handlers: [] level: 30 === other entrypoints === (eval):5: no matches found: simorgh/interface/tui/*.py __init |
| 5 | Bash | Check entry scripts for logging setup, ledger activity stream, and _cmd_run location | === any logging config anywhere outside simorgh/ (entry scripts) === === ledger 'activity' stream writer === simorgh/ledger/streams.py:22: "activity": "orchestr |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every element of the claim is true of the code today. (1) No logging configuration exists: `grep -rnE 'basicConfig|dictConfig|addHandler|StreamHandler|FileHandler|logging\.config' --include='*.py' simorgh/ simloader.py tools/` returns nothing; the only `logging` calls that touch levels are two third-party silencers (gemini.py:91, cast.py:109). simorgh/kernel/cli.py (which holds `_cmd_run` at line 172) does not import logging at all. (2) `_StdlibLogger` (simorgh/kernel/context.py:26-51) routes to `logging.getLogger("simorgh.<name>")`; with no handler attached, Python's default root logger (level WARNING=30, handlers []) drops `.info/.debug` and only WARNING+ reach stderr via `lastResort` -- verified with `python3 -c` (INFO line absent, WARN line printed, `root handlers: [] level: 30`). There are 32 `.logger.info/.debug(` call sites across subsystems (e.g. benchmark/service.py:96, interface/service.py:390, ledger/service.py:66, planning/service.py:185) that are therefore silently discarded, versus 45 `.warning/.error` sites that do reach stderr. (3) `log_level` and `log_to_ledger` are parsed in simorgh/kernel/config.py:121-122 into RuntimeConfig (api.py:48-49) and never read anywhere else: `grep -rnE '\.log_level|\.log_to_ledger' simorgh/ simloader.py` returns only the config.py parse lines. The only other mention of `log_to_ledger` is the context.py:30 docstring promising the Kernel service 'wires it on top', which nothing does; no `.log` file exists under ~/.simorgh and no log stream exists in the ledger. The blueprint (docs/blueprint/subsystems/03-kernel.md:141, 200-201) specifies the logger 'routes to ledger activity/stdout per config', so this is a designed slot with one side implemented -- the project's known 'unconnected wire' shape, but this specific instance (logging never configured; two inert runtime fields) is not in the known-findings list: `grep -niE 'logging|log_level|log_to_ledger|basicConfig'` over docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html and docs/architecture-third-opinion-2026-09-18.md returns nothing. Classification: (b) design is right (structured logger + ledger sink per config), implementation undermines it -- the wire was never connected. Severity 'low' is fair: the creator does have the ledger, traces and metrics as observability, and WARNING+ still surfaces on stderr; but the recommendation (one basicConfig with a rotating file handler in `_cmd_run`, plus either implementing or deleting `log_to_ledger`) is correct and cheap.

### evidence

- grep -rnE 'basicConfig|dictConfig|addHandler|StreamHandler|FileHandler|logging\.config' --include='*.py' simorgh/ simloader.py tools/ -> no output; only setLevel hits are simorgh/cognition/providers/gemini.py:91 and simorgh/execution/media/cast.py:109 (third-party silencers)
- simorgh/kernel/context.py:26-51 `_StdlibLogger` wraps logging.getLogger(f"simorgh.{name}") with no handler; docstring line 29-31 says log_to_ledger is 'a *separate*, additive path the Kernel service wires on top'
- python3 -c "import logging; l=logging.getLogger('simorgh.x'); l.info('INFO-dropped?'); l.warning('WARN-shown?'); print(logging.getLogger().handlers, logging.getLogger().level)" -> prints only 'WARN-shown?' then '[] 30'
- grep -rnE '\.logger\.(info|debug)\(' --include='*.py' simorgh/ | wc -l -> 32 discarded call sites (e.g. simorgh/benchmark/service.py:96, simorgh/interface/service.py:390, simorgh/ledger/service.py:66, simorgh/planning/service.py:185); warning/error sites -> 45
- grep -rnE '\.log_level|\.log_to_ledger' --include='*.py' simorgh/ simloader.py -> only simorgh/kernel/config.py:121-122 (parse into RuntimeConfig); defaults at simorgh/kernel/api.py:48-49 (log_level='info', log_to_ledger=True)
- simorgh/kernel/cli.py: `grep -n 'import logging\|logging\.'` -> no output; `_cmd_run` defined at line 172
- docs/blueprint/subsystems/03-kernel.md:141 'logger: structured; routes to ledger activity/stdout per config' and :200-201 log_level/log_to_ledger in [runtime] -- the designed contract that is unimplemented
- ls ~/.simorgh/*.log -> no matches; ~/.simorgh/ledger/ contains blobs heads idem index.json LOCK snapshots streams, no log stream
- grep -niE 'logging|log_level|log_to_ledger|basicConfig' docs/architecture-audit-2026.md docs/architecture-review-2026-09-18.html docs/architecture-third-opinion-2026-09-18.md -> no output (not previously reported)

**severity adjustment:** keep

