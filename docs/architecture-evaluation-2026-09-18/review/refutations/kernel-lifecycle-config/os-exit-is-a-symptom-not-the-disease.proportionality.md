# refute:proportionality:os._exit is a symptom, not the disease:

*Workflow: review · Phase: Refute · Agent id: `aea75f8d14231c3b9` · Tool calls: 4*

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
    "title": "os._exit is a symptom, not the disease: blocking work has no registry or cancellation, one REPL command blocks the event loop, and the boot timeout is a hardcoded constant",
    "kind": "right-design-undermined",
    "severity": "low",
    "claim": "The concurrency model (one asyncio loop, default-executor threads for blocking calls, one daemon REPL thread bridged by run_coroutine_threadsafe) is coherent, but 138 to_thread sites and 46 blocking subprocess.run calls are untracked and uncancellable, so shutdown can only race a watchdog and hard-exit; `!<cmd>` runs subprocess.run on the loop thread; and Supervisor's 30 s per-service boot timeout is not configurable.",
    "evidence": [
      "Counts (grep -rn --include='*.py' over simorgh/): asyncio.to_thread 138 (execution 19 files, voice 10, cognition 4, interface 3), threading.Thread( 1 (interface/service.py:261, daemon=True), run_coroutine_threadsafe 1 real site (interface/service.py:720), subprocess.run( 46, ThreadPoolExecutor 1 (interface/dashfeeds.py:925), asyncio.run( inside the package 1 (a generated skill-driver string, execution/tools.py:2721).",
      "simorgh/kernel/cli.py:86-129 `_HARD_EXIT = os._exit` ... `_exit_now` (pkill -P, stty sane, os._exit) and :194-200 -- every exit path, including a clean one, ends in os._exit.",
      "simorgh/interface/dispatch.py:166-172 `async def run_shell(...)`: `result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)` with no to_thread -- the bus (voice, HTTP, Telegram) stalls for the command's duration. By contrast guardian/rules.py:507 correctly wraps run_bandit in asyncio.to_thread.",
      "simorgh/kernel/supervisor.py:40 `boot_timeout_s: float = 30.0`; service.py:226-230 constructs Supervisor without passing it."
    ],
    "why_it_matters": "For one laptop the hard exit is an acceptable trade, but the Kernel cannot make any promise about in-flight tool work at shutdown, and the one loop-blocking call is on the path a human uses when things are already slow.",
    "recommendation": "Wrap run_shell in asyncio.to_thread; expose boot_timeout_s in [runtime]; longer term, route long blocking tool work through subprocesses the Execution service tracks (pid list) so shutdown can terminate them deterministically instead of pkill -P at exit.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Verify counts and cited lines in dispatch, cli, supervisor | to_thread: 138 subprocess.run(: 46 threading.Thread(: 1 run_coroutine_threadsafe: 5 simorgh/interface/service.py:465: `run_coroutine_threadsafe(...).result()`,  |
