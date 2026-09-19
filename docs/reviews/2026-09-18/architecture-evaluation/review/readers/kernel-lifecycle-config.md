# read:kernel-lifecycle-config

*Workflow: review · Phase: Read · Agent id: `abd7043be6f35c8e9` · Tool calls: 52*

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
  
  
  CONCERN: composition root, lifecycle, configuration, and the boot/rollback harness.
  Read simorgh/kernel/ (kernel.py or service.py, registry.py, config.py, secrets.py, selfcheck.py, cli.py, ticks/scheduler), simloader.py, sim.sh, simorgh/__main__.py, and ~/.simorgh/simorgh.toml (redact secrets mentally; do not print secrets).
  Questions: How does config reach subsystems, and how many subsystems actually read their config section (a memory note claims 12 subsystems ignore their config -- verify today by grepping for how each Service consumes ctx.config)? How is shutdown handled (there was an os._exit hard-exit path -- is that a sign of a lifecycle design problem)? How are threads vs asyncio mixed (grep to_thread, threading.Thread, run_in_executor) and is there a coherent concurrency model? Is the bootloader's gate (running the test suite on boot) a sound design, what does it cost in boot time, what does it protect against and what does it not? Does the self-check prove what it claims? Are there global singletons/module-level state that break the "subsystem talks only via bus" story? Evaluate the lifecycle design.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | List kernel package files with line counts | __init__.py __pycache__ api.py bootprogress.py cli.py config.py configcheck.py context.py metrics.py migrate_v1.py README.md registry.py scheduler.py secrets.py |
