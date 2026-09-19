# refute:correctness:The suite is in-process and uses real ti

*Workflow: review · Phase: Refute · Agent id: `acb11c8e85e9ebca3` · Tool calls: 6*

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
    "title": "The suite is in-process and uses real time; the two incidents that bricked the system were process-level",
    "kind": "right-design-undermined",
    "severity": "low",
    "claim": "5,515 tests run entirely inside pytest's process with 153 real asyncio.sleep(>0) waits and no timeout plugin configured, while the incidents the project remembers (a non-compiling simloader, Ctrl-C ignored by a busy tool thread) live at the process boundary no v2 test crosses.",
    "evidence": [
      "`grep -rhE 'asyncio.sleep\\(0?\\.[0-9]+|asyncio.sleep\\([1-9]' tests/simorgh | wc -l` -> 153; `time.sleep(` -> 8; tests/simorgh/execution/media/test_cast.py with a fake backend: `32 passed in 32.41s` (measured).",
      "`grep -rn '\"-m\", \"simorgh\"' tests/simorgh` -> nothing; sim.sh:35-52 exists because 'a syntax error in simloader.py bricked the system completely'.",
      "No pytest.ini/pyproject/setup.cfg; `pip list` shows pytest-xdist 3.8.0 and pytest-asyncio 0.26.0 but no pytest-timeout; conftest.py registers only the `live` marker.",
      "memory project_test_suite_speed.md: FakeClock.sleep busy-spins the scheduler in booted-Kernel tests (test_flow_5_pause_resume_stop ~17s), still open."
    ],
    "why_it_matters": "Real sleeps make the gate's 45 seconds drift upward silently and make xdist results order-sensitive; the absence of any subprocess test means the one file whose failure has no rollback (simloader.py) and the shutdown path are verified only by sim.sh's runtime guard.",
    "recommendation": "Add pytest.ini with `timeout = 120` (install pytest-timeout) and `-p no:cacheprovider`, replace the FakeClock spin with a scheduler that awaits a clock event, and add one CORE subprocess test that runs `python simloader.py status` and `python -m simorgh --self-check` and asserts exit 0 within 60s.",
    "confidence": 0.8
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Check sleep counts, subprocess tests, pytest config, installed plugins | --- sleep counts 153 8 --- test count 5493 --- -m simorgh in tests tests/simorgh/test_simloader.py tests/simorgh/test_trial_suite.py tests/simorgh/benchmark/tes |
| 2 | Bash | Check for subprocess-level tests, conftest, sim.sh guard, simloader test | --- -m simorgh literal tests/simorgh/test_simloader.py:3:`simloader.py` is deliberately stdlib-only and never imports `simorgh`, tests/simorgh/test_simloader.py |
| 3 | Bash | Inspect simloader subprocess tests, shutdown tests, and gate config | --- test_simloader _run import subprocess import sys import tempfile import unittest from pathlib import Path from unittest import mock _LOADER = Path(__file__) |
| 4 | Bash | Read memory note, shutdown tests, crash-resume test, simloader reload tests, FakeClock, gate timeout | --- memory test_suite_speed --- name: test-suite-speed description: "Why Simorgh's tests were slow (8 min gate) and what fixed it on 2026-09-14; what is still s |
| 5 | Bash | Read crash-resume process test, landing gate, cast test sleeps, gate paths | --- crash_resume 150-235 await self._bus.reply(message, type=topics.TASK_CLAIM_REPLY, payload={"granted": task is not None, "task": task or {}}) class TestWorke |
| 6 | Bash | Check core test paths, landing gate, gate duration records, FakeClock | --- CORE_TESTS # is any test marked `live` -- a real network service, Docker or a # browser. A boot must not fail, or take eight minutes, because the house # is |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The measurable parts of the claim hold: 153 asyncio.sleep(>0) and 8 time.sleep calls in tests/simorgh (my grep reproduces the reader's counts exactly); there is no pytest.ini/pyproject.toml/setup.cfg/tox.ini; pytest-timeout is not installed (pytest 8.3.5, pytest-asyncio 0.26.0, pytest-xdist 3.8.0 are); the root conftest.py registers only the `live` marker; FakeClock.sleep still advances time and yields (tests/simorgh/helpers.py:27-29), so the scheduler spin the memory note describes is current; the shutdown Stopper is tested only in-process with `_HARD_EXIT` and `_terminate_children` patched (tests/simorgh/kernel/test_stop_leaves.py:34-77), never with a real signal; and sim.sh:32-52 exists exactly for the non-compiling-loader incident. However the headline "no v2 test crosses the process boundary" is false: tests/simorgh/integration/test_local_multi_worker_crash_resume.py:211-228 spawns two real `simorgh worker` OS processes (multiprocessing spawn context), SIGKILLs one mid-task and SIGTERMs the other to exercise the graceful signal handler; and test_simloader.py:602-618 drives simloader.stream with real child processes including a kill-on-overrun. What is true is narrower: the crash-resume test is not in simloader's CORE_TESTS gate list (simloader.py:529-542), and nothing runs `python simloader.py` or `python -m simorgh` itself as a subprocess (literal grep for '"-m", "simorgh"' returns nothing). Two supporting statements are unsupported: the "gate's 45 seconds" figure appears nowhere in simloader.py or docs (the only gate bound is `--timeout` default 5400 s, simloader.py:1072); and "no timeout" is only true per-test, since simloader.stream kills the whole pytest child at timeout_s (simloader.py:406-410, 583). Finally, the "verified only by sim.sh's runtime guard" consequence is overstated: test_simloader.py exec_module()s simloader.py at collection time (lines 21-25) and is in the CORE gate, so any gate run by something other than the broken loader (e.g. the worktree landing gate that runs pytest via run_tests) fails collection on a simloader SyntaxError; the recommended `python simloader.py status` subprocess test adds nothing for that case and is circular at boot time because the loader is what runs the suite. Not on the known-findings list. Severity low is right.

