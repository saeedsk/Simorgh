# refute:correctness:`simorgh status` boots a second full Ker

*Workflow: review · Phase: Refute · Agent id: `aa045559492edd444` · Tool calls: 8*

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
    "title": "`simorgh status` boots a second full Kernel and reports on itself; `trace`/`migrate-v1` ignore the configured ledger backend",
    "kind": "over-engineering",
    "severity": "low",
    "claim": "The status subcommand constructs and boots all 17 subsystems in a throwaway process against the live data dir and, with the default in-memory bus, can never observe the running instance; the trace and migrate subcommands hardcode a jsonl ledger regardless of [ledger].",
    "evidence": [
      "simorgh/kernel/cli.py:229-239 `_cmd_status`: `kernel = Kernel(config); await kernel.boot(); print(json.dumps(kernel.status_snapshot()...)); finally: await kernel.shutdown()`.",
      "simorgh/bus/config.py:30 `backend: str = \"memory\"` and no [bus] section in ~/.simorgh/simorgh.toml; the real liveness path is interface/httpapi.py:290 `/api/status`.",
      "cli.py:246 and :264 `make_ledger({\"backend\": \"jsonl\", ...})` while ledger/config.py:18,46 allows sqlite via [ledger] or SIMORGH_LEDGER_BACKEND."
    ],
    "why_it_matters": "A diagnostic that starts voice, execution (skill scan, MCP), curiosity and the rest for one second to print its own boot state is expensive and misleading, and it is the kind of tool the creator reaches for when something is wrong.",
    "recommendation": "Make `status` an HTTP client of /api/status (fallback: read the last `system` and `metrics:history` events from the ledger without booting anything). Build the ledger mapping for trace/migrate from `_ledger_mapping_for(config, runtime)`.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Read | /Users/saeed/ws/Simorgh/simorgh/kernel/cli.py (from line 180) | 180 181 for sig in (signal.SIGINT, signal.SIGTERM): 182 try: 183 loop.add_signal_handler(sig, stopper.on_signal) 184 except (NotImplementedError, RuntimeError): |
