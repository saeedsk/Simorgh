# refute:proportionality:Under the loader, a terminal SIGINT SIGK

*Workflow: review · Phase: Refute · Agent id: `a3f3757cfe4aba2f7` · Tool calls: 4*

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
| 1 | Bash | Read launch_sim and grep for signal handling in loader |  # notice and re-run by hand. restarts += 1 say(f"Sim asked to restart (after {ran_for:.0f}s) -- re-gating the current checkout", "step") write_note(notes, {"ki |
| 2 | Bash | Read Stopper, grace default, TUI ISIG, sim.sh launch and CPython subprocess.run SIGINT path | Exit code 1 try: subprocess.run(["stty", "sane"], stdin=sys.stdin, capture_output=True, timeout=2) except (OSError, subprocess.SubprocessError): pass _HARD_EXIT |
| 3 | Bash | Inspect CPython subprocess.run SIGINT path, signal wiring in cli.py, and ledger stop reasons | Python 3.12.4 def __exit__(self, exc_type, value, traceback): if self.stdout: self.stdout.close() if self.stderr: self.stderr.close() try: # Flushing a Buffered |
| 4 | Bash | Reproduce SIGINT-to-group with subprocess.run parent and slow-shutdown child; count ledger stop reasons | parent: KeyboardInterrupt after 1.24s --- child.log: child: up child: got SIGINT, orderly shutdown 3s ---- {"causation_id":null,"idempotency_key":null,"payload" |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every cited fact checks out against the code and a fresh reproduction. simloader.py:1057 is a bare `subprocess.run([...,"-m","simorgh","run"], cwd=repo, env=env)` and the file contains no `signal.` or `KeyboardInterrupt` handling. CPython 3.12.4 on this machine has `Popen._sigint_wait_secs = 0.25`; `Popen.__exit__` waits that long on KeyboardInterrupt, then `subprocess.run`'s `except:` branch calls `process.kill()`. simorgh/kernel/cli.py:179-183 builds `Stopper(kernel.bus, hard_exit_s=grace + 10.0)` and installs it for SIGINT/SIGTERM, with stop_grace_s defaulting to 15.0 (api.py:46); that whole bounded-shutdown design is unreachable when the loader is the parent and the terminal delivers SIGINT to the group. I re-ran the standalone reproduction (parent = plain subprocess.run, child = 3 s orderly SIGINT handler, SIGINT via os.killpg): parent reported KeyboardInterrupt after 1.24 s and the child log ends at "got SIGINT" with no DONE line. The KeyboardInterrupt then propagates out of launch_sim, so the loader's watchdog/notes bookkeeping after the call is also skipped. This is a genuine bug (category c), and the two-supervisors-unaware-of-each-other framing is fair. On the skeptic lens: it is not an architectural problem at this scale and the recommendation is proportionate (a SIG_IGN around Popen or Popen+wait(timeout) is a handful of lines with no design change). The practical exposure is narrow: interface/tui.py:493 keeps ISIG off so the everyday Ctrl-C is a keypress, and the system stream shows ~250 boots with 244 "drained" stops, 158 repl_exit, 52 user exit, 31 repl_restart and only 2 "interrupt" (I found 0 literal "signal" reasons, the finding said 1; the difference is immaterial, and SIGKILLed runs by construction leave no stop event so the count under-reports slightly). The lost artefacts are a `stopped` state event, loader notes and tags, not ledger integrity. Severity should be low rather than medium: real, cheap to fix, rarely hit.

### evidence

- simloader.py:1054-1057: `return subprocess.run([sys.executable, "-m", "simorgh", "run", *sim_args], cwd=repo, env=env).returncode` -- no signal handling; `grep -n 'KeyboardInterrupt\|signal\.\|SIG_IGN' simloader.py` returns nothing.
- python3 -c inspect of subprocess (Python 3.12.4): `_sigint_wait_secs = 0.25  # 1/xkcd221.getRandomNumber()`; Popen.__exit__ on KeyboardInterrupt does `self._wait(timeout=self._sigint_wait_secs)` then returns, after which subprocess.run's except branch kills the child.
- Scratchpad reproduction (parent.py = plain subprocess.run, child.py = SIGINT handler sleeping 3 s, os.killpg SIGINT at t=1.0 s): output `parent: KeyboardInterrupt after 1.24s`; child.log = `child: up` / `child: got SIGINT, orderly shutdown 3s` with no DONE line.
- simorgh/kernel/cli.py:132-156 Stopper class (first signal publishes stop + starts hard_exit_s watchdog; second signal exits at once); cli.py:179-183 `stopper = Stopper(kernel.bus, hard_exit_s=grace + 10.0, loop=loop)` installed via loop.add_signal_handler for SIGINT and SIGTERM.
- simorgh/kernel/api.py:46 `stop_grace_s: float = 15.0`.
- simorgh/interface/tui.py:493-495 docstring: prompt_async holds raw mode with `ISIG` off so Ctrl-C is a key event instead of a real SIGINT -- everyday Ctrl-C at the prompt does not take this path.
- sim.sh:57 `exec "$PYTHON_BIN" simloader.py run "$@"` -- the standard launch does go through the loader as parent.
- ~/.simorgh/ledger/streams/system.jsonl (746 lines): reason counts 250 'boot complete', 244 'drained', 158 'repl_exit', 52 'user exit', 31 'repl_restart', 2 'interrupt', 0 'signal' -- signal-driven stops are rare in practice.

**severity adjustment:** lower

**corrected claim:** Under the loader, a terminal SIGINT delivered to the process group causes the loader's plain subprocess.run to SIGKILL Sim 0.25 s after the KeyboardInterrupt, bypassing stop_grace_s, the Stopper watchdog, the final stop/drained ledger event and the loader's post-run bookkeeping. It is a real but low-frequency bug: the TUI keeps ISIG off so ordinary Ctrl-C at the prompt is a keypress, and the ledger shows only ~2 interrupt-driven stops across ~250 boots. The exposure is boot, the readline fallback, headless runs and explicit kill -INT to the group. A local fix of a few lines (ignore SIGINT in the loader around Popen, or Popen+wait with a grace timeout) is proportionate; no architectural change is warranted.

