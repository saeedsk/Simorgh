# refute:proportionality:No regression benchmark for the daily pa

*Workflow: review · Phase: Refute · Agent id: `a583cc7ca9106231d` · Tool calls: 7*

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
    "title": "No regression benchmark for the daily path (chat + voice)",
    "kind": "missing",
    "severity": "medium",
    "claim": "Nothing measures turn latency, prompt size or trace-writer drops over time for the path the family actually uses; the benchmark unit measures model capability on public suites, not the system's own regressions.",
    "evidence": [
      "`grep -rli 'latency|p95|p50|regression' tools simorgh/benchmark tests/simorgh/benchmark` -> tools/bench_recall.py (memory retrieve scaling), simorgh/benchmark/swebench.py, one benchmark test.",
      "simorgh/voice/bench.py:12,89 measures one STT sample's latency_s; no writer stores it and `grep -rln 'voice/bench|voice bench' docs/findings docs/*.md` finds only EVOLUTION.md.",
      "kernel/metrics.py:20-27: `MetricsHistoryWriter` snapshots per-subsystem gauges to metrics:history, but no test or tool reads that stream for a threshold or a delta.",
      "memory note project_test_suite_speed.md records that the gate went 8m20s -> under a minute only after profiling by hand; nothing prevents the same drift returning.",
      "tests/simorgh/voice: 45 files, the only time-shaped one is test_a_slow_engine_is_waited_for.py (a behaviour, not a budget)."
    ],
    "why_it_matters": "The project's own history (STT degrading under self-inflicted load, provider silent failover, 8-minute gates) is a history of latency regressions discovered by the human noticing. With the offline floor provider already wired into conftest, a deterministic timing run is cheap and would have shown each of those as a number before a person felt it.",
    "recommendation": "Add tools/daily_bench.py: boot a Kernel with the floor provider and a temp data_dir, push 20 scripted lines through Interface._handle_line and 5 fake voice transcripts, record per-turn wall time, assembled prompt bytes, bus queue depth and TraceWriter.failed/dropped, append one JSON line to results/daily_bench.jsonl, and have `bless` print the delta against the last blessed line (warn at +25%). No model call, under a minute.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Check cited evidence in tools, voice bench, kernel metrics | tools/bench_recall.py simorgh/benchmark/swebench.py tests/simorgh/benchmark/test_a_failure_stays_in_the_denominator.py ---voice bench--- """`voice bench`: the n |
