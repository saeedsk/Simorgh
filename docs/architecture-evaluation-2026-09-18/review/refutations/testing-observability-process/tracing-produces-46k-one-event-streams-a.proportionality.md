# refute:proportionality:Tracing produces 46k one-event streams a

*Workflow: review · Phase: Refute · Agent id: `a528eb54ac14179de` · Tool calls: 14*

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
    "title": "Tracing produces 46k one-event streams a day and no end-to-end trace for a chat or voice turn",
    "kind": "bug",
    "severity": "medium",
    "claim": "The per-root-message trace design with a hand-maintained exclusion list yields mostly single-event streams from topics that were never excluded, while the daily path (a typed or spoken turn) leaves only a two-event think/reply island, so `simorgh trace <id>` cannot reconstruct a bad turn.",
    "evidence": [
      "Measured on ~/.simorgh/ledger/streams: `streams total: 118215  trace: 88356  non-trace: 29859`, `trace in last 24h: 46264`; 400-file sample: 228 streams with 1 line, 54 with 2, 16 with 3, 2 with 14.",
      "One-event roots by type (400 sample): world.camera.event 52, ui.notice 51, ui.hook.received 44, persona.state.changed 42, voice.listening 31, tool.registered 21, voice.transcript 18 -- none of these are in the exclusion list at bus/config.py:60-64 (`system.tick.*`, `system.metrics`, `system.health`, `cognition.provider.status`, `_inbox.#`).",
      "3000-file sample: traces containing cognition.think by length `[(2, 69), (12, 1), (14, 4), (27, 1), (271, 1)]`; traces rooted at voice.transcript `[(1, 130)]` -- every voice turn is an orphan.",
      "session.py:1291 `trace_id=session.task_id` on the think request; the inbound line/transcript and the outbound reply (private inbox, `_inbox.#` sampled to 0.0) never share it.",
      "kernel/cli.py:37 and 242-256 implement `simorgh trace <id>`; grep 'trace' in interface/tui.py returns only traceback-formatting lines (390-400), so no turn ever shows a human its trace id.",
      "kernel/metrics.py:17-27 notes that mining trace streams is already 'a dead end in practice' and adds a separate metrics:history stream."
    ],
    "why_it_matters": "The blueprint's tracing exists to answer 'what happened on that turn'; on this system it answers it only for task sessions, which are the minority path, while costing ~46k files a day of write and retention work on a JSONL ledger that is already 1.4 GB. For a one-laptop, one-family system the interesting unit is the turn, not the message.",
    "recommendation": "Invert the policy: trace only messages that carry a partition_key or task_id (an allow-list of causal topics), which removes the periodic roots without maintaining a denylist. Assign one turn id at the Interface line / voice transcript, pass it as trace_id through session, think, verify and voice.speak, and add a TUI `trace` (or `last`) command that prints the last turn's id and its chain. Measure the file count a day later.",
    "confidence": 0.9
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read cited tracing config, CLI, TUI, metrics lines |  # section 5 "Tracing"). The zeroed entries are all heartbeats and # periodic broadcasts: they root a trace of their own but cause # nothing, so each one wrote  |
| 2 | Bash | Check trace_id wiring in session/interface and ledger stream counts |  `[voice] unplaced_needs_name = false`.""" if not self._config.unplaced_needs_name or speaker: return False if self._in_conversation(speaker): return False if s |
| 3 | Bash | Inspect how the bus assigns trace ids and writes trace streams |  # whose assembled memory-retrieval block happens to be # large (large migrated records, a broad query) could # exceed budget even after layers 1-4 -- `allow_su |
| 4 | Bash | Read trace writer and message trace_id defaults | """The trace writer: every message -> Ledger stream `trace:<trace_id>`, sampled per type (docs/blueprint/subsystems/01-bus.md section 5.6; 03 section 5 "Tracing |
| 5 | Bash | Measure trace stream counts, lengths and one-event root types in the ledger | Command did not complete within its 120s timeout and was moved to the background (ID: bvpzj1wk4). Output is being written to: /private/tmp/claude-501/-Users-sae |
| 6 | Bash | Sample 2000 trace streams and tally lengths and root types | trace streams: 88356 mtime<24h: 43046 len dist: [(1, 1550), (2, 350), (3, 89), (12, 2), (14, 7), (15, 1), (24, 1)] one-event roots: [('ui.notice', 276), ('world |
| 7 | Bash | Show think-trace contents and how voice session publishes transcripts | trace%3A9b6e0dfd-40d4-447a-819b-5386a37f1806.jsonl 9b6e0dfd-40d4-447a-819b-5386a37f1806 cognition.think None None trace%3A9bab0496-20bc-4b15-88b3-ebcc3be0eec5.j |
| 8 | Bash | Trace how a voice transcript and a chat line flow to think and speak, and where trace ids surface | (eval):1: no matches found: --include=*.py ---- (eval):1: no matches found: --include=*.py ---- simorgh/orchestration/api.py:110: messages: list[dict] = field(d |
| 9 | Bash | Read voice turn record, transcript publish, and how bus assigns trace_id on publish | simorgh/contracts/topics.py:279:VOICE_TRANSCRIPT = "voice.transcript" # what was heard, before Sim answers simorgh/voice/pipeline.py:8:`voice.transcript`, `voic |
| 10 | Bash | Check ask/publish trace ids, chat path id sharing, and trace retention config |  return None, "" if self._config.keep_audio: self._keep(audio) heard_at = self._clock.now() utterance = await self._stt.transcribe(audio, language=self._config. |
| 11 | Bash | Check id derivation in orchestration, typed-line trace ids, trace disk footprint, compaction wiring, and id exposure in TUI | ---- handler simorgh/orchestration/service.py:36: topics.PERCEPT_TEXT_RECEIVED, topics.TOOL_REGISTERED, simorgh/orchestration/service.py:98: self._percept_sub = |
| 12 | Bash | Read percept handler id derivation, CLI publish path, and idem share of traces |  async def _on_percept(self, message) -> None: text = message.payload.get("text", "") if not text or not self._workers: return session_id = message.payload.get( |
| 13 | Bash | Check CLI percept publish ids, bus.new trace_id default, and trace idem file sizes | 26: outcome = await dispatch(command, bus=self._ctx.bus, clock=self._ctx.clock, 27: session_id=self.session_id, vitals=self.vitals, ledger=self._ctx.ledger) sim |
| 14 | Bash | Read the CLI percept publish call |  self._pending_turns[session_id] = fut self._turn_started[session_id] = time.monotonic() # A chat turn's task is its session id and no `task.created` # ever ann |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The core mechanism and the numbers reproduce. bus/trace.py:99-101 writes every non-excluded message to `trace:<trace_id>`; contracts/envelope.py:98 assigns a fresh uuid4 trace_id to any message created without one; bus/client.py:145 defaults trace_id=None. The daily paths create messages that way: interface/service.py:953 publishes `percept.text.received` with `bus.new(...)` and no trace_id, voice/pipeline.py:305-309 and :565-566 publish `voice.transcript`/`voice.spoken`/`percept.text.received` via `_publish` -> `bus.new` with no trace_id, and orchestration/service.py:267 takes `session_id` from the payload (not the message's trace_id) as the chat task id, which then becomes the think request's trace_id at orchestration/session.py:1291. So the inbound percept, the think/reply pair, and the outbound reply each live in different trace streams; my own 4000-stream sample found 73 traces that are exactly (cognition.think, cognition.think.reply) and 79/79 voice.transcript-rooted traces with one event. Ledger counts reproduced: 88356 trace streams, 43046 modified in the last 24h, 2000-sample length distribution 1550/350/89 for 1/2/3 lines, one-event roots led by ui.notice, world.camera.event, persona.state.changed, ui.hook.received, voice.listening, tool.registered -- none in the denylist at bus/config.py:60-64. `simorgh trace` exists only in kernel/cli.py:37,242; interface/tui.py mentions 'trace' only for tracebacks (390-400) and no TUI code exposes a session/trace id.

Two overstatements. (1) Cost: trace streams are ~1 KB each: 20000 trace streams = 21 MB and 20000 trace idem files = 20 MB, so all 88k traces are ~180 MB of the 1.4 GB, and retention is already bounded to 2 days (ledger/compaction.py:36 `"trace:": "2d"`, run from ledger/service.py:65). The 1.4 GB is mostly other streams (696 MB total), idem (355 MB) and blobs (325 MB). The real cost is inode churn (~86k files/day created and deleted, since each trace is a stream file plus an idem file), not gigabytes. (2) 'cannot reconstruct a bad turn' is too strong for voice: voice/pipeline.py:571-583 writes a `voice:turns` record per turn with heard/said/metrics/engines keyed by session_id, and `trace:<session_id>` holds the think pair, so the pieces exist; what is missing is one id joining percept -> think -> reply -> speak, and any UI that tells the human the id.

Scale lens: this is category (b), a right design (causal trace per root) undermined by implementation defaults (fresh uuid on every root, denylist), and it is proportionate to fix: pass `trace_id=session_id` at interface/service.py:953 and voice/pipeline.py:329/339/565 (a handful of lines), and the allow-list inversion is a config change. The 46k/day churn is tolerable on one laptop, but the missing turn-level trace directly hurts the creator's main debugging method (watching real turns), so medium severity is right.

### evidence

- bus/trace.py:99-101: `stream=f"trace:{message.trace_id}"` -- every traced message lands in a per-trace_id stream
- contracts/envelope.py:98: `trace_id=trace_id or str(uuid.uuid4())`; bus/client.py:145 `trace_id: str | None = None` -- any root published without a trace_id starts its own stream
- interface/service.py:953-955: `bus.new(topics.PERCEPT_TEXT_RECEIVED, {"channel": "cli", "text": text, "session_id": session_id})` -- no trace_id
- voice/pipeline.py:565-566 `_publish` -> `self._bus.new(topic, payload)`; :305-309 voice.transcript, :357-366 percept.text.received, :335-337 voice.spoken all go through it -- no trace_id
- orchestration/service.py:267: `session_id = message.payload.get("session_id") or message.id` -- chat task id taken from payload, not message.trace_id; orchestration/session.py:1291 `trace_id=session.task_id` on the think request
- bus/config.py:60-64 denylist: system.tick.second/idle/sleep, system.metrics, system.health, cognition.provider.status, _inbox.#
- ledger measured: `ls ~/.simorgh/ledger/streams | wc -l` = 118215; trace streams 88356; mtime<24h 43046; 2000-sample len dist [(1,1550),(2,350),(3,89),(12,2),(14,7),(15,1),(24,1)]
- one-event roots (2000 sample): ui.notice 276, world.camera.event 274, persona.state.changed 250, ui.hook.received 244, voice.listening 144, tool.registered 101, tool.invoked 88, voice.transcript 79
- 4000-sample: 73 traces are exactly ('cognition.think','cognition.think.reply'); voice.transcript-rooted traces by length [(1,79)]
- kernel/cli.py:37 `sub.add_parser("trace", ...)`, :242 `_cmd_trace` reads `trace:{trace_id}`; `grep -n trace simorgh/interface/tui.py` -> only lines 390-400 (traceback formatting)
- kernel/metrics.py:17-27: mining trace streams for system.metrics is 'a dead end in practice'; separate `metrics:history` stream
- Size correction: `du -ch` of 20000 trace streams = 21M, 20000 trace idem files = 20M; `du -sh`: ledger 1.4G, streams 696M, idem 355M, blobs 325M; ledger/compaction.py:36 `DEFAULT_RETENTION = {"trace:": "2d", ...}`; ledger/service.py:65 schedules compaction
- Partial mitigation for voice: voice/pipeline.py:571-583 appends a `voice:turns` event per turn with trace_id=session_id, heard, said, metrics, engines

**severity adjustment:** keep

**corrected claim:** Every root message published without an explicit trace_id (which is all of them on the chat and voice paths, plus every ui.notice, world.camera.event, persona.state.changed, ui.hook.received, voice.listening and tool.* broadcast) starts its own one-event trace stream; ~43k trace streams a day, each with a paired idem file, held for 2 days (~180 MB of the 1.4 GB ledger, so the cost is file churn, not disk). A typed or spoken turn is split across three unrelated traces (the percept root, the think/reply pair under the session id, the spoken/inbox reply), so `simorgh trace <session_id>` shows only the think pair; for voice the `voice:turns` stream still records heard/said per session, but nothing joins the chain end to end and no TUI surface ever shows a human the id.