### evidence

- `grep -rhE 'asyncio\.sleep\(0?\.[0-9]+|asyncio\.sleep\([1-9]' tests/simorgh | wc -l` -> 153; `grep -rhE 'time\.sleep\(' tests/simorgh | wc -l` -> 8 (reproduced)
- `ls pytest.ini pyproject.toml setup.cfg tox.ini` -> all 'No such file'; `pip list | grep -i pytest` -> pytest 8.3.5, pytest-asyncio 0.26.0, pytest-xdist 3.8.0, pytest-cov, pytest-mock; no pytest-timeout
- /Users/saeed/ws/Simorgh/conftest.py:71-75 pytest_configure registers only the `live` marker
- /Users/saeed/ws/Simorgh/tests/simorgh/helpers.py:27-29 `async def sleep(self, seconds): self._now += seconds; await asyncio.sleep(0)` (FakeClock spin still current)
- /Users/saeed/ws/Simorgh/sim.sh:32-52 compile-check of simloader.py with restore from newest sim-good-* tag, comment: 'a syntax error in simloader.py bricked the system completely ... (2026-09-08)'
- /Users/saeed/ws/Simorgh/tests/simorgh/kernel/test_stop_leaves.py:34,46,57,66,77 every Stopper test patches `cli._HARD_EXIT` and `cli._terminate_children`; no signal is delivered
- REFUTING: /Users/saeed/ws/Simorgh/tests/simorgh/integration/test_local_multi_worker_crash_resume.py:211-228 `ctx = mp.get_context("spawn"); worker1 = ctx.Process(target=_run_worker, ...); worker1.kill()  # SIGKILL` and `worker2.terminate()  # SIGTERM -- the graceful path _cmd_worker's signal handler takes` -- a real cross-process, real-signal test
- REFUTING: /Users/saeed/ws/Simorgh/tests/simorgh/test_simloader.py:602-618 `simloader.stream([sys.executable, "-c", ...], timeout_s=30/1)` runs real child processes and asserts kill-on-overrun
- /Users/saeed/ws/Simorgh/simloader.py:529-542 CORE_TESTS includes tests/simorgh/test_simloader.py but not integration/test_local_multi_worker_crash_resume.py
- /Users/saeed/ws/Simorgh/tests/simorgh/test_simloader.py:21-25 `_spec.loader.exec_module(simloader)` at module import -> a SyntaxError in simloader.py fails collection of a CORE gate file
- /Users/saeed/ws/Simorgh/simloader.py:1072 `--timeout` default 5400.0; simloader.py:406-410 stream raises TimeoutExpired and kills the child; :583 'unit suite exceeded {timeout_s}s' -- gate-level timeout exists, per-test does not; no '45' second gate figure found in simloader.py, docs/findings or docs/architecture-audit-2026.md
- `grep -rn '"-m", "simorgh"' tests/simorgh` -> no matches (reproduced); no test runs `python simloader.py <cmd>` as a subprocess

**severity adjustment:** keep

**corrected claim:** The ~5,500-test suite has no per-test timeout (no pytest.ini, pytest-timeout not installed; only simloader's whole-gate --timeout of 5400 s bounds a hang), 153 real asyncio.sleep(>0) waits, and a FakeClock.sleep that still busy-spins the Kernel scheduler in booted-Kernel tests. Process-boundary tests do exist (test_local_multi_worker_crash_resume.py SIGKILLs/SIGTERMs real `simorgh worker` processes; test_simloader.py runs real children through simloader.stream), but the crash-resume test is outside the CORE gate, no test runs `python simloader.py` or `python -m simorgh` as a subprocess, and the Ctrl-C/Stopper path is tested only with os._exit patched. A non-compiling simloader.py is caught at land time by test_simloader.py's collection-time import inside the core gate and at boot time by sim.sh's compile check; an in-suite subprocess test would not add coverage for the boot case because the loader is what runs the suite.