| 2 | Bash | Check readers of metrics history, docs refs, tools list, timing tests | --- metrics:history readers --- (eval):1: no matches found: --include=*.py --- voice bench refs in docs --- docs/EVOLUTION.md --- results dir / jsonl bench outp |
| 3 | Bash | Check history readers, floor provider, trial timing, prompt-size metrics, findings docs | --- metrics:history readers --- simorgh/interface/config.py:121: history_stream: str = "metrics:history" simorgh/interface/httpapi.py:144: history_stream: str = |
| 4 | Bash | Check history readers, floor provider, trace counters, per-turn timing gauges, bless | --- httpapi history use --- class HttpApi: def __init__( self, bus, *, ledger=None, host: str = "127.0.0.1", port: int = 8765, clock=None, status_timeout_s: flo |
| 5 | Bash | Read bus latency gauges, floor provider wiring, simloader notes, subsystem gauges | --- bus/metrics.py --- """Delivery counters and gauges, snapshotted into `system.metrics` (docs/blueprint/subsystems/01-bus.md section 3.2). Plain dicts, no loc |
| 6 | Bash | Check gate baseline comparison, metric publishers, trace counter export, e2e provider | --- simloader baseline seconds use --- With `allow_skip`, pressing `s` at the terminal abandons the gate and boots anyway -- a `run` convenience, never offered  |
| 7 | Bash | Check cognition and interface gauges, trace writer export, file sizes | --- cognition gauges --- 468: # every other subsystem's own gauges already do -- no new topic, 469: # `gauges` already permits a structured value (milestone 112 |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core gap is real: nothing measures end-to-end chat/voice turn wall time, assembled prompt size, or trace-writer drops over time, and nothing anywhere compares any stored number against a threshold or a previous run (grep for threshold|delta|regress in simorgh/kernel/metrics.py and simorgh/interface/httpapi.py returns nothing). voice/bench.py is a one-shot manual tool whose result is stored nowhere and referenced only in EVOLUTION.md. TraceWriter.dropped/failed (bus/trace.py:51,53) are incremented but never exported; bus/service.py:55 only surfaces a boolean `trace.degraded`. But the finding overstates in three places. (1) A latency measure over time does exist on the daily path: bus/metrics.py:23-37 keeps a rolling 1000-sample window and publishes `request_latency_ms_p50` in every `system.metrics` snapshot; MetricsHistoryWriter persists it to `metrics:history`, and HttpApi `/api/history` (httpapi.py:582, 1186-1203) reads that stream for the dashboard, so evidence 3 ("no test or tool reads that stream") is wrong as written; what is true is that nobody applies a threshold to it, and bus request latency is a proxy, not turn latency. (2) Evidence 4 is wrong that "nothing prevents the same drift returning": simloader.py:731 already writes gate `seconds` into unit_baseline-<scope>.json on every bless and line 567 prints "Ns last time" at every gate, so gate drift is visible each boot, just not warned on. (3) The "offline floor provider already wired into conftest" premise is inexact: there is no tests/conftest.py (only tests/simorgh/interface/conftest.py); the floor is simply last in cognition/config.py:73 provider_order, and test_cli_end_to_end.py:20 relies on it answering when no key is present, so a no-model timing run is feasible but not via a fixture. On the scale lens: for one laptop and one developer this is not over-built; the project's memory notes record three latency regressions found only by a person feeling them, and the pieces (floor provider, metrics:history, a gate baseline with seconds) already exist. The recommendation as written is somewhat disproportionate, though: a +25% wall-time warning on a laptop under variable load will false-alarm, and a new results/daily_bench.jsonl duplicates two stores that already exist. The proportionate version is smaller: compare the already-stored gate `seconds` in simloader and warn; add a per-turn wall-time gauge and TraceWriter.dropped/failed to the existing `system.metrics` payloads so `metrics:history` and `/api/history` carry them for free; treat prompt bytes and drops (deterministic) as the hard-fail signals and wall time as advisory. Kind: (b) right design (metrics stream, gate baseline) whose implementation stops one step short of closing the loop.

### evidence

- simorgh/bus/metrics.py:23-37 -- `observe_request_latency` keeps a rolling 1000-sample list and `snapshot()` publishes `gauges["request_latency_ms_p50"]` under subsystem "bus": a latency-over-time measure on the daily path does exist, contrary to the claim's 'nothing measures'
- simorgh/kernel/metrics.py:20-27 + simorgh/interface/httpapi.py:144,582,1186-1203 -- MetricsHistoryWriter writes `metrics:history`; HttpApi `/api/history` reads it (`_read_tail(self._history_stream, ...)`), so the stream IS read; `grep -rnE 'threshold|delta|regress' simorgh/interface/httpapi.py simorgh/kernel/metrics.py` -> no output: no threshold or delta anywhere
- simorgh/bus/trace.py:51,53,95,145,172 -- `self.dropped`/`self.failed` counters; `grep -rn '_trace\.dropped|writer\.dropped|writer\.failed' simorgh --include='*.py'` -> nothing; bus/service.py:55 exports only `self._client.trace.degraded` (a boolean)
- simorgh/voice/bench.py (117 lines), :89-92 -- `latency_s`/`rtf` computed into `out["transcription"]` and returned to the caller only; `grep -rln 'voice/bench|voice bench' docs/findings docs/*.md` -> docs/EVOLUTION.md only
- simloader.py:567 prints `-- {last['seconds']:.0f}s last time`; :731 `write_text(json.dumps({"tests": tests, "seconds": seconds, "ts": time.time()}))` -- gate duration IS recorded per bless into unit_baseline-{core,all}.json, it is just never compared (evidence 4 of the finding is wrong as written)
- simorgh/cognition/config.py:73 `provider_order = ("together", "claude_code_cli", "gemini", "floor")`; tests/simorgh/integration/test_cli_end_to_end.py:20 'Cognition is real here and will answer from its floor provider'; `find tests -name conftest.py` -> tests/simorgh/interface/conftest.py only (no top-level conftest wiring the floor)
- `grep -rnoE '"[a-z_.]*(turn|latency|prompt|elapsed|seconds)[a-z_.]*"\s*:' simorgh --include='*.py'` -> no per-turn timing gauge in interface/orchestration/voice/cognition services; cognition/service.py:472-473 publishes only a `providers` structured gauge
- `ls tests/simorgh/voice | wc -l` -> 48 (finding says 45); the only time-named test is test_a_slow_engine_is_waited_for.py
- `grep -rliE 'latency|p95|p50|regression' tools simorgh/benchmark tests/simorgh/benchmark` -> tools/bench_recall.py, simorgh/benchmark/swebench.py, tests/simorgh/benchmark/test_a_failure_stays_in_the_denominator.py (matches the finding)

**severity adjustment:** keep

**corrected claim:** No number on the family's daily path (chat + voice) is ever compared against a previous run or a budget. The bus already publishes a rolling `request_latency_ms_p50` into `system.metrics`, the Kernel persists it to `metrics:history`, the dashboard's `/api/history` reads it, and simloader already stores each gate's `seconds` in unit_baseline-*.json, but none of these has a threshold or delta check, no end-to-end per-turn wall time or assembled prompt size is measured anywhere, and TraceWriter.dropped/failed are counted but never exported. The proportionate fix reuses those stores (warn on the gate baseline, add turn-time/prompt-bytes/trace-drop gauges to the existing metrics payloads, and let bless compare them) rather than a new benchmark file; wall time on a laptop should be advisory, prompt bytes and drops the hard signals.