| 2 | Bash | Check run_shell callers, Execution subprocess tracking, boot timeout handling, prior reviews | simorgh/benchmark/swebench.py:557: step 12 run_shell: [main e2aef5e39] Fix NDDataRef mask propagation simorgh/interface/service.py:775: `!` (the shell escape) i |
| 3 | Bash | Check the REPL shell path, clone path, execution shell tool threading, supervisor construction, shutdown handling | async def dispatch(command: Command, *, bus: BusClient, clock, session_id: str, vitals: VitalsCache, ledger: LedgerClient) -> Outcome: name, args = command.name |
| 4 | Bash | Check real boot-timeout occurrences, clone callers, in-flight replay, shutdown grace | did not start within 12 s; Backyard Door Left: the stream did not start within 12 s; Backyard Left: the stream did not start within 12 s; Office: the stream did |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Every file:line citation checks out (counts reproduced exactly: to_thread 138, subprocess.run( 46, threading.Thread( 1, one real run_coroutine_threadsafe site at interface/service.py:720; dispatch.py:166-172 runs subprocess.run on the loop thread; supervisor.py:40 hardcodes boot_timeout_s=30.0 and service.py:226-230 does not pass it). But three of the four claims are either a documented deliberate trade-off, overstated, or disproportionate at this scale, and one is a genuine small bug.

(1) os._exit: this is not an undiagnosed symptom. kernel/cli.py:80-86 records the reproduced failure that motivated it (a busy thread held the process 90 s after two signals, 2026-09-11) and _exit_now's docstring explains why it runs even after a clean Kernel.shutdown(). Python cannot cancel a thread running a blocking call, so the only alternatives are (a) what the finding proposes -- moving long blocking work into tracked subprocesses -- or (b) what exists: a grace window ([runtime] stop_grace_s, kernel/config.py:82,119), a watchdog, pkill -P of children, then os._exit. For one laptop, (b) is the proportionate answer. Rewriting 138 to_thread sites across execution/voice/cognition/interface into a pid-tracked subprocess model is far more work than it saves.

(2) "untracked" / "the Kernel cannot make any promise about in-flight tool work": overstated. Execution keeps an in-flight ledger stream and on the next boot _replay_inflight (execution/service.py:702-713) emits ACTION_RESULT with error="interrupted by restart" for every started-but-unfinished action and closes the stream entry. So tool work IS tracked at the action level and IS reconciled after a hard exit; what is missing is only cooperative cancellation of the OS thread, which CPython does not offer anyway. The one long-lived child process class that matters (MCP servers) is already terminated/killed explicitly (execution/mcp.py:151,190).

(3) boot_timeout_s not configurable: true, but there is no evidence it has ever fired. The only "did not start within" strings in ~/.simorgh/ledger are camera-stream messages at 12 s, not Supervisor BootTimeout. Voice, the heaviest subsystem, loads models lazily on first use (voice/service.py:4, :235 via to_thread), so start() is cheap. Adding a config key for a limit nobody has hit is churn, not architecture.

(4) run_shell blocking the event loop: genuine bug, correctly identified, and cheap to fix. dispatch.py:187 runs the REPL's `!` command with timeout=120.0 synchronously on the loop, and -- not in the original finding -- _clone_at (dispatch.py:1837-1849, the `skill` install path at :274) does the same with 180 s git clone/fetch timeouts. Meanwhile the tool-side run_shell in execution/shell.py:222 correctly uses asyncio.to_thread(subprocess.run, ...). This is inconsistency between two implementations of the same idea, not an architectural gap; the fix is one to_thread wrap in interface/dispatch.py::run_shell.

Net: the claim is partly true. The kernel/lifecycle design is coherent and its hard-exit trade-off is deliberate and documented; the genuine item is a one-function bug in interface/dispatch.py. The long-term recommendation (subprocess pid registry) is disproportionate for this system's scale.

**corrected claim:** interface/dispatch.py::run_shell (used by the REPL `!` command at :187 with a 120 s timeout and by the `skill` install clone path _clone_at at :1837-1849 with 180 s timeouts) calls subprocess.run synchronously on the asyncio loop thread, stalling every other channel (voice, HTTP, Telegram) for the command's duration; the tool-side run_shell in execution/shell.py:222 already does it right via asyncio.to_thread. This is a genuine but one-line bug. The hard os._exit exit path is a documented, deliberate trade-off (kernel/cli.py:80-86) that is proportionate for a single-laptop system, and in-flight tool actions are already tracked in a ledger stream and reconciled at next boot (execution/service.py:702-713). The hardcoded 30 s Supervisor boot timeout (supervisor.py:40) has no evidence of ever having fired and does not warrant a config key.

### evidence

- grep counts over simorgh/ (reproduced): asyncio.to_thread 138, subprocess.run( 46, threading.Thread( 1, run_coroutine_threadsafe 5 matches of which 1 is code (interface/service.py:720)
- simorgh/interface/dispatch.py:166-172 run_shell: `result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)` inside `async def`, no to_thread; :187 `if name == "!": return Outcome(await run_shell(args, timeout=120.0))`
- simorgh/interface/dispatch.py:1837-1849 _clone_at: `await run_shell(f"git clone --depth 1 --quiet {url} {into}", timeout=180.0)` and fetch/checkout/rev-parse the same way; called from the `skill` command (:274)
- simorgh/execution/shell.py:222-223: `completed = await asyncio.to_thread(subprocess.run, ...` -- the tool-side implementation is correctly off-loop
- simorgh/kernel/cli.py:80-86 comment documents the reproduced hang (thread alive 90 s after two signals, 2026-09-11) that motivated `_HARD_EXIT = os._exit`; :108-129 _exit_now docstring: called after an orderly Kernel.shutdown() on purpose
- simorgh/kernel/config.py:82,119: [runtime] stop_grace_s is already configurable; cli.py:190-198 uses grace+5.0 for shutdown and grace+10.0 for the watchdog
- simorgh/execution/service.py:196 `await self._replay_inflight()`; :702-713 replays INFLIGHT_STREAM started-minus-finished and publishes ACTION_RESULT error="interrupted by restart" for each -- in-flight tool work is tracked and reconciled
- simorgh/execution/mcp.py:151 `self._process.terminate()`, :190 `self._process.kill()` -- long-lived MCP child processes are already terminated deterministically
- simorgh/kernel/supervisor.py:40 `boot_timeout_s: float = 30.0`; :68 wait_for(...timeout=self._boot_timeout_s); simorgh/kernel/service.py:226-230 Supervisor(...) constructed without boot_timeout_s -- confirmed
- grep -rl 'did not start within' ~/.simorgh/ledger/streams/ -> 3 trace files, all reading 'Backyard Door Left: the stream did not start within 12 s; ...' (camera streams), zero Supervisor BootTimeout occurrences
- simorgh/voice/service.py:4 (models loaded on first use) and :235 `await asyncio.to_thread(open_recogniser, ...)` -- the heaviest subsystem does not do its expensive work in start()
- grep -c 'os._exit|_exit_now|run_shell|boot_timeout' over docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md -> 0, 0, 0 (not previously reported)

**severity adjustment:** keep

