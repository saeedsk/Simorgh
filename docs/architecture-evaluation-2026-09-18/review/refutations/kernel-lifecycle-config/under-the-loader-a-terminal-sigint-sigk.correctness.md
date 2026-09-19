# refute:correctness:Under the loader, a terminal SIGINT SIGK

*Workflow: review · Phase: Refute · Agent id: `ac5e84c45b6543785` · Tool calls: 5*

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
    "title": "Under the loader, a terminal SIGINT SIGKILLs Sim 250 ms into its orderly shutdown",
    "kind": "bug",
    "severity": "medium",
    "claim": "simloader.launch_sim uses a plain subprocess.run with no signal handling; a Ctrl-C reaches both processes, CPython's subprocess.run waits 0.25 s for the child and then kill()s it, so stop_grace_s, the Stopper watchdog, the final `stopped` ledger event and the loader's own bookkeeping are all skipped whenever the signal is delivered to the group.",
    "evidence": [
      "simloader.py:1053-1057 `subprocess.run([sys.executable, \"-m\", \"simorgh\", \"run\", *sim_args], cwd=repo, env=env)`; grep 'KeyboardInterrupt|signal.' in simloader.py: no matches.",
      "Standalone reproduction in the scratchpad (parent = plain subprocess.run, child = SIGINT handler doing a 3 s orderly shutdown, SIGINT sent to the process group): output 'parent: KeyboardInterrupt after 1.24 s' (1.0 s delay + 0.25 s _sigint_wait_secs), 'child alive 4s later: False', child.log 'got SIGINT' with no 'orderly shutdown DONE' line.",
      "simorgh/kernel/cli.py:132-156 Stopper expects grace+10 s (stop_grace_s default 15, api.py:46).",
      "Frequency is low in practice: ~/.simorgh/ledger/streams/system.jsonl stop reasons are repl_exit 158, user exit 52, repl_restart 31, signal 1; interface/tui.py:493 keeps ISIG off so Ctrl-C at the prompt is a keypress, not a signal. The path is live during boot, the gate, the readline fallback, headless runs, and `kill -INT -<pgid>`."
    ],
    "why_it_matters": "Two process supervisors (loader and Kernel Stopper) that do not know about each other: the Kernel's carefully bounded shutdown is unreachable in the standard launch path for the one signal a terminal sends. A SIGKILL mid-append is exactly what the ledger's fsync discipline exists to survive, but the `stopped` state, notes and tags are lost.",
    "recommendation": "In launch_sim, ignore SIGINT in the loader for the child's lifetime (`signal.signal(SIGINT, SIG_IGN)` before Popen, restore after), or use Popen + wait() and on KeyboardInterrupt wait(timeout=stop_grace+15) before killing. Five lines.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read launch_sim and grep signal handling in simloader |  # notice and re-run by hand. restarts += 1 say(f"Sim asked to restart (after {ran_for:.0f}s) -- re-gating the current checkout", "step") write_note(notes, {"ki |
