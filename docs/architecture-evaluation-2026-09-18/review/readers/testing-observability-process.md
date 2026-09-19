# read:testing-observability-process

*Workflow: review · Phase: Read · Agent id: `a55cd2a7d595cba47` · Tool calls: 48*

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
  
  
  CONCERN: verification of the whole -- test suite shape, integration/e2e tests, the trial harness, observer kit, benchmark unit, tracing/observability, docs/findings process, and the Verification subsystem's role.
  Read tests/ layout (count per subsystem; find integration/e2e tests, tests/simorgh/integration/test_cli_end_to_end.py), conftest.py, tools/ (trial.py, trial_suite.py, observer_kit.py, bench_instance.py), simorgh/verification/, simorgh/benchmark/ briefly, docs/findings/README.md, docs/observer-testing.md.
  Questions: The project's own notes say unit tests assert code shape and missed every real blocker; is the suite (90k lines, 447 files -- larger than the code) giving proportional confidence, or is it mostly mock-heavy shape testing? Count tests that boot real subsystems vs. pure unit. How long does the suite take (do NOT run it; read notes/CI config/markers)? Is the bootloader gate running THIS suite, and if so is it gating on tests that would not catch the failures that matter? Is there any load/latency/regression benchmark for the daily path (chat + voice)? Is tracing (trace:<id> streams) usable for debugging a bad turn, or noise? Is the Verification subsystem (11 mechanical checks) the right idea? Evaluate the project's approach to knowing whether it works.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | List repo, tests layout, and line counts | __pycache__ conftest.py dash.sh docs games images papers project_simorgh_groundwork.md README.md requirements.txt results sim.sh simloader.py simorgh simorgh_pa |
