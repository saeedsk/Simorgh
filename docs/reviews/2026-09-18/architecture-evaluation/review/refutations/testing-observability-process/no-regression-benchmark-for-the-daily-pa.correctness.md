# refute:correctness:No regression benchmark for the daily pa

*Workflow: review · Phase: Refute · Agent id: `af5bb8c1090740b2e` · Tool calls: 6*

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
| 1 | Bash | Check latency-related files and voice bench source | tools/bench_recall.py simorgh/benchmark/swebench.py tests/simorgh/benchmark/test_a_failure_stays_in_the_denominator.py ---voice bench """`voice bench`: the numb |
| 2 | Bash | Check metrics writer readers, voice tests, tools, and bless path | ---metrics.py """Aggregates `system.metrics`/`system.health` into in-memory tables (justified caches -- section 4: derivable from the `system` stream on replay, |
| 3 | Bash | Check metrics history readers, baseline check, trial timing, bless, turn latency gauges | ---readers of metrics:history simorgh/interface/config.py:121: history_stream: str = "metrics:history" simorgh/interface/httpapi.py:144: history_stream: str = " |
| 4 | Bash | Check history endpoint, floor provider, voice gauges, timing asserts, trial suite comparisons | ---httpapi history class HttpApi: def __init__( self, bus, *, ledger=None, host: str = "127.0.0.1", port: int = 8765, clock=None, status_timeout_s: float = 3.0, |
| 5 | Bash | Check floor provider wiring, timing asserts, voice and orchestration gauges | ---floor in tests tests/simorgh/integration/test_cli_end_to_end.py:20:Cognition is real here and will answer from its floor provider (no API simorgh/cognition/p |
| 6 | Bash | Check where per-turn voice metrics go and orchestration gauges | ---voice turn metrics sink and self.last_identification.name else "") self.stats.last_metrics = metrics engine = getattr(self._tts, "last_engine", "") or self._ |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core of the finding survives: there is no tool, test or gate that records a timing/size number for the chat or voice path and compares it against a previous run or a budget. `ls tools` shows bench_recall.py (memory retrieve), denoise_bench.py, bench_instance.py (public suites), trial_suite.py (coding tasks) and no daily/chat/voice regression runner; `grep -rlniE 'daily_bench|regression' tools simorgh tests` hits only unrelated uses of the word (swebench, verification/_baseline attribution, docstrings). The bless path (simloader.py:803-846) runs the unit/trial gate and tags; it records nothing about duration or latency. Three evidence lines are overstated, however. (1) "no test or tool reads metrics:history" is false as written: simorgh/interface/httpapi.py:582 registers `/api/history` and :1186-1212 reads that stream for the dashboard, and tests/simorgh/interface/test_httpapi.py:438-446 and tests/simorgh/integration/test_dashboard_observe_tier.py:151-157 exercise it. What is true is the qualifier: nothing applies a threshold or computes a delta (`grep -n 'threshold\|warn\|delta\|regress' simorgh/interface/httpapi.py` returns nothing relevant). (2) "Nothing measures turn latency" is too strong for voice: simorgh/voice/session.py:1839-1866 computes per-turn `clock.metrics(report)` and persists it in the `voice:turns` VoiceTurn record (only when `config.diagnostics` is on) and publishes VOICE_SPOKEN with `seconds`; interface/service.py:166,946,966 also times each chat turn, but only for the "Thinking... [Ns]" narration. These are measured but never aggregated or compared, so the "over time" half of the claim holds. (3) "floor provider already wired into conftest" is inaccurate: `grep floor tests/conftest.py` finds nothing; the floor is Cognition's built-in last-resort provider (simorgh/cognition/providers/base.py:1-18) that test_cli_end_to_end.py:20 relies on implicitly. The recommendation remains feasible. Not in the known-findings list: "STT latency degrades under self-inflicted load" is a symptom, not the absence of a regression harness. Classification: (a)/(missing) — a process gap, not a bug; medium severity is appropriate for a one-laptop system whose history is latency regressions found by feel.

### evidence

- `ls tools` -> aggregate_findings.py bench_instance.py bench_recall.py denoise_bench.py observer_kit.py observer_wave.py render_logo_splash.py scan_half_wired.py trial_suite.py trial.py voice_live_trial.py voice_setup.py — no chat/voice timing runner
- `grep -rliE 'latency|p95|p50|regression' tools simorgh/benchmark tests/simorgh/benchmark` -> tools/bench_recall.py, simorgh/benchmark/swebench.py, tests/simorgh/benchmark/test_a_failure_stays_in_the_denominator.py (matches the finding)
- simloader.py:803-846 `cmd_bless`: runs `run_gate`, tags, writes a note with kind/commit/tag/why; no duration or latency recorded or compared
- simorgh/interface/httpapi.py:582 `self.register_route("GET", "/api/history", ...)` and :1186-1212 `_history_json` reads `metrics:history` — so the stream IS read (for display); `grep -n 'threshold\|warn\|delta\|regress' simorgh/interface/httpapi.py` finds no comparison logic
- tests/simorgh/interface/test_httpapi.py:438-446 and tests/simorgh/integration/test_dashboard_observe_tier.py:151-157 read metrics:history but assert presence/shape only
- simorgh/voice/session.py:1839 `metrics = clock.metrics(report)`; :1861-1866 VoiceTurn(... metrics=metrics if self._config.diagnostics else {}) — per-turn voice timings exist but are persisted only under diagnostics and never aggregated
- simorgh/interface/service.py:166 `self._turn_started: dict[str, float] = {}  # session_id -> monotonic start, for narration timing`; :946,966 elapsed used only for the 'Thinking... [Ns]' line
- simorgh/orchestration/service.py:312-316 gauges are workers.total/workers.busy/workers — no prompt-size or latency gauge
- tools/trial_suite.py:136,241,406 records `seconds` per trial into results but never compares to a prior run; and it drives coding tasks, not chat/voice
- `grep -rn floor tests/conftest.py` -> nothing; simorgh/cognition/providers/base.py:1 'The guaranteed floor (principle 4.5): a stdlib, offline provider'; tests/simorgh/integration/test_cli_end_to_end.py:20 'Cognition is real here and will answer from its floor provider'
- simorgh/voice/bench.py:1-13 and :89 `latency_s` — one-shot manual `voice bench`; `grep -rln 'voice/bench|voice bench' docs` -> docs/EVOLUTION.md only
- tests/simorgh/voice: 48 files; timing asserts (`grep -rln assertLess.*elapsed`) exist only in test_barge_in.py:111 as a behavioural bound, not a budget

**severity adjustment:** keep

**corrected claim:** No tool, test or gate records a timing or prompt-size number for the chat/voice path and compares it against a previous run or a budget. Per-turn timings do exist (voice/session.py:1839-1866 under `diagnostics`, interface/service.py:946-968 for narration) and `metrics:history` is read by the dashboard's `/api/history` (httpapi.py:582,1186), but nothing aggregates, thresholds or diffs any of them; the benchmark unit and trial_suite measure model capability and coding tasks, not the family's daily path. The offline floor provider makes a no-model timing run feasible (it is Cognition's built-in fallback, not a conftest fixture).