| 2 | Bash | Read Stopper, grace default, TUI ISIG, sim.sh launch, ledger stop reasons, CPython run() behaviour |  stream.flush() except (OSError, ValueError): pass _terminate_children() if sys.stdin is not None and hasattr(sys.stdin, "isatty") and sys.stdin.isatty(): try:  |
| 3 | Bash | Check CPython wait() SIGINT path, kernel signal handler registration, sim.sh python, ledger signal events |  tool. self._sigint_wait_secs = 0.25 # 1/xkcd221.getRandomNumber() meout=timeout) except KeyboardInterrupt: # https://bugs.python.org/issue25942 # The first key |
| 4 | Bash | Confirm signal registration, stopped event, loader exception handling, and run a standalone SIGINT reproduction |  loop = asyncio.get_running_loop() grace = float(getattr(kernel.runtime, "stop_grace_s", 15.0)) stopper = Stopper(kernel.bus, hard_exit_s=grace + 10.0, loop=loo |
| 5 | Bash | Check stopped event emission and whether prior reviews mention the loader SIGINT issue | simorgh/kernel/state.py:23:STOPPED = "stopped" simorgh/kernel/supervisor.py:146: self.services[name].status = "stopped" ---- known docs docs/architecture-review |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every load-bearing element of the claim checks out against the code as it exists today, not history. (1) simloader.py:1054-1057 `launch_sim` is a bare `subprocess.run([sys.executable, "-m", "simorgh", "run", ...])` and a grep for `KeyboardInterrupt|signal.|SIG_IGN|SIGINT` in simloader.py returns nothing; `main` (line 1060) has no KeyboardInterrupt handling either. (2) sim.sh:57 `exec "$PYTHON_BIN" simloader.py run "$@"` is the standard launch path, so the loader is the terminal's foreground process-group leader and Sim is its child in the same group; a terminal Ctrl-C reaches both. (3) The installed CPython confirms the mechanism: `Popen.__init__` sets `self._sigint_wait_secs = 0.25`, `Popen.wait()` catches KeyboardInterrupt, waits at most that long, re-raises, and `subprocess.run`'s bare `except:` then calls `process.kill()` (SIGKILL). (4) The Kernel side is as claimed: simorgh/kernel/cli.py:180-183 registers `stopper.on_signal` for SIGINT/SIGTERM, Stopper (cli.py:132-156) publishes SYSTEM_STOP and arms a `grace + 10` s watchdog with grace from `stop_grace_s` (api.py:46, default 15.0), and cli.py:192 awaits `kernel.shutdown()` with `grace + 5` s. None of that can complete in 0.25 s, so it is SIGKILLed mid-shutdown. (5) A standalone reproduction in the scratchpad (parent = plain subprocess.run, child = SIGINT handler doing a 3 s orderly shutdown, SIGINT sent via killpg to a fresh session) printed 'child: got SIGINT, orderly shutdown 3s', 'parent: KeyboardInterrupt after 1.24s', and no 'orderly shutdown DONE'; no surviving child pid afterwards. (6) Frequency claim is roughly right: ~/.simorgh/ledger/streams/system.jsonl has 158 repl_exit, 52 user exit, 31 repl_restart, 2 interrupt, 1 "reason":"signal" stops, and interface/tui.py:489-493 documents ISIG off at the prompt, so the path is rare interactively but live during boot/gate/headless/`kill -INT -pgid`. The `stopped` ledger state exists (kernel/state.py:23 STOPPED). One nit: the loader's own bookkeeping is also skipped because `run_sim`'s watchdog/rollback logic (simloader.py:1042-1051) never sees a returncode when KeyboardInterrupt propagates. Not in the known-findings list and not in the prior review docs (grep for sigint/signal/kill in docs/architecture-audit-2026.md and architecture-review-2026-09-18.html finds nothing relevant). Severity medium is fair: a genuine bug (category c), low frequency, but it silently defeats a deliberately designed shutdown path in the standard launch; the recommended five-line fix (SIG_IGN in the loader around the child's lifetime, or Popen+wait with a grace-sized timeout on KeyboardInterrupt) is correct and minimal.

### evidence

- simloader.py:1054-1057: `def launch_sim(...)` -> `return subprocess.run([sys.executable, "-m", "simorgh", "run", *sim_args], cwd=repo, env=env).returncode` -- no Popen, no signal handling.
- `grep -nE 'KeyboardInterrupt|signal\.|SIG_IGN|SIGINT' simloader.py` -> no matches; only `except subprocess.TimeoutExpired` at 582/622.
- sim.sh:15 `PYTHON_BIN="${SIMORGH_PYTHON:-python3}"`; sim.sh:57 `exec "$PYTHON_BIN" simloader.py run "$@"` -- loader is the foreground process, Sim its child in the same process group.
- python3 -c inspect of installed CPython: Popen.__init__ `self._sigint_wait_secs = 0.25`; Popen.wait() `except KeyboardInterrupt: ... self._wait(timeout=sigint_timeout) ... raise`; subprocess.run `except:  # Including KeyboardInterrupt ... process.kill()`.
- simorgh/kernel/cli.py:177-183: `grace = float(getattr(kernel.runtime, "stop_grace_s", 15.0))`; `Stopper(kernel.bus, hard_exit_s=grace + 10.0, ...)`; `loop.add_signal_handler(sig, stopper.on_signal)` for SIGINT and SIGTERM. cli.py:192 `await asyncio.wait_for(kernel.shutdown(), timeout=grace + 5.0)`.
- simorgh/kernel/api.py:46 `stop_grace_s: float = 15.0`.
- simorgh/interface/tui.py:489-493 docstring: prompt_async holds raw mode with `ISIG` off so Ctrl-C is a key event, not a real SIGINT.
- Scratchpad reproduction (driver -> parent using plain subprocess.run -> child with 3 s SIGINT handler, os.killpg SIGINT after 1 s): output 'child: got SIGINT, orderly shutdown 3s' / 'parent: KeyboardInterrupt after 1.24s' / 'driver: surviving child pids: ''' -- no 'orderly shutdown DONE' line.
- ~/.simorgh/ledger/streams/system.jsonl stop reasons: 158 repl_exit, 52 user exit, 31 repl_restart, 2 interrupt, 1 "reason":"signal".
- simloader.py:1042-1051: watchdog/rollback bookkeeping keys off `returncode` from launch_sim, which is never returned when KeyboardInterrupt propagates; main() at 1060 has no handler.
- grep -i 'sigint|ctrl-c|signal' over docs/architecture-audit-2026.md, docs/architecture-review-2026-09-18.html, docs/architecture-third-opinion-2026-09-18.md: no prior report of this finding.

**severity adjustment:** keep