| 2 | Bash | Count tests and code per subsystem | === per subsystem test counts (files / lines) === __pycache__: 0 files, 0 lines benchmark: 17 files, 2887 lines bus: 13 files, 1760 lines cognition: 14 files, 3 |
| 3 | Bash | Read conftest, pytest config, and what top-level tests import | === conftest === """Test-session isolation from the ambient environment. `kernel/config.py::_apply_env_overrides` lets `SIMORGH_<SECTION>_<KEY>` override a conf |
| 4 | Bash | Read simloader gate, sim.sh invocation, and src legacy size | === simloader gate === 22:- Every decision is printed as it is made, and every rollback is written 26:Known-good tags are `sim-good-<n>`, monotonically numbered |
| 5 | Bash | Read simloader docstring and gate logic | #!/usr/bin/env python3 """The Sim loader: a bootloader for a program that edits its own source. The creator, 2026-09-07: "at start up we should have an independ |
| 6 | Bash | Find loader notes directory and baseline files | 39:gate fails, step back one tag and try again, up to `--max-rollbacks`. 41:Sim exits non-zero inside `--watchdog` seconds, that counts as a bad 616: [sys.execu |
| 7 | Bash | Locate the loader's notes and baseline records and count blessed tags | def main(argv: list[str] \| None = None) -> int: parser = argparse.ArgumentParser(description="Boot Simorgh from a known-good tag, and keep it that way.") parser |
| 8 | Bash | Read loader notes: baselines, last gate outputs, decisions, tag dates | total 144 drwxr-xr-x 10 saeed staff 320 Sep 18 14:00 . drwxr-xr-x 34 saeed staff 1088 Sep 18 17:34 .. -rw-r--r-- 1 saeed staff 18 Sep 17 02:54 .last_rollback_in |
| 9 | Bash | Read trial verdicts and trial_suite docstring | === trial verdict lines === 13: PASS create-a-file completed 299s 37: FAIL edit-an-existing-file blocked 181s 67: PASS write-a-skill completed 236s 83: FAIL res |
| 10 | Bash | Read trial list and judge in trial_suite | TRIALS: tuple[Trial, ...] = ( Trial( "create-a-file", "create a new file simorgh/greeting.py containing a single function greet(name) " "that returns the string |
| 11 | Bash | Read docstrings of the tools harnesses | === trial.py === """Put one task to Sim, under control, and watch every turn. The creator, 2026-09-07, after this method found five separate blockers that had k |
| 12 | Bash | Read the Verification subsystem's checks and service | === verification pkg === 121 simorgh/verification/api.py 239 simorgh/verification/checklist.py 111 simorgh/verification/config.py 95 simorgh/verification/parsin |
| 13 | Bash | List verification checks and who requests verification | __init__.py __pycache__ _baseline.py _files.py denylist_immunity.py didanything.py docstring.py fullsuiteran.py invariants.py isolated_suite.py js_syntax.py ren |
| 14 | Bash | Read verification requesters, rigor, config defaults, and full_suite_ran check | === who requests verification === simorgh/learning/service.py:40: topics.LEARN_SKILL_ACQUIRED, topics.ACTION_PROPOSED, topics.VERIFY_REQUESTED, topics.MEMORY_ST |
| 15 | Bash | Read findings README and observer-testing doc | === findings README === # Findings Dated records of what was measured, what broke, what was fixed and what was decided, so a later session can start from eviden |
| 16 | Bash | Read integration test layout and the CLI end-to-end harness | === integration tests === __init__ __pycache__ test_a_patch_lands_through_a_worktree test_a_project_finishes_when_its_work_is_dead test_a_repeated_answer_stops_ |
| 17 | Bash | Read test helpers and the two architecture-level tests | === helpers === """Shared test helpers for the v2 suite (docs/blueprint/05 section 5): a controllable clock, a message builder that fills a valid payload for an |
| 18 | Bash | Count mock-heavy vs real-boot tests across the v2 suite | test funcs: 5515 async: 2553 files using unittest.mock/MagicMock/monkeypatch: 90 of 405 MagicMock/Mock( occurrences: 28 mock.patch occurrences: 298 class Fake*: |
| 19 | Bash | Read tracing writer and find who reads trace streams | === trace: writers === simorgh/ledger/streams.py:20: "trace:": "bus", simorgh/ledger/compaction.py:36:DEFAULT_RETENTION: dict[str, str] = {"trace:": "2d", "dead |
| 20 | Bash | Read how a trace is read back and whether trace ids reach the user | === cli.py trace reader === await worker.shutdown() return 0 async def _cmd_status(config_path: str \| None, timeout: float) -> int: config = load_config(config_ |
| 21 | Bash | Inspect the live ledger's trace streams, retention state, and sampling config | ledger dir: 1.4G blobs heads idem index.json LOCK entries: 7 trace files: 0 trace files older than 2d: 0 === ledger/bus toml === === bus default trace_sample == |
| 22 | Bash | Locate trace streams under the ledger and read bus trace sampling defaults | heads entries: 0 action%3A00058d0478bb.jsonl action%3A00069b23741c.jsonl action%3A000730a414ea.jsonl === find stream dirs === /Users/saeed/.simorgh/ledger /User |
| 23 | Bash | Measure trace stream volume and inspect one chat-turn trace | Command did not complete within its 120s timeout and was moved to the background (ID: b92n8t2jv). Output is being written to: /private/tmp/claude-501/-Users-sae |
| 24 | Bash | Read the project's own notes on test speed and what tests missed | === project_test_suite_speed.md === --- name: test-suite-speed description: "Why Simorgh's tests were slow (8 min gate) and what fixed it on 2026-09-14; what is |
| 25 | Bash | Search for any daily-path latency or regression benchmark and list pytest plugins | === latency/regression in tools/bench/tests === tools/bench_recall.py simorgh/benchmark/swebench.py tests/simorgh/benchmark/test_a_failure_stays_in_the_denomina |
| 26 | Bash | Check interface conftest, cast test marker, half-wired scanner usage, and invariants reality | === interface conftest === """Pin the terminal width for Interface tests. Rendering follows the real terminal (`render.terminal_width`), which is right for the  |
| 27 | Bash | Read the invariants check body and the cast test header | class InvariantsCheck: name = "invariants" cost = "free" def applies(self, req: VerifyRequest) -> bool: return bool(req.subject.get("path")) and ( req.subject.g |
| 28 | Bash | Read each check's applies() and what subject the session hands to verification | === applies() per check === simorgh/verification/checks/denylist_immunity.py:21: def applies(self, req: VerifyRequest) -> bool: simorgh/verification/checks/deny |
| 29 | Bash | Check which subject keys orchestration sends to verification | 14: "description": session.user_text, "result": text[:2000], "kind": session.kind, "steps": steps, 15: "complete_log": complete_log, "subject": session.subject  |
| 30 | Bash | Check what prior reviews already said about testing so I do not repeat them | === findings docs on suite/gate durations === === audit doc testing section === 13:## 3. Verified Architectural Gaps & Anti-Patterns === review html testing men |
| 31 | Bash | Extract prior reviews' statements about tests and verification | 8:1. **Guardian's HMAC Verification:** The separation of proposal and execution via HMAC tokens is a stellar security pattern. Every effect is published as `act |
| 32 | Bash | Read the parallel trial round test, trial-suite test, and the v1 e2e test | === parallel_trial_round === """Regressions from the parallel trial round, 2026-09-07. Ten observer agents each ran one kind of task against a sandbox copy and  |
| 33 | Bash | Read did_anything and trailing_narration check rationale | === did_anything === """`did_anything`: a patch task that wrote nothing did not patch anything. Observed 2026-09-08, in a real project run. Child task `6d7b8ed1 |
| 34 | Bash | Check trace CLI reachability, process-boundary e2e tests, and verification test subject shapes | === trace subcommand === 37: trace_p = sub.add_parser("trace", help="print the causal message trace for an id") 242:async def _cmd_trace(config_path: str \| None |
| 35 | Bash | Check TUI trace surfacing, subprocess e2e, and code-vs-test commit coupling | === tui trace lines === 390: traceback), show one dim line, never block.""" 391: import traceback 397: if exc is not None and getattr(exc, "__traceback__", None |
| 36 | Bash | Count commits that change code with tests, without, or tests only | tests-only: 3 code-only: 24 both: 103 |
| 37 | Read | /private/tmp/claude-501/-Users-saeed-ws-Simorgh/488b3cca-edac-4c83-98e1-f1e7db34bf14/tasks/b92n8t2jv.output | 1 streams total: 118215 trace: 88356 non-trace: 29859 2 trace in last 24h: 46264 3 oldest trace: Sep 16 13:57:30 2026 4 newest trace: Sep 18 17:14:18 2026 5 === |
| 38 | Bash | Tabulate what event types dominate single-event trace streams and show a multi-event trace | Exit code 127 (eval):1: command not found: timeout |
| 39 | Bash | Tabulate what event types dominate single-event trace streams and show a multi-event trace | sampled 400 one-event traces by type: [('world.camera.event', 52), ('ui.notice', 51), ('ui.hook.received', 44), ('persona.state.changed', 42), ('voice.listening |
| 40 | Bash | Probe whether chat turns get multi-event traces and which mechanical checks actually fire in the live ledger | Exit code 1 sampled 3000 traces containing cognition.think, by length: [(2, 69), (12, 1), (14, 4), (27, 1), (271, 1)] traces rooted at voice.transcript, by leng |
| 41 | Bash | Check how trace ids are assigned and whether chat/voice turns propagate them | === envelope trace_id assignment === 52: trace_id: str 70: trace_id: str \| None = None, 98: trace_id=trace_id or str(uuid.uuid4()), 116: trace_id=self.trace_id, |
| 42 | Bash | Read the chat-turn think publish and the verification request site | === chat think publish === offered = tuple(offered) + ("delegate",) catalog = self._catalog(session) if offered and not no_tools else "" if catalog and "use_ski |
| 43 | Bash | Check trace id on the think message and how verification derives kind and reversibility | === think Message.new tail === 12: ) + (f"\n\n{session.extra_rules}" if getattr(session, "extra_rules", "") else ""), === VerifyRequest === 31:class VerifyReque |
| 44 | Bash | Confirm think trace id, rigor gates, turn topics, retention scheduling, and verification test files | === think tail === "allow_summarize": is_chat, **self._tier(session), }, trace_id=session.task_id, clock=self._clock, ) reply = await self._bus.request_or_error |
| 45 | Bash | Read rigor gating in the verification service and check which kinds tests exercise |  verification_id=verification_id, task_id=task_id, kind=kind, subject=subject, checklist_hint=payload.get("checklist_hint"), reversibility=subject.get("reversib |
| 46 | Bash | Tabulate which mechanical checks have fired in the live ledger and with what status | verify streams sampled 349 verdict events 350 verdicts: [('fail', 220), ('pass', 109), ('insufficient_evidence', 21)] ('did_anything', 'failed') 12 ('did_anythi |
| 47 | Bash | Size the legacy v1 test share and when it was last touched | v1 top-level test functions: 887 v1 tests/tools test functions: 22 === last commit touching src/ === 2026-09-09 19:14:22 -0700 Design domains 4-5 and secret sou |
| 48 | Bash | Run the single cast unit test file that failed inside the trial lab | tests/simorgh/execution/media/test_cast.py::AndroidTvToolsTestCase::test_pairing_through_the_tool_then_youtube_plays_in_the_tvs_own_app <frozen importlib._boots |

## Structured reply

**concern:** Verification of the whole: test-suite shape, integration/e2e tests, trial harness, observer kit, benchmark unit, tracing/observability, findings process, and the Verification subsystem's role

**summary of what is actually there:** Two test trees coexist: tests/simorgh/ (405 files, 5,515 test functions, 2,553 async) for the v2 system, and tests/test_*.py (41 files, 11,574 lines, 887 test functions) which import only the dead v1 tree src/ (16,441 lines that nothing under simorgh/ imports; src last touched 2026-09-09, its tests 2026-09-06). There is no pytest.ini/pyproject/CI; the only configuration is the root conftest.py, which strips every SIMORGH_* variable and every model key from the session and forces SIMORGH_COGNITION_PROVIDER_ORDER=floor so booted Kernels answer offline (conftest.py:30-71), and registers a single `live` marker used by 6 files, all under tests/simorgh/execution. The bootloader simloader.py gates a checkout with a curated CORE_TESTS list (simloader.py:530-542, `-m "not live"`, six execution domains ignored) and reads pytest's own summary line rather than its exit code, refusing empty, skipped or shrunken runs (simloader.py:641-700); the last gate ran 3,348 tests in 45s (.simorgh_loader/unit_baseline-core.json). The trial suite (tools/trial_suite.py) boots a real Kernel in a copy-on-write repo clone, files one human task per trial, waits for a terminal status and judges the system's behaviour (commit made or not, tree clean, tool faults that are ours, ledger verify verdicts), but it only runs under `bless --full`, calls a paid model, takes ~25 minutes serially and depends on Together being up. The last full run (2026-09-18 14:00) was 3/7 clean and the creator then blessed four commits unit-only (decisions.jsonl). Integration tests are genuine: 43 files construct a real Kernel (33 in tests/simorgh/integration), test_kernel_boots_all_sixteen_subsystems boots all 17 real services, test_cli_end_to_end drives 17 lines through the real Interface `_handle_line`, and two architecture tests enforce import boundaries by AST and that a config section actually reaches its service. Nothing in tests/simorgh spawns `python -m simorgh` as a process; the only process-boundary e2e is the v1 tests/test_e2e_cli.py. The Verification subsystem registers 11 mechanical checks (simorgh/verification/checks/__init__.py:13-25) but the orchestration path hands it a subject of description/result/kind/steps/complete_log/subject/written_paths/base_ref/repo_root with wire kind always "task" (orchestration/session.py:1741, 1885-1890), so five checks whose `applies()` needs `candidate`/`code`/`original` or kind=="skill" never run, and the live ledger confirms it: over 349 sampled verify streams only six check names ever appear, verdicts split 220 fail / 109 pass / 21 insufficient_evidence, and full_suite_ran failed 56 of 62 times. Tracing writes one `trace:<id>` stream per root message (bus/trace.py:101) with a hand-maintained exclusion list (bus/config.py:60-64); the live ledger holds 88,356 trace streams from two days, 76% of a 400-file sample containing exactly one event, chat turns yield 2-event islands (think + reply) and voice turns 1-event islands, while only task sessions produce a chain. The benchmark unit (simorgh/benchmark) scores GAIA/BFCL/SWE-bench model capability; there is no latency or regression benchmark of the chat/voice path (only tools/bench_recall.py for memory retrieval and voice/bench.py for one STT sample). Findings are recorded in docs/findings (5 dated files since 2026-09-15), alongside a 5,254-line EVOLUTION.md, ~40 memory notes and observer findings JSONL under ~/.cache.

### strengths

- The loader never runs the code it judges and does not trust its exit byte: simloader.py:641-700 parses pytest's own summary line, rejects 'no tests ran', rejects a suite that shrank >10% against the last green baseline, and each of those rules is annotated with the live attack it closed (deleted tests, conftest exit-status override, blanket skip marker). This is a correct A/B-image design for a self-editing program.
- The root conftest.py (lines 30-71) isolates the whole session from the operator's environment and model keys and forces the offline floor provider; the docstring records the incident (84 fake memories written into the live ledger by tests) that motivated it. Deterministic, unbilled unit runs are a precondition for everything else and they got it right.
- Architecture-level tests exist and are mechanical: tests/simorgh/test_module_boundaries.py enforces the blueprint's import rules by AST and self-tests the checker against a temp tree; tests/simorgh/test_every_subsystem_reads_its_config.py asserts a toml value arrives in the service rather than that a config attribute exists; tests/simorgh/integration/test_kernel_boots_all_sixteen_subsystems.py boots all 17 real services through the real registry.
- tests/simorgh/integration/test_cli_end_to_end.py (17 cases) starts where a human starts (a typed line through the real booted Interface) and asserts on what Planning and Orchestration did with it; its docstring names the three seam bugs unit tests structurally cannot see. 33 of the 42 integration files boot a real Kernel; 103 of the last 130 commits touch code and tests together.
- tools/trial_suite.py judges the system, not the model: a task ending blocked/failed, a dirty tree, an unparseable file, a tool fault in the _OUR_FAULT list; commits are counted with `git rev-list --count` after a substring judge was fooled (trial_suite.py:171-186); a safety block is accepted only when the ledger's own verify.result shows `full_suite_ran` fired (trial_suite.py:255-285). The trial suite is the one instrument that found the 2026-09-07 blockers, and the project documents that honestly (simloader.py:26-29).
- The mechanical checks that do run are each born from one live incident and scoped narrowly with the cost stated: did_anything (checks/didanything.py:1-30), trailing_narration (checks/trailing_narration.py:1-20), full_suite_ran with baseline attribution so a pre-existing red suite is not blamed on the change (checks/fullsuiteran.py:31-60).
- Trace volume is controlled by excluding whole message types and by 2-day retention rather than fractional sampling, with the reasoning written down (bus/config.py:39-58); retention demonstrably works today (oldest trace stream Sep 16 13:57, newest Sep 18 17:14, 0 streams older than 2 days).
- The observer kit (tools/observer_kit.py) solves real measured costs -- copy-on-write repo clones, collision-free workspaces, JSONL findings clustered by tools/aggregate_findings.py -- and docs/observer-testing.md states plainly what did and did not get faster. For a one-person project whose workforce is parallel AI agents, this is proportionate infrastructure.

### findings

##### 1. The only check that catches real blockers is optional and is being skipped

- **kind:** right-design-undermined
- **severity:** high
- **claim:** The loader's own docstring says a known-good tag is earned by 'the unit suite plus the scored trial suite', but run_gate only runs trials under --full, and the decision log shows the creator blessing four commits unit-only right after a full bless was refused for trial failures.
- **evidence:**
  - simloader.py:26-29: 'The gate that earns one is the unit suite plus the scored trial suite -- because this week 2,600 passing tests sat on top of a system that could not write a file, and the trial suite is the check that would have caught it.'
  - simloader.py:609-611: `if not full: return True, f"unit suite green ({unit_why})"` -- trials never run on `run`, only on `bless --full`.
  - .simorgh_loader/decisions.jsonl tail: `{"ts": 1789765232, "kind": "bless_refused", "commit": "e317076", "why": "trial suite had failures"}` followed 187s later by `{"ts": 1789765419, "kind": "blessed", "commit": "e317076", "tag": "sim-good-0020", "why": "unit suite green (3348 tests ran, none failed)"}`; sim-good-0021, 0022, 0023 all 'unit suite green'.
  - .simorgh_loader/last_green.json: `{"commit": "93764b7...", "full": false, "all_tests": false}`.
  - .simorgh_loader/last_trials.txt: `3/7 clean`; FAIL edit-an-existing-file (blocked), research-a-question (blocked), already-done, continues-across-attempts; trial wall times 299+181+236+45+374+327+71 = 1533s; Together 503s mid-run ('cognition.provider_failed provider=together ... Service unavailable').
- **why it matters:** The bootloader's promise is that a sim-good tag means independently verified; today it means 'the unit suite that has never caught a real blocker was green'. Sim's self-patches and the creator's own edits both roll forward on that tag. The trial suite is 25 minutes, costs money and fails on third-party outages, so the human rationally skips it, and the design silently degrades to exactly the gate the docstring says is insufficient.
- **recommendation:** Make a cheap trial subset part of `bless` by default: two trials (create-a-file and breaks-the-suite, ~6 min) with autonomy off and a `--unit-only` flag that must be typed to skip them. Record the trial verdict (n/7 clean) in the tag's decision note and refuse to tag when it is worse than the previous tag's. Treat a provider 503 as 'not judged' rather than FAIL so an outage cannot block a bless, and cache the last trial verdict per source hash the way gate_reused already caches the unit result.
- **confidence:** 0.95

##### 2. Five of eleven mechanical checks can never run on the real path, and the rigor table is inert

- **kind:** right-design-undermined
- **severity:** high
- **claim:** Orchestration's verify subject never carries candidate/code/original and always sends wire kind 'task', so denylist_immunity, docstring, invariants, isolated_suite and sandbox_smoke are dead for every human or trial task, and select_rigor resolves every task to STANDARD regardless of the configured patch=FULL / research=LIGHT / skill=FULL table.
- **evidence:**
  - simorgh/orchestration/session.py:1885-1890 subject keys: `"description", "result", "kind", "steps", "complete_log", "subject", "written_paths", "base_ref", "repo_root"`; grep for '"candidate"|"code":|"original"|"path":' in session.py returns only an unrelated git_discard arg at line 864.
  - simorgh/orchestration/session.py:1741: `"kind": "task", "subject_ref": subject_ref` -- session.kind (patch/skill/research) is not the wire kind.
  - checks/invariants.py:28-31, checks/docstring.py:45-48, checks/denylist_immunity.py:21-22, checks/isolated_suite.py:18-19 all require `req.subject.get("candidate") or req.subject.get("code")`; checks/sandbox_smoke.py:28 `return req.kind == "skill"`.
  - verification/rigor.py:22-25 with config.py:14-26: `rigor_by_kind.get("task", Rigor.STANDARD)` -- 'task' is not in the table; service.py:162 `reversibility=subject.get("reversibility", "reversible")` -- never sent, so STANDARD both ways; service.py:172-174 FULL only adds isolated_suite, which cannot apply.
  - Live ledger probe over 349 verify streams: only ('did_anything','full_suite_ran','js_syntax','render','syntax','trailing_narration') ever appear as mechanical results; verdicts `fail 220 / pass 109 / insufficient_evidence 21`.
  - checks/fullsuiteran.py:5-13 already documents that IsolatedSuiteCheck never fires for this reason; the four siblings with the same applies() condition were not noticed.
- **why it matters:** This is the verification-side consequence of the already-known dead Learning pipeline, and it is materially larger than 'one tool is not registered': the subsystem's design (11 checks, cheapest-first, reversibility-weighted rigor) is what the docs and the tests describe, but the running system is 6 checks at one rigor. Research tasks pay a model call for a checklist they were configured to skip; skills never get the sandbox smoke; and tests/simorgh/verification/test_invariants.py and test_docstring.py assert the shape of code the system never executes -- the exact failure mode the project's own notes describe.
- **recommendation:** Pick one of two honest states. Either (a) make the checks reachable: have _put_verify_subject send session.kind as the wire kind and, for each written path, read the worktree file into subject['candidates'][path] (the worktree is already at session.worktree), and rewrite the four content checks to iterate written paths; or (b) delete the five dead checks, the rigor table and their tests, leaving the six that run. Add one integration assertion that every check in ALL_CHECKS has fired at least once against the subject shape orchestration actually sends.
- **confidence:** 0.92

##### 3. full_suite_ran fails 90% of the time because 'the whole suite' is the wrong oracle inside a task

- **kind:** right-design-undermined
- **severity:** high
- **claim:** The load-bearing gate for self-patching demands a run of `tests` (all 6,000 tests, ~2 minutes, including v1 and feature suites that are environment-sensitive) inside every patch task, and it fails 56 of the 62 times it has run in the live ledger.
- **evidence:**
  - Live ledger probe: `('full_suite_ran', 'failed') 56`, `('full_suite_ran', 'passed') 6`.
  - .simorgh_loader/last_trials.txt line 8: `run_tests([ran target='tests'] [failed 4: tests/simorgh/execution/media/test_cast.py:...  ✗ 1.8m` inside the create-a-file trial; the same file on the host: `python3 -m pytest -q tests/simorgh/execution/media/test_cast.py` -> `32 passed, 2 warnings in 32.41s`, i.e. the lab's suite was red for reasons unrelated to the change.
  - last_trials.txt lines 150-158: `verification fail: mechanical check failed -- run_tests was called on a narrower target` three times, then `blocked in 70s -- verification failed after max revisions`.
  - checks/fullsuiteran.py:31-60 describes the 'objection that could not be answered' and adds baseline attribution, which still needs a second full run to answer it.
  - simloader.py:530-554 already defines the curated 45-second CORE selection with `-m "not live"`; the in-task check does not use it.
- **why it matters:** Verification's job is to give a patch a fast, attributable yes/no. A two-minute oracle that is red on this machine for unrelated reasons, running inside a step budget, converts the check into a revision loop that ends in 'blocked' -- the last_trials output shows exactly that. The creator then sees tasks blocked and blesses without trials (finding 1). The check is right; the suite it points at is the loader's `--all-tests` set, not the loader's gate.
- **recommendation:** Define the suite once: expose simloader.gate_selection() (or a tests/core.txt it reads) and have run_tests' 'whole suite' mean that CORE selection, so the in-task oracle is the same 45-second set the loader blesses on. Persist the last green gate's failure set per machine and have _baseline consult it before re-running anything. Mark the feature suites (media, home, voice engines) `live` or keep them out of CORE so they cannot make the oracle red.
- **confidence:** 0.9

##### 4. Tracing produces 46k one-event streams a day and no end-to-end trace for a chat or voice turn

- **kind:** bug
- **severity:** medium
- **claim:** The per-root-message trace design with a hand-maintained exclusion list yields mostly single-event streams from topics that were never excluded, while the daily path (a typed or spoken turn) leaves only a two-event think/reply island, so `simorgh trace <id>` cannot reconstruct a bad turn.
- **evidence:**
  - Measured on ~/.simorgh/ledger/streams: `streams total: 118215  trace: 88356  non-trace: 29859`, `trace in last 24h: 46264`; 400-file sample: 228 streams with 1 line, 54 with 2, 16 with 3, 2 with 14.
  - One-event roots by type (400 sample): world.camera.event 52, ui.notice 51, ui.hook.received 44, persona.state.changed 42, voice.listening 31, tool.registered 21, voice.transcript 18 -- none of these are in the exclusion list at bus/config.py:60-64 (`system.tick.*`, `system.metrics`, `system.health`, `cognition.provider.status`, `_inbox.#`).
  - 3000-file sample: traces containing cognition.think by length `[(2, 69), (12, 1), (14, 4), (27, 1), (271, 1)]`; traces rooted at voice.transcript `[(1, 130)]` -- every voice turn is an orphan.
  - session.py:1291 `trace_id=session.task_id` on the think request; the inbound line/transcript and the outbound reply (private inbox, `_inbox.#` sampled to 0.0) never share it.
  - kernel/cli.py:37 and 242-256 implement `simorgh trace <id>`; grep 'trace' in interface/tui.py returns only traceback-formatting lines (390-400), so no turn ever shows a human its trace id.
  - kernel/metrics.py:17-27 notes that mining trace streams is already 'a dead end in practice' and adds a separate metrics:history stream.
- **why it matters:** The blueprint's tracing exists to answer 'what happened on that turn'; on this system it answers it only for task sessions, which are the minority path, while costing ~46k files a day of write and retention work on a JSONL ledger that is already 1.4 GB. For a one-laptop, one-family system the interesting unit is the turn, not the message.
- **recommendation:** Invert the policy: trace only messages that carry a partition_key or task_id (an allow-list of causal topics), which removes the periodic roots without maintaining a denylist. Assign one turn id at the Interface line / voice transcript, pass it as trace_id through session, think, verify and voice.speak, and add a TUI `trace` (or `last`) command that prints the last turn's id and its chain. Measure the file count a day later.
- **confidence:** 0.9

##### 5. 11.5k lines of tests and a verification invariant guard the dead v1 tree

- **kind:** over-engineering
- **severity:** medium
- **claim:** The 41 top-level tests/test_*.py files (887 tests) import only src/, which nothing under simorgh/ imports, yet they remain in `--all-tests`, in the 'all' baseline, and one Verification invariant still protects src/main.py.
- **evidence:**
  - `grep -l 'from src' tests/test_*.py | wc -l` -> 39; `grep -l 'simorgh' tests/test_*.py | wc -l` -> 0; `grep -rl 'from src' simorgh/ simloader.py sim.sh` -> nothing.
  - src/: 16,441 lines; last commit touching src/ 2026-09-09, tests/test_*.py 2026-09-06.
  - simloader.py:551-552 `if all_tests or not paths: return ["tests"]`; .simorgh_loader/unit_baseline.json `{"tests": 5969}` vs core 3348.
  - simorgh/verification/config.py:28-31 `_DEFAULT_INVARIANTS = {"src/main.py": ["AuditGate(", ...], ...}`; simorgh/execution/ invariant `verifier.verify(` matches exactly 1 file of the package (grep -rl -> 1), so the prefix rule would fail any other execution/ file if it ever applied.
  - tests/test_e2e_cli.py:1-9 is the only process-boundary e2e in the repo and it spawns `python -m src.main`.
- **why it matters:** A quarter of the suite by test count and 13% by lines is maintenance weight that verifies nothing the running system does, inflates the 'suite larger than the code' number, and keeps `--all-tests` at ~20 minutes. The only genuine process-level e2e pattern in the repo lives in that dead tree instead of being ported.
- **recommendation:** Move src/ and tests/test_*.py to an archive branch or delete them (git keeps them), drop the src/main.py invariant, and port test_e2e_cli.py's pattern to v2 as a single CORE test that spawns `python -m simorgh --self-check` with a 60s timeout and asserts exit 0.
- **confidence:** 0.93

##### 6. No regression benchmark for the daily path (chat + voice)

- **kind:** missing
- **severity:** medium
- **claim:** Nothing measures turn latency, prompt size or trace-writer drops over time for the path the family actually uses; the benchmark unit measures model capability on public suites, not the system's own regressions.
- **evidence:**
  - `grep -rli 'latency|p95|p50|regression' tools simorgh/benchmark tests/simorgh/benchmark` -> tools/bench_recall.py (memory retrieve scaling), simorgh/benchmark/swebench.py, one benchmark test.
  - simorgh/voice/bench.py:12,89 measures one STT sample's latency_s; no writer stores it and `grep -rln 'voice/bench|voice bench' docs/findings docs/*.md` finds only EVOLUTION.md.
  - kernel/metrics.py:20-27: `MetricsHistoryWriter` snapshots per-subsystem gauges to metrics:history, but no test or tool reads that stream for a threshold or a delta.
  - memory note project_test_suite_speed.md records that the gate went 8m20s -> under a minute only after profiling by hand; nothing prevents the same drift returning.
  - tests/simorgh/voice: 45 files, the only time-shaped one is test_a_slow_engine_is_waited_for.py (a behaviour, not a budget).
- **why it matters:** The project's own history (STT degrading under self-inflicted load, provider silent failover, 8-minute gates) is a history of latency regressions discovered by the human noticing. With the offline floor provider already wired into conftest, a deterministic timing run is cheap and would have shown each of those as a number before a person felt it.
- **recommendation:** Add tools/daily_bench.py: boot a Kernel with the floor provider and a temp data_dir, push 20 scripted lines through Interface._handle_line and 5 fake voice transcripts, record per-turn wall time, assembled prompt bytes, bus queue depth and TraceWriter.failed/dropped, append one JSON line to results/daily_bench.jsonl, and have `bless` print the delta against the last blessed line (warn at +25%). No model call, under a minute.
- **confidence:** 0.85

##### 7. The suite is in-process and uses real time; the two incidents that bricked the system were process-level

- **kind:** right-design-undermined
- **severity:** low
- **claim:** 5,515 tests run entirely inside pytest's process with 153 real asyncio.sleep(>0) waits and no timeout plugin configured, while the incidents the project remembers (a non-compiling simloader, Ctrl-C ignored by a busy tool thread) live at the process boundary no v2 test crosses.
- **evidence:**
  - `grep -rhE 'asyncio.sleep\(0?\.[0-9]+|asyncio.sleep\([1-9]' tests/simorgh | wc -l` -> 153; `time.sleep(` -> 8; tests/simorgh/execution/media/test_cast.py with a fake backend: `32 passed in 32.41s` (measured).
  - `grep -rn '"-m", "simorgh"' tests/simorgh` -> nothing; sim.sh:35-52 exists because 'a syntax error in simloader.py bricked the system completely'.
  - No pytest.ini/pyproject/setup.cfg; `pip list` shows pytest-xdist 3.8.0 and pytest-asyncio 0.26.0 but no pytest-timeout; conftest.py registers only the `live` marker.
  - memory project_test_suite_speed.md: FakeClock.sleep busy-spins the scheduler in booted-Kernel tests (test_flow_5_pause_resume_stop ~17s), still open.
- **why it matters:** Real sleeps make the gate's 45 seconds drift upward silently and make xdist results order-sensitive; the absence of any subprocess test means the one file whose failure has no rollback (simloader.py) and the shutdown path are verified only by sim.sh's runtime guard.
- **recommendation:** Add pytest.ini with `timeout = 120` (install pytest-timeout) and `-p no:cacheprovider`, replace the FakeClock spin with a scheduler that awaits a clock event, and add one CORE subprocess test that runs `python simloader.py status` and `python -m simorgh --self-check` and asserts exit 0 within 60s.
- **confidence:** 0.8

##### 8. Knowledge about what works is spread across four records

- **kind:** over-engineering
- **severity:** low
- **claim:** docs/findings (5 dated files), docs/EVOLUTION.md (5,254 lines of history the notes say is stale), ~40 memory notes, and observer findings JSONL under ~/.cache all record measured results, so the next session has to reconcile them rather than read one.
- **evidence:**
  - `ls docs/findings | wc -l` -> 6 (5 findings + README), earliest 2026-09-15; docs/findings/README.md:3 'Each file is self-contained and cites its commits.'
  - tools/observer_kit.py:60-79: FINDINGS_ROOT = ~/.cache/simorgh-observer-findings, outside the repo; tools/aggregate_findings.py clusters them but writes nowhere in docs/.
  - Task brief for this review: 'docs/EVOLUTION.md (5,254 lines) is a HISTORY; a bug it describes has very likely been fixed since.'
- **why it matters:** The findings process is the right idea (dated, measured, cited) and it is only three days old; the risk is that it becomes a fifth place rather than the place, and that observer output evaporates in a cache directory.
- **recommendation:** Have aggregate_findings.py emit a docs/findings/<date>-observer-wave.md skeleton (clusters, files, lines) that the coordinator edits; freeze EVOLUTION.md with a header pointing at docs/findings; keep memory notes as pointers into findings rather than as parallel records.
- **confidence:** 0.75


### measurements

- find tests -name 'test_*.py' | wc -l -> 447; all tests/*.py lines -> 90,203; all simorgh/*.py lines -> 86,996; src/*.py lines -> 16,441
- tests/simorgh: 5,515 test functions (2,553 async); tests/test_*.py: 887 test functions in 11,574 lines, 39 of 41 files import from src, 0 import simorgh
- Files using unittest.mock/MagicMock/monkeypatch: 90 of 405; mock.patch/patch.object sites: 298; 'class Fake*': 18 in 8 files; FakeClock used in 88 files
- Files constructing a real Kernel: 43 (integration 33, kernel 3, benchmark 2, voice 2, bus 1, guardian 1, interface 1); files calling build_factories: 29; files calling .boot(): 41
- pytest.mark.live: 6 files, all under tests/simorgh/execution; real asyncio.sleep(>0) in tests: 153; time.sleep: 8
- .simorgh_loader/unit_baseline-core.json: {"tests": 3348, "seconds": 45.67}; unit_baseline.json (all): {"tests": 5969}; last_unit.txt tail: '3348 passed, 16 warnings in 45.08s'
- git tag -l 'sim-good-*' | wc -l -> 23; decisions.jsonl: last five blesses all 'unit suite green'; one 'bless_refused ... trial suite had failures' at ts 1789765232 followed by 'blessed sim-good-0020' at 1789765419; last_green.json full=false
- last_trials.txt: '3/7 clean'; per-trial seconds 299, 181, 236, 45, 374, 327, 71 (sum 1533s); in-task 'run_tests([ran target=\'tests\'] [failed 4: tests/simorgh/execution/media/test_cast.py' took 1.8m; on the host `pytest tests/simorgh/execution/media/test_cast.py` -> '32 passed, 2 warnings in 32.41s'
- Live ledger ~/.simorgh/ledger: 1.4G total (streams 696M, idem 355M, blobs 325M, index.json 12M); streams total 118,215 of which trace 88,356 (46,264 in the last 24h); oldest trace Sep 16 13:57:30, newest Sep 18 17:14:18; 0 trace streams older than 2 days
- Trace sample (400 files): 228 have 1 event, 54 have 2, 16 have 3, 2 have 14; one-event roots: world.camera.event 52, ui.notice 51, ui.hook.received 44, persona.state.changed 42, voice.listening 31, tool.registered 21, voice.transcript 18, tool.invoked 17
- Trace sample (3000 files): traces containing cognition.think by length [(2, 69), (12, 1), (14, 4), (27, 1), (271, 1)]; traces rooted at voice.transcript by length [(1, 130)]
- Live verify streams (349 sampled, 350 verdict events): fail 220 / pass 109 / insufficient_evidence 21; mechanical results seen: did_anything passed 110 failed 12; full_suite_ran passed 6 failed 56; syntax passed 50 skipped 33; trailing_narration passed 57 skipped 33; js_syntax passed 6 skipped 1; render passed 6 failed 1; never seen: denylist_immunity, docstring, invariants, isolated_suite, sandbox_smoke
- git log -150 --name-only: commits touching tests only 3, simorgh code only 24, both 103
- pip list: pytest 8.3.5, pytest-xdist 3.8.0, pytest-asyncio 0.26.0, pytest-mock 3.15.1; no pytest-timeout; no pytest.ini/pyproject.toml/setup.cfg/tox.ini/.github in the repo
- docs/findings: 5 dated files (2026-09-15 to 2026-09-17) plus README; tools/: trial.py, trial_suite.py, observer_kit.py, observer_wave.py, aggregate_findings.py, bench_instance.py, bench_recall.py, denoise_bench.py, scan_half_wired.py, voice_live_trial.py

