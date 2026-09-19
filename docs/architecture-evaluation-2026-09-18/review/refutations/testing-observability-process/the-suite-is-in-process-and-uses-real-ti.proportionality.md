# refute:proportionality:The suite is in-process and uses real ti

*Workflow: review · Phase: Refute · Agent id: `aec66f4f8446ac67a` · Tool calls: 10*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "testing-observability-process". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Count real sleeps, find subprocess tests, check pytest config | --- sleep counts 153 8 --- subprocess tests tests/simorgh/test_simloader.py tests/simorgh/test_trial_suite.py tests/simorgh/benchmark/test_a_mode_flip_is_not_a_ |
| 2 | Bash | Inspect simloader test, sim.sh guard, and conftest markers | --- test_simloader subprocess 3:`simloader.py` is deliberately stdlib-only and never imports `simorgh`, 5:the gate stubbed -- the gate is a subprocess of pytest |
| 3 | Bash | Read conftest, simloader test harness, gate config, shutdown tests, FakeClock | --- root conftest """Test-session isolation from the ambient environment. `kernel/config.py::_apply_env_overrides` lets `SIMORGH_<SECTION>_<KEY>` override a con |
| 4 | Bash | Check shutdown test, FakeClock, simloader status command and gate timing notes | --- test count 5493 --- test_stop_leaves """A signal ends the process (kernel/cli.py, 2026-09-11). Reproduced live: with one tool thread busy (a pytest, a whisp |
| 5 | Bash | Sleep value distribution, simloader watchdog, suite-speed memory, cast test sleeps | --- sleep distribution 43 asyncio.sleep(0.01) 33 asyncio.sleep(0.05) 17 asyncio.sleep(0.3) 11 asyncio.sleep(0.02) 10 asyncio.sleep(0.1) 8 asyncio.sleep(0.005) 5 |
| 6 | Bash | Check cast sleeps, loader notes for gate duration, flaky test memory, gate scope | Exit code 1 --- cast.py sleeps context self._zconf = zeroconf.Zeroconf() self._browser = CastBrowser(SimpleCastListener(), self._zconf) self._browser.start_disc |
| 7 | Bash | Locate loader notes, gate scope, flaky memory, cast sleep sites | --- notes path 748:def write_note(notes: Path, note: dict) -> None: 1064: parser.add_argument("--notes", default=None, blobs heads idem index.json LOCK snapshot |
| 8 | Bash | Time the cast test file once to check the 32s claim | (eval):1: command not found: timeout |
| 9 | Bash | Time the cast test file once to check the 32s claim |  <frozen importlib._bootstrap>:488: DeprecationWarning: Type google.protobuf.pyext._message.ScalarMapContainer uses PyType_Spec with a metaclass that has custom |
| 10 | Bash | Read the 30s cast test and find the unpatched 30s wait |  async def test_unpaired_the_file_path_is_used_and_the_tools_say_how_to_pair(self): tools, cast, bus = self._tools() r = await tools["cast_play"].run({"url": "h |

## Structured reply

**refuted:** False

**verdict:** partly-true

**corrected claim:** The unit suite runs in-process with 153 asyncio.sleep(>0) calls (but 76 of them are 0.01–0.05s; the measured 32s in test_cast.py is ONE test hitting an unpatched 30.0s constant at simorgh/execution/media/cast.py:674), and there is no pytest.ini or pytest-timeout. However the process boundary is not unverified: the gate itself is a subprocess with a hard wall timeout and kill (simloader.py:376-427, default --timeout 5400 at :1072) and already passes `-p no:cacheprovider` (:574); simloader.py runs `python -m simorgh run` as a child and treats a non-zero exit inside a 60s watchdog as a bad boot on every start (:1042-1057, :1074); and test_simloader.py exec-loads the real simloader.py (:21-25) so a non-compiling loader fails the gate. The one genuinely uncovered process-level path is signal-driven shutdown, tested only with _HARD_EXIT patched (tests/simorgh/kernel/test_stop_leaves.py:34).

**reasoning:** The raw evidence checks out (153 sleeps, 8 time.sleep, no ini, no pytest-timeout, 32.38s for test_cast.py, sim.sh guard text), but the architectural inference drawn from it does not hold at this system's scale. (1) "No timeout plugin" is moot: the gate is already a subprocess with its own deadline, chunked-read watchdog and kill path, and the '45 seconds' figure appears nowhere in code (the default is 5400s). (2) "-p no:cacheprovider" is already in the gate's pytest argv. (3) "No v2 test crosses the process boundary" is materially wrong for boot: simloader's watchdog runs `python -m simorgh run` as a child on every start and rolls back on a fast non-zero exit; a `--self-check` subprocess test would duplicate that. (4) The simloader bricking is a chicken-and-egg (the loader runs the gate), so neither an in-process nor a subprocess pytest could have caught it; only an out-of-band guard can, and that is exactly what sim.sh:35-52 is. The recommendation would not have prevented that incident. (5) The 153-sleep number is misleading: the distribution is dominated by 5–50ms yields, and the one slow file is a single test awaiting an unpatched 30.0s constant, which is a one-line test fix, not a suite architecture issue. (6) xdist order-sensitivity is asserted, not shown; the one known flaky test is documented as an in-process scheduling race. Replacing FakeClock across ~50 boot tests and adding a third-party pytest plugin to a stdlib-first, one-developer project to recover ~30s is disproportionate. What survives: patch the 30s constant in test_cast.py, and optionally one subprocess test that sends SIGINT/SIGTERM to a booted process with a busy tool thread, since Stopper's real os._exit path is the only remembered incident with no process-level check.

### evidence

- `grep -rhE 'asyncio\.sleep\(0?\.[0-9]+|asyncio\.sleep\([1-9]' tests/simorgh | wc -l` -> 153; `time.sleep(` -> 8; `grep -rhE '^\s*(async )?def test_' tests/simorgh | wc -l` -> 5493 (confirms scale).
- Sleep distribution (`grep -rhoE ... | sort | uniq -c`): 43x sleep(0.01), 33x sleep(0.05), 17x 0.3, 11x 0.02, 10x 0.1, 8x 0.005 -- 76 of 153 are <=50ms yields, not real waits.
- Measured: `python -m pytest -q -p no:cacheprovider tests/simorgh/execution/media/test_cast.py --durations=6` -> `32 passed in 32.38s`, of which `30.02s call ...test_unpaired_the_file_path_is_used_and_the_tools_say_how_to_pair`; next slowest 1.29s. Cause: simorgh/execution/media/cast.py:674 `time.monotonic() - started > 30.0` (watcher gives up after 30s), awaited by the test via `await asyncio.gather(*tools["cast_play"]._fetches)`; IDLE_POLL_S and _WAKE_SETTLE_S are patched (test_cast.py:236,426,521,611) but this constant is not.
- simloader.py:574 already runs `[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *pytest_parallel_args(), ...]` -- the recommended `-p no:cacheprovider` is already in place.
- simloader.py:376-427 `stream()` enforces `deadline = time.monotonic() + timeout_s`, raises TimeoutExpired and kills the child; :583 `return False, f"unit suite exceeded {timeout_s:.0f}s"`; :1072 `--timeout` default 5400.0. The gate has a hard wall timeout without pytest-timeout; no '45 seconds' constant exists in the code.
- simloader.py:1057 `subprocess.run([sys.executable, "-m", "simorgh", "run", *sim_args], cwd=repo, env=env)`; :1042-1045 `if returncode != 0 and ran_for < watchdog_s: why = f"Sim exited {returncode} after {ran_for:.0f}s, inside the {watchdog_s:.0f}s watchdog"` -> the boot IS a process-boundary check, executed on every start via sim.sh.
- tests/simorgh/test_simloader.py:21-25 `_spec = importlib.util.spec_from_file_location("simloader", _LOADER) ... _spec.loader.exec_module(simloader)` -- the real simloader.py is compiled and loaded by the gate's own collection; a syntax error fails the suite. The 2026-09-08 brick (sim.sh:33-40) happened because the loader that runs the gate was itself broken; no pytest test of any kind could have caught that.
- tests/simorgh/kernel/test_stop_leaves.py:34 `with mock.patch.object(cli, "_HARD_EXIT", exits.append), mock.patch.object(cli, "_terminate_children")` -- shutdown is verified in-process only; this is the one part of the claim that stands.
- `ls pytest.ini pyproject.toml setup.cfg tox.ini` -> none exist; `pip list | grep -i pytest` shows pytest 8.3.5, pytest-asyncio 0.26.0, pytest-xdist 3.8.0, no pytest-timeout; conftest.py:58-62 registers only the `live` marker.
- memory project_autotesting_paused_2026-09-09.md:19 attributes the one known flaky test to an in-process scheduling race in Interface._handle_line, not to real sleeps or xdist ordering.
- memory project_test_suite_speed.md: FakeClock spin costs ~17s (test_flow_5) + ~13s (worktree landing) and 'Changing FakeClock touches about 50 boot tests' -- the recommended rewrite is ~50 test edits for ~30s.

**severity adjustment:** lower