| 2 | Bash | Inspect bus/ledger config, kernel ledger wiring, live toml, and CLI dispatch | """Bus configuration (docs/blueprint/subsystems/01-bus.md section 3.5). Loaded from the `[bus]` section of `simorgh.toml` by the Kernel; every field has a worki |
| 3 | Bash | Locate kernel module, ledger mapping helper, live config, and status command callers | __init__.py __pycache__ api.py bootprogress.py cli.py config.py configcheck.py context.py metrics.py migrate_v1.py README.md registry.py scheduler.py secrets.py |
| 4 | Bash | Read ledger mapping helper, boot, status_snapshot, CLI dispatch, and ledger LOCK handling |  change (`bus/backends/sqlite.py`'s module docstring).""" from simorgh.bus.config import Config as BusConfig return BusConfig.from_mapping(config.section("bus") |
| 5 | Bash | Check ledger lock behaviour, status usage in scripts, argparse options, and prior-review mentions | simorgh/ledger/backends/jsonl.py:20: <root>/LOCK advisory lock taken around each append simorgh/ledger/backends/jsonl.py:75: _MAX_LOCKS = 4096 simorgh/ledger/ba |
| 6 | Bash | Confirm StatusServer scope, subsystem boot in Kernel, bus config default, and prior review coverage |  # anyway). Subscribing this late meant that gauge -- the whole # point of the fix described in its own docstring -- was silently # lost on every single boot (c |
| 7 | Bash | Find StatusServer definition, layers booted, runtime mode, and the HTTP status route | simorgh/kernel/metrics.py:60:class StatusServer: 52:from .metrics import MetricsHistoryWriter, MetricsTable, ProcessMetricsPublisher, StatusServer ---- def _sub |
| 8 | Bash | Read StatusServer snapshot source, HTTP status handler, kernel README on status, and the boot layers | class StatusServer: def __init__( self, *, bus: Bus, clock: Clock, run_id: str, mode: str, state: SystemStateMachine, supervisor: Supervisor, metrics: MetricsTa |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited line checks out against the code today. `_cmd_status` (simorgh/kernel/cli.py:229-239) does `Kernel(config)` -> `await kernel.boot()` -> prints `kernel.status_snapshot()` -> `kernel.shutdown()`. `Kernel.boot()` (simorgh/kernel/service.py:157ff) opens the ledger at the configured data dir and iterates `self._own_layers(factories)` (service.py:347-357), which is `registry.LAYERS` (registry.py:39-46: bus, ledger, cognition, memory, worldmodel, guardian, execution, verification, planning, learning, reflection, curiosity, persona, benchmark, voice, interface, orchestration) filtered only by what factories can build -- so a `status` invocation boots the whole subsystem set in a throwaway process. `status_snapshot()` (service.py:566-567) returns `self._status.snapshot()`, and `StatusServer.snapshot()` (kernel/metrics.py:104-119) enumerates `self._supervisor.services` of that same throwaway Kernel -- it reports on itself, not on any running `simorgh run`. The bus default is `backend: str = "memory"` (bus/config.py:30); the live `~/.simorgh/simorgh.toml` has no `[bus]` and no `[runtime]` section (grep output: only [voice], [interface], [execution], [cognition], [cognition.providers], [cognition.providers.ollama]), so the memory bus is in force and the status process cannot see the running instance's `system.status.request/reply`. `_cmd_trace` (cli.py:246) and `_cmd_migrate_v1` (cli.py:264) both hardcode `make_ledger({"backend": "jsonl", ...})`, while `_ledger_mapping_for` (service.py:76-80) is the helper `Kernel`/`WorkerKernel` use to honour `[ledger]` and `SIMORGH_LEDGER_BACKEND` (ledger/config.py:18,46). Two small extras the finding did not mention: the `--timeout` argument `status` accepts (cli.py:36) is passed to `_cmd_status` but never used (cli.py:229-239), and the help text/docs promise "the current system.status snapshot" (cli.py:35, docs/architecture.md:77), so this is a case of a right design intent (a one-shot liveness query) undermined by the implementation, plus a genuine config-bypass bug for trace/migrate. Not in the known-findings list; no mention in docs/architecture-audit-2026.md or docs/architecture-review-2026-09-18.html. Practical impact is limited: today the live ledger backend IS the jsonl default (no [ledger] section), so trace/migrate happen to hit the right store; the mismatch only bites once someone flips to sqlite as the config claims they can. Severity "low" is appropriate.

### evidence

- /Users/saeed/ws/Simorgh/simorgh/kernel/cli.py:229-239 -- `_cmd_status`: `kernel = Kernel(config)`; `await kernel.boot()`; `print(json.dumps(kernel.status_snapshot(), ...))`; `finally: await kernel.shutdown()`; the `timeout` parameter is never referenced.
- /Users/saeed/ws/Simorgh/simorgh/kernel/cli.py:35-36 -- `sub.add_parser("status", help="print the current system.status snapshot")`, `--timeout` default 2.0 (unused).
- /Users/saeed/ws/Simorgh/simorgh/kernel/service.py:157-163 and :347-357 -- `Kernel.boot()` opens the ledger via `make_ledger(self._ledger_mapping())` and boots every layer from `known_layers(factories)`; `_own_layers` only strips orchestration in local-multi mode.
- /Users/saeed/ws/Simorgh/simorgh/kernel/registry.py:39-46 -- LAYERS lists all 17 subsystems including voice, execution, curiosity, interface.
- /Users/saeed/ws/Simorgh/simorgh/kernel/service.py:566-567 -- `status_snapshot()` returns `self._status.snapshot()`; /Users/saeed/ws/Simorgh/simorgh/kernel/metrics.py:104-119 -- `StatusServer.snapshot()` enumerates `self._supervisor.services` of the same in-process Kernel.
- /Users/saeed/ws/Simorgh/simorgh/bus/config.py:30 -- `backend: str = "memory"  # memory | sqlite | aws`.
- Command: `grep -n "^\[" ~/.simorgh/simorgh.toml` -> `[voice] [interface] [execution] [cognition] [cognition.providers] [cognition.providers.ollama]`; no `[bus]`, `[ledger]`, or `[runtime]` section; `env | grep SIMORGH_LEDGER` prints nothing.
- /Users/saeed/ws/Simorgh/simorgh/kernel/cli.py:246 and :264 -- `make_ledger({"backend": "jsonl", "data_dir": str(config.runtime.data_dir / "ledger")})` in both `_cmd_trace` and `_cmd_migrate_v1`.
- /Users/saeed/ws/Simorgh/simorgh/kernel/service.py:76-80 -- `_ledger_mapping_for(config, runtime)` reads `config.section("ledger")`; /Users/saeed/ws/Simorgh/simorgh/ledger/config.py:18,46 -- default backend jsonl, `SIMORGH_LEDGER_BACKEND` env override, BACKENDS includes sqlite.
- /Users/saeed/ws/Simorgh/simorgh/interface/httpapi.py:290 -- `self.register_route("GET", "/api/status", _status, auth=False)`; :254-264 comment calls it the liveness route.
- /Users/saeed/ws/Simorgh/docs/architecture.md:77 -- `python -m simorgh status      # one-shot system.status snapshot` (documented intent).
- Command: `grep -o "simorgh status[^<]*" docs/architecture-review-2026-09-18.html; grep -n "simorgh status" docs/architecture-audit-2026.md` -> no output (not previously reported).

**severity adjustment:** keep