| 2 | Bash | Read the Kernel service module | <persisted-output> Output too large (39.7KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 3 | Bash | Read registry, config, context, api, main and sim.sh | <persisted-output> Output too large (34.3KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 4 | Bash | Read cli, selfcheck, and secrets modules | <persisted-output> Output too large (39.1KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 5 | Read | /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/tool-results/bqh3sdpr2.txt | 1 1 """`Kernel`: the composition root itself, wired up (docs/blueprint/ 2 2 subsystems/03-kernel.md section 5.1). Boots config -> secrets -> Ledger 3 3 -> Bus(p |
| 6 | Read | /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/tool-results/bmss054le.txt | 1 1 """The one place subsystems are named (docs/blueprint/subsystems/03-kernel.md 2 2 sections 3.4/5). `02-system-architecture.md` section 4 rule 4 permits 3 3  |
| 7 | Read | /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/tool-results/baurb3gn2.txt | 1 1 """`python -m simorgh …` (docs/blueprint/subsystems/03-kernel.md sections 2 2 3.5/5/10). Subcommands are thin: they either boot the Kernel and run 3 3 until |
| 8 | Bash | Read supervisor, configcheck and state modules | <persisted-output> Output too large (35.2KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 9 | Bash | Read the simloader bootloader | <persisted-output> Output too large (57.9KB). Full output saved to: /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/t |
| 10 | Bash | Read the live config (secrets redacted) and inspect data dir | [voice] barge_in = false keep_audio = true vad_sensitivity = "high" barge_in_calibrate_ms = 1200 barge_in_speech_ms = 350 barge_in_ratio = 2.8 min_confidence =  |
| 11 | Read | /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/tool-results/bg2v24pbz.txt | 1 1 """Subsystem lifecycle: start in dependency order, poll health, restart 2 2 crashed services with backoff, and give up (`down`) past a restart 3 3 budget (d |
| 12 | Read | /Users/saeed/.claude/projects/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/tool-results/bse7wrehl.txt | 1 1 #!/usr/bin/env python3 2 2 """The Sim loader: a bootloader for a program that edits its own source. 3 3 4 4 The creator, 2026-09-07: "at start up we should  |
| 13 | Bash | Check how each Service consumes ctx.config | == bus (simorgh/bus/service.py): 0 hits == ledger (simorgh/ledger/service.py): 2 hits 59: if self._config_from_caller is None and ctx.config: 60: self._adopt(Co |
| 14 | Bash | Count and locate thread/asyncio mixing primitives | == to_thread (eval):1: no matches found: --include=*.py 0 == threading.Thread (eval):1: no matches found: --include=*.py 0 == run_in_executor (eval):1: no match |
| 15 | Bash | Find who drives the supervisor health poll and restart | == poll_once callers (eval):1: no matches found: --include=*.py == supervisor._restart callers / re-start (eval):1: no matches found: --include=*.py |
| 16 | Bash | Read scheduler and metrics headers |  1 """Turns time and human activity into messages (docs/blueprint/ 2 subsystems/03-kernel.md section 5.5). The Kernel does not know or care 3 whether there is w |
| 17 | Bash | Inspect loader notes, baselines, decisions and known-good tags | == loader notes total 144 drwxr-xr-x 10 saeed staff 320 Sep 18 14:00 . drwxr-xr-x 34 saeed staff 1088 Sep 18 17:34 .. -rw-r--r-- 1 saeed staff 18 Sep 17 02:54 . |
| 18 | Bash | Locate module-level mutable singletons and global statements | == module-level mutable state (assignments at col 0 of dict/list/set/None with underscore) (eval):1: no matches found: --include=*.py 0 (eval):1: no matches fou |
| 19 | Bash | Count thread and asyncio mixing primitives per package | 138 asyncio.to_thread 1 threading.Thread( 1 run_in_executor 3 ThreadPoolExecutor 5 run_coroutine_threadsafe 4 call_soon_threadsafe 0 new_event_loop 7 asyncio.ru |
| 20 | Bash | Find who drives supervisor health polling and restart | == poll_once / _health_task callers (whole repo incl tests) tests/simorgh/integration/test_guardian_down_autopauses.py:8:reports `down`, driven through the real |
| 21 | Bash | Locate module-level mutable state and global statements | == module-level mutable singletons 9 simorgh/contracts/compat.py:25:_TRANSLATORS: dict[tuple[str, int, int], Translator] = {} simorgh/contracts/places.py:40:_ca |
| 22 | Bash | Check auto-approve env reader, loader notes consumer, config pattern, and REPL threading | == SIMORGH_GUARDIAN_AUTO_APPROVE readers simorgh/execution/security/tools.py:192: raw_env = (self._env.get("SIMORGH_GUARDIAN_AUTO_APPROVE") or "").strip() simor |
| 23 | Bash | Analyse the loader's decision history for gate usage and rollbacks | == gate decisions timeline total decisions: 99 first: 2026-09-14 last: 2026-09-18 Counter({'gate_skipped': 34, 'restart': 24, 'blessed': 20, 'gate_reused': 7, ' |
| 24 | Bash | List headings from the prior reviews to avoid repeating them | == known findings in prior reviews (headings) 1:# Simorgh Architectural Audit & Roadmap (2026) 4:## 1. Executive Summary 7:## 2. Architectural Strengths & Merit |
| 25 | Bash | Check how status health is computed and whether health polling has a live driver | == StatusServer: how is health computed 43:from .supervisor import Supervisor 69: supervisor: Supervisor, 79: self._supervisor = supervisor 102: pass # the supe |
| 26 | Bash | Count ad-hoc environment-variable configuration outside the kernel config path | == ad-hoc os.environ reads outside kernel (config-by-env-var not via toml) 21 8 SIMORGH_CONFIG 7 SIMORGH_LOADER_NOTES 4 SIMORGH_PATCH_FAILED 4 SIMORGH_GUARDIAN_ |
| 27 | Bash | Spot-check whether the hand-maintained dead-field list is still accurate | == spot-check KNOWN_DEAD_FIELDS still dead? ugrep: warning: simorgh/guardian classifier_timeout_s: No such file or directory guardian classifier_timeout_s. -> 0 |
| 28 | Bash | Read the module-level state in contracts and orchestration, and the thread pool sites | == contracts package mutable state #: A silence longer than this ends a conversation and the next line #: starts a new one. The creator, 2026-09-16: "keep track |
| 29 | Bash | Check whether blocking subprocess calls run on the event loop thread | == blocking subprocess.run on the loop thread? (non-execution/voice packages, with 4 lines of context) --- simorgh/guardian/rules.py 7:131: `command` was `["pyt |
| 30 | Bash | Measure import cost, check loader signal handling and backend defaults | == python Python 3.12.4 == loader KeyboardInterrupt handling == loader status (read-only) [simloader] ── status ──────────────────────────────────────────────── |
| 31 | Bash | Check self-check callers, loader file protection, roll-forward, ledger flush, and env isolation test | == who calls --self-check / run_selfcheck in production simorgh/interface/service.py:156: # every headless boot (tests, `--self-check`, `status`, `trace`) simor |
| 32 | Bash | Check which of my candidate findings prior reviews already cover | == prior reviews: do they cover supervisor/health/local-multi/os._exit/env overrides? poll_once: audit=0 review=0 supervisor: audit=0 review=0 health_every: aud |
| 33 | Bash | Spot-check dead config fields and count the hand-maintained dead list | guardian.classifier_timeout_s -> 0 reads outside config.py guardian.reversible_auto_in_guarded -> 0 reads outside config.py interface.prompt_timeout_s -> 0 read |
| 34 | Bash | Read StatusServer health handling and the blueprint's health-poll promise | == StatusServer health path self._health_sub = None self._status_sub = None async def start(self) -> None: self._metrics_sub = await self._bus.subscribe(topics. |
| 35 | Bash | Read REPL thread details, TUI Ctrl-C handling, executor caps, status route, and prior mention of local-multi | == REPL thread (daemon?) # -- REPL thread (readline blocks; bridged to asyncio via run_coroutine_threadsafe) -- def _wait_for_boot_or_stop(self) -> bool: """Hol |
| 36 | Bash | Experiment: how a plain subprocess.run parent treats its child when both receive Ctrl-C | child: running child: got SIGINT, doing orderly shutdown for 3s parent: KeyboardInterrupt after 1.24 s --- then: does the child survive as an orphan? (child exi |
| 37 | Bash | Gather gate cost numbers and check worktree landing branch logic | == full unit suite cost vs core (from loader notes) 1 5940 passed, 17 warnings in 445.02s (0:07:25)) 1 3347 passed, 16 warnings in 47.58s) 1 2971 passed, 16 war |
| 38 | Bash | Definitive experiment: is the child SIGKILLed by subprocess.run during its orderly shutdown | parent: KeyboardInterrupt after 1.24 s child alive 4s later: False child.log: got SIGINT at 548054.30 |
| 39 | Bash | Read how worktree landing picks the target branch | == worktree landing target """One worktree per task: where Sim's own edits happen, and how they land. Until 2026-09-11 a patch task edited the live checkout --  |
| 40 | Bash | Quote blueprint supervisor promise, check REPL thread flag, and find readers of runtime config fields | == blueprint 5.3 Supervisor ### 5.3 Supervisor Each service runs as an `asyncio.Task` wrapping `start()`. Health is polled every `health_every_s`; three consecu |
| 41 | Bash | Count running/stopping/stopped states in the live ledger system stream | blobs heads idem index.json LOCK snapshots streams == find system stream ./streams/system.jsonl file: ./streams/system.jsonl 746 ./streams/system.jsonl state co |
| 42 | Bash | Check who authored rolled-back commits, Sim's own commit count, and the watchdog aftermath | == authors of the three rolled-back commits dd54876 Saeed Guard test allows the one variable the suite sets on purpose 5cadca0 Saeed cancel_task: "all" is a thi |
| 43 | Bash | Read worktree main resolution and headless HTTP behaviour | == worktree main_head computation status = _git(path, "status", "--porcelain") if status.returncode != 0: return Landed(False, f"git status failed in the worktr |
| 44 | Bash | Check ledger lock type, logging setup, and ledger stream sizes | == ledger LOCK handling 20: <root>/LOCK advisory lock taken around each append 22:Multi-process: an advisory `fcntl` lock is held around each append (not 48:try |
| 45 | Bash | Check worktree fast-forward on detached HEAD and the second config-loading path | == worktree ff mechanism 30: merge = _git(self.repo, "merge", "--ff-only", landed_from) 31: if merge.returncode != 0: 32: return Landed(False, f"refused: main c |
| 46 | Bash | Build a cross-subsystem import matrix and read the boundaries test allowlist | packages: 18 subsystem->subsystem import edges (excluding contracts/bus/ledger targets): 14 kernel -> benchmark, cognition, curiosity, execution, guardian, inte |
| 47 | Bash | Check the test env guard, ledger start scan, metrics history growth, and logging handlers | == conftest env guard == jsonl backend start(): what it does per stream 18: <root>/index.json {stream: {head, bytes, last_ts}}; read at start 103: self.scanned_ |
| 48 | Bash | Measure restart-to-gate latency and gate outcome distribution from loader notes | restarts: 24 next-decision kinds: Counter({'gate_skipped': 8, 'blessed': 5, 'tag_withheld': 5, 'gate_failed': 3, 'gate_reused': 2, 'restart': 1}) restart->next  |
| 49 | Bash | Check whether a cwd-relative config write can shadow the real config file | == repo-root simorgh.toml exists? gitignored? ls: simorgh.toml: No such file or directory == dispatch.py cwd-relative toml write context return Outcome(f"skills |
| 50 | Bash | Measure the ledger's boot scan cost and metrics-history growth rate | == jsonl start(): scan strategy async def start(self) -> None: try: for sub in ("streams", "snapshots", "idem", "blobs", "heads"): (self.root / sub).mkdir(paren |
| 51 | Bash | Check self-check callers, the suite env scrub location, and IO inside the contracts package | == relaunch tool: does it run --self-check before execv? == where is the SIMORGH_* env scrub for the suite? tests/simorgh/interface/conftest.py 2:`conftest.py`' |
| 52 | Bash | Confirm which blocking subprocess calls run on the event-loop thread | == interface/dispatch.py run_shell async def run_shell(command: str, *, timeout: float) -> str: if not command: return "usage: !<shell command>" try: result = s |

## Structured reply

**concern:** Composition root, lifecycle, configuration, and the boot/rollback harness (simorgh/kernel/*, simloader.py, sim.sh, simorgh/__main__.py, ~/.simorgh/simorgh.toml)

**summary of what is actually there:** The composition root is simorgh/kernel/service.py::Kernel.boot (lines 157-327): it opens the Ledger (make_ledger, line 163), builds one bus backend and the Kernel's own BusClient with a ReservedTopologyPolicy (lines 173-186), records the effective config to a `config:effective` stream after configcheck.report (lines 202-214), then walks registry.LAYERS (registry.py:39-46, six layers: bus/ledger -> cognition/memory/worldmodel -> guardian/execution/verification/planning -> learning/reflection/curiosity -> persona/benchmark/voice/interface -> orchestration) through Supervisor.start_layer, which starts each layer concurrently under a hardcoded 30 s boot timeout and waits for every service's health() before the next layer (supervisor.py:51-79). registry.py is the only module that imports other subsystems' Service classes (verified: all 14 cross-subsystem import edges originate in kernel/); every Service is constructed with no arguments except guardian/execution, which receive a Config built by the Kernel (registry.py:145-146, service.py:217-218). ContextFactory.build (context.py:111-143) hands each subsystem its own BusClient bound to its source name, `config=self._config.section(name)`, a deny-by-default ScopedSecretStore (plus `__hmac__` for guardian/execution only), a per-subsystem data dir, and (in multi-process modes) a self-issued identity token. Config is loaded by kernel/config.py::load_config with search order --config > $SIMORGH_CONFIG > ./simorgh.toml > ~/.simorgh/simorgh.toml (lines 38-51), and the live file has [voice], [interface], [execution], [cognition.providers.ollama] sections and no [runtime]/[bus]/[ledger] (so mode=single, bus=memory, ledger=jsonl). Fourteen services adopt their section in start() via `if self._config_from_caller is None and ctx.config: Config.from_mapping(...)`, guardian/execution via the Kernel constructor, and only bus.Service takes none, so the memory note that 12 subsystems ignore their config is stale: 16 of 17 consume it. After the layers, the Kernel starts the Scheduler (durable timers rebuilt from the `schedule` ledger stream, scheduler.py), a ProcessMetricsPublisher and MetricsHistoryWriter on metrics_every_s=10 s, subscribes to system.pause/resume/stop/restart, appends state transitions to the `system` stream before publishing system.state.changed (state.py, service.py:388-447), and restores a persisted autonomous pause (service.py:366-386). Shutdown (service.py:527-556) unsubscribes, stops the periodic tasks, appends `stopped`, then Supervisor.stop_all stops layers in reverse under one shared grace budget (supervisor.py:126-147); kernel/cli.py::_cmd_run wraps this in a Stopper whose first SIGINT/SIGTERM publishes system.stop and arms a grace+10 s watchdog, and every exit path ends in `_exit_now` -> os._exit after pkill -P and stty sane (cli.py:86-200). The concurrency model is one asyncio loop, 138 `asyncio.to_thread` sites for blocking work on the default executor, 46 blocking `subprocess.run` calls (mostly inside those threads), one daemon REPL thread bridged with `run_coroutine_threadsafe(...).result()` (interface/service.py:261, 720), and one ThreadPoolExecutor for dashboard feeds. sim.sh (cd to the repo root, exports SIMORGH_EXECUTION_REPO_ROOT, restores simloader.py from the newest sim-good tag if it will not compile, then execs `python simloader.py run`) launches simloader.py, a stdlib-only bootloader that, unless `.simorgh_loader/last_green.json` matches a clean HEAD, runs the core pytest selection (`-n auto`, ~3348 tests) with a skip key, judges the verdict from pytest's summary line plus a shrink baseline, tags green clean commits `sim-good-NNNN`, rolls back with `git checkout -q <tag>` on failure (refusing if the tree is dirty), relaunches Sim with a plain `subprocess.run`, re-gates on exit code 75 (the REPL `restart`), and treats any non-zero exit within 60 s as a bad image.

### strengths

- Composition-root discipline is real, not aspirational: a scripted import matrix over all 18 packages found exactly 14 subsystem-to-subsystem import edges and every one originates in simorgh/kernel/ (registry.py + configcheck.py + service.py); no subsystem imports another, and tests/simorgh/test_module_boundaries.py enforces it. The 'talks only via the bus' story holds at the import level.
- Layered boot with the safety layer before any proposer: registry.py:39-46 puts guardian/execution in layer 3 and orchestration last; supervisor.py:51-79 starts a layer concurrently and refuses to proceed until every member's health() is ok/degraded, so no Worker exists before Guardian and Execution are up.
- Per-subsystem Context is well shaped: context.py:111-143 gives each subsystem its own BusClient bound to its source name (so trace/metrics/policy see the real publisher), its own [section] dict, a per-subsystem data dir, and a deny-by-default ScopedSecretStore with prefix families (secrets.py:96-132) plus a curated DEFAULT_SECRETS map (registry.py:64-82) so features are not switched off by a forgotten config line.
- Honesty instrumentation around config: configcheck.py probes each section by building the Config from the empty mapping and from the written one and warns when they are identical (lines 1-21, 262-284), corrects the inverted guardian default (EFFECTIVE_DEFAULTS, lines 31-45), and Kernel._record_effective_config writes value+source per field to a `config:effective` stream (service.py:466-525) that the `config` REPL command reads back.
- The loader honours its one principle on the code side: simloader.py never imports simorgh (stdlib only), reads pytest's own summary line rather than trusting the exit byte, refuses 'no tests ran', refuses a run that shrank more than 10% against the last green baseline, and withholds a tag when untracked code would have been imported (unit_verdict lines 660-699; untracked_code 492-503; cmd_run 985-1000). sim.sh:41-55 restores a non-compiling loader from the newest sim-good tag, closing the 'Sim bricks its own bootloader' hole.
- Shutdown is bounded end to end: one shared grace budget across all layers (supervisor.py:126-147), a watchdog that fires even for REPL-initiated stops (cli.py:191-192), the final `stopped` state appended before the ledger layer closes (service.py:538-549). The live `system` stream shows 244 stopping / 244 stopped over 255 boots, i.e. orderly shutdown completes essentially every time.
- State is durable where it matters: transitions are appended to the ledger before system.state.changed is published (state.py docstring, service.py:388-397); a human's `auto off` survives restarts (service.py:366-386, state.py:56-67); schedules are a ledger projection rather than threading.Timer (scheduler.py:14-18, 89-118).
- Boot cost is not the ledger's size: jsonl.py:203-244 trusts index.json entries whose byte size matches, and a measured scandir+stat over the live 118,215 stream files took 0.27 s with index.json parsing in 0.07 s; importing the whole composition root (build_factories, all 17 Service modules) takes 0.29 s. The 45 s boot is the test gate, not the system.

### findings

##### 1. The Supervisor never supervises: no health ticker, restart never restarts, auto-pause on Guardian-down is unreachable

- **kind:** right-design-undermined
- **severity:** high
- **claim:** Supervisor.poll_once (which is the only path to _restart, and therefore to _on_critical_down) has no production caller, health_every_s is parsed and never read, and _restart stops a service without ever calling start() again, so the S3 invariant 'Guardian/Execution down => system pauses' is not enforced at runtime and the status snapshot's per-subsystem health is frozen at boot-time values.
- **evidence:**
  - grep -rn 'poll_once\|_health_task' across simorgh/ and tests/: the only callers are tests/simorgh/kernel/test_supervisor.py:99,106,122 and tests/simorgh/integration/test_guardian_down_autopauses.py:76, whose docstring (lines 8-13) says: 'Phase 0 has no periodic health-poll driver wired into Kernel.boot() yet -- poll_once() is called directly here, standing in for that future ticker.'
  - simorgh/kernel/service.py:157-327 (Kernel.boot) creates the Supervisor at 226-230 and never create_task()s a poll loop; grep 'health_every_s' hits only kernel/config.py:81,115 and kernel/api.py:43.
  - simorgh/kernel/supervisor.py:116-124: after `await supervised.service.stop()` the method ends with the comment 'The concrete restart (re-start()) is driven by the caller (Kernel service loop)' -- no such loop exists; supervisor.py:79 stores `asyncio.current_task()` (the boot coroutine) as the service's task.
  - simorgh/kernel/metrics.py:101-102 `_on_health: pass  # the supervisor's own poll is the source of truth` and 110-119 snapshot() reads s.status/s.last_health, which only _boot_one and poll_once write.
  - docs/blueprint/subsystems/03-kernel.md:281-290 promises 'Health is polled every health_every_s; three consecutive non-ok polls -> degraded ... Guardian and Execution are special: if either is down, the Kernel transitions to paused automatically'.
- **why it matters:** This is the project's own dominant bug shape (designed slot, one side built, nobody drives it) sitting in the kernel that is supposed to catch it elsewhere. The safety story leans on 'nothing may execute without the safety path' being enforced by wiring; today it is hoped for. The dashboard's subsystem health column is a boot-time screenshot, and three [runtime] knobs (health_every_s, supervisor_backoff_s, supervisor_max_restarts_per_10m) are inert while being exempt from the dead-config probe (configcheck.KERNEL_SECTIONS).
- **recommendation:** Pick one of two small changes. (a) Wire the ticker: in Kernel.boot after the layer loop, `self._health_task = asyncio.create_task(self._health_loop())` that sleeps health_every_s, awaits supervisor.poll_once(), and publishes system.health for each changed service; cancel it in shutdown. (b) For one laptop, simpler and probably better: delete the in-process restart/backoff machinery and keep only 'down => pause + publish', because a subsystem that crashed mid-state is safer taken down with the process and relaunched by the loader, which is already the process-level restart mechanism. Either way, delete the dead runtime fields or make configcheck cover [runtime].
- **confidence:** 0.95

##### 2. A cwd-relative `simorgh.toml` write can silently shadow the real config on the next boot

- **kind:** bug
- **severity:** high
- **claim:** interface/dispatch.py appends MCP approvals to `Path("simorgh.toml")` relative to the process cwd, which under sim.sh/simloader is the repo root where no simorgh.toml exists; the Kernel's search order prefers ./simorgh.toml over ~/.simorgh/simorgh.toml, so after one `mcp approve` and the advertised restart the entire live configuration ([voice], [interface], [execution] secrets, [cognition]) is replaced by a file containing one MCP block, with no warning.
- **evidence:**
  - simorgh/interface/dispatch.py:79 `_SIMORGH_TOML_PATH = Path("simorgh.toml")`; :2167-2173 `with _SIMORGH_TOML_PATH.open("a", ...)` then `return Outcome(f"approved: wrote ... to {_SIMORGH_TOML_PATH} -- restart Sim to load it")`.
  - simorgh/kernel/config.py:44-50: `cwd_candidate = Path("simorgh.toml"); if cwd_candidate.is_file(): return cwd_candidate` before the data_dir candidate.
  - sim.sh:13 `cd "$REPO_ROOT"`; simloader.py:1057 `subprocess.run([..."-m", "simorgh", "run"...], cwd=repo, ...)`; `ls /Users/saeed/ws/Simorgh/simorgh.toml` -> 'No such file or directory'; the live config is ~/.simorgh/simorgh.toml.
  - A second, independent config path exists: simorgh/contracts/settings.py:162-170 re-implements the search order 'without importing' the kernel (ignores --config and SIMORGH_RUNTIME_DATA_DIR) and :185 is a TOML writer; contracts/places.py:57-62 reads the TOML directly with a module-level `_cache`.
- **why it matters:** Configuration has one reader in the kernel but at least three independent locators/writers outside it. The failure is silent and total: configcheck cannot warn because the shadow file parses fine, and `config` will happily report the new path. It also means a `--config other.toml` run has tools persisting settings into a different file from the one being read.
- **recommendation:** Make the path a single fact: add `config_path` to Context (ContextFactory already holds LoadedConfig.path) and have every writer (settings.py, places.py, dispatch.py) use it; delete the cwd candidate from find_config_path (a daemon launched from a repo root should not read a repo-relative config); have contracts/settings.py call kernel.config.find_config_path instead of copying it.
- **confidence:** 0.85

##### 3. The loader boots and rolls back the development checkout, so rollback is refused when it is needed, detaches HEAD, and diverts Sim's own landings

- **kind:** wrong-design
- **severity:** high
- **claim:** Running the A/B-image pattern against the same git checkout the creator edits means rollback is disabled whenever the tree is dirty (most of the time during development), a successful rollback leaves HEAD detached with no roll-forward, worktree landing then fast-forwards that detached HEAD instead of main, and sim.sh's loader self-repair itself dirties the tree and thereby disables rollback.
- **evidence:**
  - simloader.py:877-897 cmd_rollback: `if is_dirty(repo): say("refusing: the working tree has uncommitted changes..."); return 2` (no write_note on this path), then `git checkout -q target` (line 888) -- detached HEAD; grep for 'checkout' in simloader.py finds no return-to-branch logic.
  - .simorgh_loader/decisions.jsonl lines 59-60: `{"kind": "watchdog", "commit": "a68ed8e", "why": "Sim exited 2 after 7s, inside the 60s watchdog"}` followed 23 s later by `{"kind": "gate_skipped", ...}` with no rollback/rollback_failed note between -- the watchdog rollback was silently refused.
  - simorgh/execution/worktree.py:192 `main_head = _git(self.repo, "rev-parse", "HEAD")` and the landing `merge --ff-only` (worktree.py, ~line 229) run in the live repo, i.e. 'main' means whatever HEAD is; the module docstring (lines 22-25) says 'fast-forward main'.
  - sim.sh:45 `git checkout "$LAST_GOOD" -- simloader.py` modifies a tracked file, which is_dirty (simloader.py:444-450, `--untracked-files=no`) then reports as dirty.
  - git log: all three real rollbacks (dd54876, 5cadca0, 424c478) were on commits authored 'Saeed'; `git log --author=Simorgh --oneline | wc -l` = 94 of 856 commits -- Sim's own commits land pre-gated via worktree.land and have never been the thing rolled back.
  - Memory note feedback_live_checkout_uncommitted: 'sim.sh boots from the repo I edit; half-done edits get gated and block rollback'.
- **why it matters:** The bootloader analogy works in embedded systems because the image slot is not the engineer's workbench. Here the same directory is the workbench, the deploy target, and Sim's landing target, so the three interfere: the human's uncommitted edit blocks the rollback, the rollback strands the human on a detached HEAD, and Sim's next patch lands on that detached HEAD where a later `git checkout main` orphans it.
- **recommendation:** Separate deploy from dev with one git worktree: the loader owns `~/.simorgh/live` (git worktree add on a `live` branch), boots Sim from it, and rollback/roll-forward are `git -C live reset --hard sim-good-NNNN` / `... main` there -- the dev tree's state never matters, HEAD is never detached in the creator's checkout, and landing targets the `main` branch by name (`rev-parse main`, `update-ref`), not HEAD. Roughly 50 lines in simloader.py and sim.sh. Also write a note on the dirty-refusal path so Sim can see that a rollback did not happen.
- **confidence:** 0.9

##### 4. The boot gate is skipped by hand about half the time, gates the wrong moment, and runs the judged code with the live environment

- **kind:** right-design-undermined
- **severity:** medium
- **claim:** The 45-48 s core gate is bypassed with the skip key on 34 of 70 gate opportunities in the last five days, cannot be reused while any untracked .py exists (as now), duplicates the landing-time gate that already protects Sim's own commits, treats a config/boot error as a bad image, and inherits the operator's environment and $HOME so the loader's 'never runs the code it is judging' principle is violated on the environment side.
- **evidence:**
  - .simorgh_loader/decisions.jsonl (99 decisions, 2026-09-14..18): gate_skipped 34, blessed 20, gate_reused 7, tag_withheld 5, gate_failed 4, restart 24, rollback 3, watchdog 1; restart -> next gate decision median 45 s, p90 58 s.
  - .simorgh_loader/unit_baseline-core.json: {"tests": 3348, "seconds": 45.67}; a whole-suite gate in the notes: '5940 passed ... in 445.02s (0:07:25)'.
  - `python3 simloader.py status`: 'untracked CODE -- the gate would run it, no tag can be earned while it is here: simorgh/big.py' (a 2-line scratch file) -- source_fingerprint returns '' so already_verified never matches (simloader.py:916-954).
  - simloader.py:383-386 `subprocess.Popen(argv, cwd=cwd, ...)` with no env=; sim.sh:22 exports SIMORGH_EXECUTION_REPO_ROOT into that environment; tests/simorgh/kernel/test_the_suite_cannot_see_the_operators_env.py documents the consequence ('5,007 files written into the live data_dir') and the fix lives in the suite's own conftest, i.e. in the judged code.
  - simloader.py:1042-1048 treats any non-zero exit inside 60 s as a bad image; kernel/cli.py:392-397 returns 2 for both ConfigError and KernelBootError; the one real watchdog event was 'Sim exited 2 after 7s'.
  - simorgh/execution/worktree.py:22-25: landing already runs 'the gate -- the whole suite -- in a copy of the rebased tree; fast-forward main'.
- **why it matters:** A gate that the operator routinely skips protects the tag ledger, not the boot. Its real catches (4 gate_failed) were all the creator's own un-tested commits; Sim's commits are gated at landing. Meanwhile every restart pays 45 s or a keypress, and the gate cannot tell 'the code regressed' from 'the house is offline'.
- **recommendation:** Move the default to gate-at-change, not gate-at-boot: `run` reuses the last green verdict for the current commit regardless of untracked non-test scratch (or ignore untracked files outside tests/ and simorgh/ that the suite does not import), gates only when HEAD moved past the newest tag, and offers `--force-gate` for the rest. Give the pytest child a loader-side env allowlist (PATH, HOME=<tmp>, PYTHON*) so the judged code cannot inherit the live data dir. Split exit codes so a ConfigError (2) never triggers the watchdog rollback while a KernelBootError (3) does.
- **confidence:** 0.85

##### 5. Three deployment modes and a multi-process trust model carried by a single-process system, plus a self-check that proves stubs and is never called

- **kind:** over-engineering
- **severity:** medium
- **claim:** WorkerKernel, IdentityRegistry, per-process identity tokens, `aws` mode and the `--self-check` proof exist for a topology that has never run here; in the only mode in use (`single`, one Python process) the HMAC approval token and reserved-topic policy are discipline rather than a boundary, and selfcheck.py exercises stub Guardian/Execution rather than the registry the blueprint says it boots.
- **evidence:**
  - ~/.simorgh/simorgh.toml has no [runtime] section (mode defaults to 'single', api.py:34); bus/config.py:30 backend default 'memory'.
  - simorgh/kernel/service.py:353-354 '`aws` mode is untouched here -- its process topology is a different track's concern'; :588-597 WorkerKernel docstring: the worker's identity secret 'is *not*, and today cannot be, the same secret the main process's own IdentityRegistry holds: policy is enforced client-side, per process ... unfinished hardening'.
  - simorgh/kernel/selfcheck.py:10-14 'The Guardian/Execution used here are minimal stubs, not the real subsystems'; :7-8 claims `learning`'s relaunch tool calls this before execv -- grep for 'self-check|run_selfcheck|selfcheck' outside kernel/ finds no caller; docs/blueprint/subsystems/03-kernel.md:292-294 promises the self-check 'Boots the full registry on the memory bus and memory ledger'.
  - service.py:167-172 acknowledges the token secret doubles as the identity secret; in single mode `identities` is None (line 173) and the Kernel object holding `_hmac_secret` is reachable from any code in the process.
- **why it matters:** For one laptop and one family the safety property that matters is 'Execution runs only what Guardian approved', which in-process is a code-review property; the token machinery documents it nicely but the extra modes double the surface (two kernels, two boot paths, a policy with two enforcement regimes) and produce docstrings that explain why they do not quite work. The self-check is 256 lines that assert something no boot depends on.
- **recommendation:** Keep the approval token (cheap, self-documenting) and the ReservedTopologyPolicy; delete WorkerKernel, `simorgh worker`, `aws`/`local-multi` and IdentityRegistry until a second process actually exists (git keeps them). Either make `--self-check` the real thing (boot the actual registry on memory backends in a temp data dir and run one guarded no-op) and call it from the loader watchdog path, or delete it.
- **confidence:** 0.8

##### 6. Configuration is four mechanisms: section dicts, a documented env override that covers 2 of 17 sections, ~25 bespoke SIMORGH_* variables, and direct TOML access; 26 config fields ship with no reader

- **kind:** missing
- **severity:** medium
- **claim:** The kernel's promise 'every [section] key is overridable by SIMORGH_<SECTION>_<KEY>' is implemented for [runtime] and [execution] only; subsystems compensate with 21 ad-hoc os.environ reads of their own variable names; configcheck maintains a hand-written list of 19 config fields that parse but are never read (verified still dead), and 7 of RuntimeConfig's 18 fields have no reader while [runtime] is exempt from the probe; the `config:effective` record covers 3 of 17 sections.
- **evidence:**
  - simorgh/kernel/config.py:5-9 promises the override for every section; `_apply_env_overrides` callers: config.py:93 ([runtime]) and service.py:217 via `_with_env_overrides`, whose docstring (service.py:33-36) says 'kernel/config.py promised this for every section and delivered it for [runtime] alone'.
  - grep of SIMORGH_* names outside simorgh/kernel/: 21 read sites, including SIMORGH_GUARDIAN_AUTO_APPROVE (guardian/config.py:155, execution/security/tools.py:192), SIMORGH_COGNITION_PROVIDER_ORDER, SIMORGH_LLM_DAILY_MAX_CALLS, SIMORGH_LLM_DAILY_BUDGET_USD, SIMORGH_PLANNING_LEASE_SECONDS, SIMORGH_VERIFICATION_RIGOR, SIMORGH_TTS_THREADS, SIMORGH_CARTOON_SPLASH, SIMORGH_LEDGER_BACKEND, SIMORGH_BUS_BACKEND.
  - simorgh/kernel/configcheck.py:66-207: KNOWN_DEAD_FIELDS + KNOWN_DEAD_NESTED_FIELDS = 15 + 4 = 19 fields across 11 sections (python -c import count); spot-check grep outside each package's config.py: guardian.classifier_timeout_s 0 reads, guardian.reversible_auto_in_guarded 0, interface.prompt_timeout_s 0, interface.notice_queue_max 0, interface.vitals_interval_s 0, planning.max_task_attempts 0, execution.approval_max_age_s 0, execution.readable_root_files 0, cognition.availability_poll_seconds 0, bus.metrics_interval_seconds 0.
  - simorgh/kernel/api.py:31-51 RuntimeConfig; grep outside kernel/config.py and kernel/api.py: 0 readers for `.disabled`, `.subsystems`, `health_every_s`, `log_level`, `log_to_ledger`, `.deployment`, `schedule_persist`; configcheck.py:29 KERNEL_SECTIONS exempts 'runtime'.
  - simorgh/kernel/service.py:485-486 `models = {"execution": ..., "guardian": ..., "interface": ...}` -- three of seventeen sections in `config:effective`, while interface/dispatch.py:1545 presents it as what is in force.
  - Verified today: 14 services adopt ctx.config in start() (`if self._config_from_caller is None and ctx.config:` in ledger, cognition, memory, worldmodel, verification, planning, learning, reflection, curiosity, persona, benchmark, voice, interface, orchestration), guardian/execution via registry.py:145-146 -- the '12 subsystems ignore their config' note is resolved.
- **why it matters:** `[runtime] disabled = ["voice"]` does nothing and nothing says so; SIMORGH_VOICE_TTS=... does nothing; 19 documented keys are decoys with a comment explaining why; and the operator cannot tell from one place what is in force. The dead-field list is a TODO list that ships in the product.
- **recommendation:** Delete the 19 dead fields and the 7 dead runtime fields rather than listing them (or wire the two that matter: `disabled`, `health_every_s`). Apply `_with_env_overrides(name, section, ConfigClass)` once in ContextFactory.build so the promise holds for every section, then retire the bespoke variables into their sections. Record all 17 sections in `config:effective` by iterating configcheck._config_classes().
- **confidence:** 0.9

##### 7. Under the loader, a terminal SIGINT SIGKILLs Sim 250 ms into its orderly shutdown

- **kind:** bug
- **severity:** medium
- **claim:** simloader.launch_sim uses a plain subprocess.run with no signal handling; a Ctrl-C reaches both processes, CPython's subprocess.run waits 0.25 s for the child and then kill()s it, so stop_grace_s, the Stopper watchdog, the final `stopped` ledger event and the loader's own bookkeeping are all skipped whenever the signal is delivered to the group.
- **evidence:**
  - simloader.py:1053-1057 `subprocess.run([sys.executable, "-m", "simorgh", "run", *sim_args], cwd=repo, env=env)`; grep 'KeyboardInterrupt|signal.' in simloader.py: no matches.
  - Standalone reproduction in the scratchpad (parent = plain subprocess.run, child = SIGINT handler doing a 3 s orderly shutdown, SIGINT sent to the process group): output 'parent: KeyboardInterrupt after 1.24 s' (1.0 s delay + 0.25 s _sigint_wait_secs), 'child alive 4s later: False', child.log 'got SIGINT' with no 'orderly shutdown DONE' line.
  - simorgh/kernel/cli.py:132-156 Stopper expects grace+10 s (stop_grace_s default 15, api.py:46).
  - Frequency is low in practice: ~/.simorgh/ledger/streams/system.jsonl stop reasons are repl_exit 158, user exit 52, repl_restart 31, signal 1; interface/tui.py:493 keeps ISIG off so Ctrl-C at the prompt is a keypress, not a signal. The path is live during boot, the gate, the readline fallback, headless runs, and `kill -INT -<pgid>`.
- **why it matters:** Two process supervisors (loader and Kernel Stopper) that do not know about each other: the Kernel's carefully bounded shutdown is unreachable in the standard launch path for the one signal a terminal sends. A SIGKILL mid-append is exactly what the ledger's fsync discipline exists to survive, but the `stopped` state, notes and tags are lost.
- **recommendation:** In launch_sim, ignore SIGINT in the loader for the child's lifetime (`signal.signal(SIGINT, SIG_IGN)` before Popen, restore after), or use Popen + wait() and on KeyboardInterrupt wait(timeout=stop_grace+15) before killing. Five lines.
- **confidence:** 0.9

##### 8. `simorgh status` boots a second full Kernel and reports on itself; `trace`/`migrate-v1` ignore the configured ledger backend

- **kind:** over-engineering
- **severity:** low
- **claim:** The status subcommand constructs and boots all 17 subsystems in a throwaway process against the live data dir and, with the default in-memory bus, can never observe the running instance; the trace and migrate subcommands hardcode a jsonl ledger regardless of [ledger].
- **evidence:**
  - simorgh/kernel/cli.py:229-239 `_cmd_status`: `kernel = Kernel(config); await kernel.boot(); print(json.dumps(kernel.status_snapshot()...)); finally: await kernel.shutdown()`.
  - simorgh/bus/config.py:30 `backend: str = "memory"` and no [bus] section in ~/.simorgh/simorgh.toml; the real liveness path is interface/httpapi.py:290 `/api/status`.
  - cli.py:246 and :264 `make_ledger({"backend": "jsonl", ...})` while ledger/config.py:18,46 allows sqlite via [ledger] or SIMORGH_LEDGER_BACKEND.
- **why it matters:** A diagnostic that starts voice, execution (skill scan, MCP), curiosity and the rest for one second to print its own boot state is expensive and misleading, and it is the kind of tool the creator reaches for when something is wrong.
- **recommendation:** Make `status` an HTTP client of /api/status (fallback: read the last `system` and `metrics:history` events from the ledger without booting anything). Build the ledger mapping for trace/migrate from `_ledger_mapping_for(config, runtime)`.
- **confidence:** 0.9

##### 9. os._exit is a symptom, not the disease: blocking work has no registry or cancellation, one REPL command blocks the event loop, and the boot timeout is a hardcoded constant

- **kind:** right-design-undermined
- **severity:** low
- **claim:** The concurrency model (one asyncio loop, default-executor threads for blocking calls, one daemon REPL thread bridged by run_coroutine_threadsafe) is coherent, but 138 to_thread sites and 46 blocking subprocess.run calls are untracked and uncancellable, so shutdown can only race a watchdog and hard-exit; `!<cmd>` runs subprocess.run on the loop thread; and Supervisor's 30 s per-service boot timeout is not configurable.
- **evidence:**
  - Counts (grep -rn --include='*.py' over simorgh/): asyncio.to_thread 138 (execution 19 files, voice 10, cognition 4, interface 3), threading.Thread( 1 (interface/service.py:261, daemon=True), run_coroutine_threadsafe 1 real site (interface/service.py:720), subprocess.run( 46, ThreadPoolExecutor 1 (interface/dashfeeds.py:925), asyncio.run( inside the package 1 (a generated skill-driver string, execution/tools.py:2721).
  - simorgh/kernel/cli.py:86-129 `_HARD_EXIT = os._exit` ... `_exit_now` (pkill -P, stty sane, os._exit) and :194-200 -- every exit path, including a clean one, ends in os._exit.
  - simorgh/interface/dispatch.py:166-172 `async def run_shell(...)`: `result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)` with no to_thread -- the bus (voice, HTTP, Telegram) stalls for the command's duration. By contrast guardian/rules.py:507 correctly wraps run_bandit in asyncio.to_thread.
  - simorgh/kernel/supervisor.py:40 `boot_timeout_s: float = 30.0`; service.py:226-230 constructs Supervisor without passing it.
- **why it matters:** For one laptop the hard exit is an acceptable trade, but the Kernel cannot make any promise about in-flight tool work at shutdown, and the one loop-blocking call is on the path a human uses when things are already slow.
- **recommendation:** Wrap run_shell in asyncio.to_thread; expose boot_timeout_s in [runtime]; longer term, route long blocking tool work through subprocesses the Execution service tracks (pid list) so shutdown can terminate them deterministically instead of pkill -P at exit.
- **confidence:** 0.85

##### 10. The Kernel's own metrics history is the largest ledger stream and grows ~19 MB per day of uptime with no retention

- **kind:** bug
- **severity:** low
- **claim:** MetricsHistoryWriter appends a full MetricsTable snapshot every metrics_every_s=10 s to the append-only `metrics:history` stream, which is now 114 MB / 50,677 events, larger than any other stream, with no compaction or age cap anywhere in kernel/metrics.py.
- **evidence:**
  - `ls -S ~/.simorgh/ledger/streams | head`: metrics%3Ahistory.jsonl 114M, curiosity%3Aticks.jsonl 43M, persona%3Astate.jsonl 17M; `wc -l` metrics history = 50677 lines; 50677 x 10 s = 140.8 h of uptime => 19.4 MB per day.
  - simorgh/kernel/service.py:289-293 MetricsHistoryWriter(interval_s=self.runtime.metrics_every_s); api.py:42 metrics_every_s = 10.0; grep 'retention|compact|truncat|keep' in kernel/metrics.py: no hits.
  - Ledger totals: 118,215 stream files, streams/ 696M, blobs/ 325M, index.json 12.8 MB.
- **why it matters:** The ledger is meant to be the durable record; the kernel is filling it with derivable telemetry (metrics.py's own docstring calls the table a 'justified cache'). Boot cost is fine (0.27 s scan measured), so this is disk and backup weight, but it is the kernel doing it to its own store.
- **recommendation:** Snapshot every 60 s and write to a rolling file outside the ledger (or a single `metrics:history` stream truncated by age at boot); the dashboard's /api/history needs the last hours, not five days at 10 s resolution.
- **confidence:** 0.9

##### 11. `contracts` has become a utility package with IO and process-global state; the tool registry is module-level

- **kind:** right-design-undermined
- **severity:** low
- **claim:** The package described as the frozen Phase 0 contracts now contains five modules that run git, write log files under a threading.Lock, and read/write simorgh.toml, plus four of the codebase's nine module-level mutable singletons; and orchestration keeps its tool registry in module globals that already caused cross-kernel leakage.
- **evidence:**
  - grep -l 'subprocess|threading|open(' simorgh/contracts/*.py: checkout.py console.py overheard.py places.py settings.py (5 of 26 modules, 4,588 lines total); overheard.py:68 `_lock = threading.Lock()`; console.py:76 `global _since_check`; places.py:40,51,115 `_cache`.
  - Module-level mutable state scan (9 hits): contracts/compat.py:25 _TRANSLATORS, contracts/places.py:40 _cache, contracts/registry.py:66 _REGISTRY, contracts/overheard.py:68 _lock, execution/media/androidtv.py:54 _PENDING, orchestration/tools.py:559 _DYNAMIC_TOOLS, :569 _REGISTERED, orchestration/scaffolds.py:35 _UNAVAILABLE, guardian/rules.py:408 _bandit_cache.
  - orchestration/tools.py:562-569 comment: 'using it as "what exists" made every later harness test offer the model nothing ... so one kernel's tools never leak into the next'.
  - registry.py:7-10: subsystems were 'built concurrently by separate tracks against the frozen Phase 0 contracts'.
- **why it matters:** None of this breaks the bus-only import rule (the matrix shows no subsystem imports another), but it is state and side effects that live outside any Context: invisible to config, to the supervisor, and to the per-subsystem data-dir discipline, and `contracts` is imported by everyone so its IO runs in everyone.
- **recommendation:** Move checkout/console/overheard/places/settings into a `simorgh/support` (or `platform`) package that the boundaries test treats like contracts; make the Orchestration tool registry an attribute of its Service (or a small object passed via ctx) instead of module globals.
- **confidence:** 0.85

##### 12. Logging is never configured: structured INFO logs are dropped and [runtime] log_level / log_to_ledger are inert

- **kind:** missing
- **severity:** low
- **claim:** No code calls logging.basicConfig/dictConfig or attaches a handler, so `_StdlibLogger.info/debug` from every subsystem is discarded by Python's default root logger and only WARNING+ reach stderr via the last-resort handler; the documented `log_to_ledger` path is not wired.
- **evidence:**
  - grep -rn --include='*.py' 'basicConfig|dictConfig|addHandler|StreamHandler|FileHandler' simorgh/: only two third-party setLevel calls (cognition/providers/gemini.py:91, execution/media/cast.py:109).
  - simorgh/kernel/context.py:26-31 `_StdlibLogger` docstring: 'section 4's log_to_ledger is a *separate*, additive path the Kernel service wires on top' -- grep 'log_to_ledger' outside kernel/config.py and kernel/api.py: only that docstring; api.py:48-49 defaults log_level='info', log_to_ledger=True.
- **why it matters:** When something goes wrong the creator has the ledger and the TUI but no log; and two runtime settings that look like the knob for it do nothing.
- **recommendation:** One `logging.basicConfig(level=runtime.log_level.upper(), handlers=[RotatingFileHandler(data_dir/'simorgh.log')])` in `_cmd_run`, and either implement log_to_ledger as a WARNING+ handler that appends to a `log` stream or delete the field.
- **confidence:** 0.9


### measurements

- Cross-subsystem import matrix (scripted over simorgh/, 18 packages): 'subsystem->subsystem import edges (excluding contracts/bus/ledger targets): 14' -- all 14 originate in kernel/ (kernel -> benchmark, cognition, curiosity, execution, guardian, interface, learning, memory, orchestration, persona, planning, reflection, voice, worldmodel).
- grep -rn 'poll_once|_health_task' simorgh/ tests/: production callers 0; test callers tests/simorgh/kernel/test_supervisor.py:99,106,122 and tests/simorgh/integration/test_guardian_down_autopauses.py:76.
- grep 'health_every_s' simorgh/: kernel/config.py:81, kernel/config.py:115, kernel/api.py:43 only.
- Services adopting ctx.config in start(): 14 with the `_config_from_caller is None and ctx.config` pattern + guardian/execution via Kernel constructor = 16 of 17; bus.Service: 0 hits.
- KNOWN_DEAD_FIELDS + KNOWN_DEAD_NESTED_FIELDS: 'flat 15 nested 4 total 19 sections 11'; RuntimeConfig fields with 0 readers outside kernel/config.py+api.py: deployment, subsystems, disabled, health_every_s, log_level, log_to_ledger, schedule_persist (7 of 18).
- SIMORGH_* environment names read outside simorgh/kernel/: 21 read sites, 25 distinct names; _apply_env_overrides callers: config.py:93 ([runtime]) and service.py:217 ([execution]) only.
- Concurrency primitive counts (grep -rn --include='*.py' simorgh/): asyncio.to_thread 138; threading.Thread( 1; run_in_executor 1; ThreadPoolExecutor 3 (1 real); run_coroutine_threadsafe 5 (1 real call site); call_soon_threadsafe 4; subprocess.run( 46; subprocess.Popen( 2; create_subprocess_exec 6; asyncio.run( inside package (non-cli) 1.
- Module-level mutable singletons: 9 (4 in contracts/, 2 in orchestration/tools.py); `global` statements: 4. contracts modules doing subprocess/threading/file IO: 5 of 26 (4,588 lines total).
- Loader notes .simorgh_loader/decisions.jsonl: 99 decisions 2026-09-14..18: gate_skipped 34, restart 24, blessed 20, gate_reused 7, tag_withheld 5, gate_failed 4, rollback 3, watchdog 1, bless_refused 1; restart -> next decision median 45 s, p90 58 s, max 866 s.
- .simorgh_loader/unit_baseline-core.json: {"tests": 3348, "seconds": 45.67}; a whole-suite gate: '5940 passed, 17 warnings in 445.02s (0:07:25)'; `python3 simloader.py status`: 'untracked CODE ... simorgh/big.py', 'last green gate ran 3348 tests; a run below 3013 is refused', 'latest known-good: sim-good-0023', HEAD 38a9049 = sim-good-0023-1-g38a9049.
- Rolled-back commits dd54876, 5cadca0, 424c478: all authored 'Saeed'; `git log --author=Simorgh --oneline | wc -l` = 94; `git rev-list --count HEAD` = 856.
- SIGINT experiment (scratchpad, plain subprocess.run parent, child with 3 s orderly shutdown, SIGINT to process group): 'parent: KeyboardInterrupt after 1.24 s' / 'child alive 4s later: False' / child.log 'got SIGINT' only.
- Live ledger ~/.simorgh/ledger: 1.4G total; streams/ 696M in 118,215 files; blobs/ 325M; index.json 12,784,528 bytes; system.jsonl 746 lines with states running 255 / stopping 244 / stopped 244 / paused 2 / failed 1; stop reasons repl_exit 158, user exit 52, repl_restart 31, user requested restart 2, signal 1.
- metrics%3Ahistory.jsonl: 114M, 50,677 lines -> 140.8 h of uptime at 10 s, 19.4 MB per day of uptime.
- Boot-cost floors measured: scandir+stat over 118,215 stream entries 0.27 s; index.json parse 0.07 s (118,215 keys); `python3 -c 'from simorgh.kernel.registry import build_factories; build_factories(...)'` real 0.29 s.
- ~/.simorgh/simorgh.toml sections present: [voice], [interface], [execution], [cognition], [cognition.providers.ollama]; no [runtime], [bus], [ledger], [guardian]. `ls /Users/saeed/ws/Simorgh/simorgh.toml`: No such file or directory.

