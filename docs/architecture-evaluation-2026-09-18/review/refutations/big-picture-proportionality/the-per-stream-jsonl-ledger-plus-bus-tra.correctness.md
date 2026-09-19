# refute:correctness:The per-stream JSONL ledger plus bus tra

*Workflow: review · Phase: Refute · Agent id: `a6a3d3357332a552f` · Tool calls: 8*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
  FINDING:
  {
    "title": "The per-stream JSONL ledger plus bus tracing produces ~44k files a day for a single-process laptop",
    "kind": "wrong-design",
    "severity": "high",
    "claim": "The Ledger's default backend writes one JSONL file and one idempotency index file per stream, and the bus writes one trace stream per trace_id; the result is 118,215 stream files + 90,755 idem files (1.4 GB) of which 88,356 are traces under two days old, most rooted at broadcast events and containing one event, so the cost is paid and the trace answers nothing.",
    "evidence": [
      "du -sh ~/.simorgh/ledger -> \"1.4G\"; ls streams | wc -l -> 118215; ls idem | wc -l -> 90755 (355M); streams by prefix: \"88356 trace / 26737 action / 2431 task / 350 verify\"",
      "find streams -name 'trace*' -mtime +2 | wc -l -> 0 (retention IS running; the volume is the steady state, ~44k trace streams/day)",
      "trace root types (sample 800): \"216 ui.hook.received / 196 world.camera.event / 194 persona.state.changed / 192 ui.notice / 120 system.status.request / 102 tool.registered ...\" -- bus/config.py:60-63 zeroes only system.tick.*, metrics, health, provider.status",
      "trace depth (sample 6000): most streams 1 event; 1108 have 2, 292 have 3; 29 traces rooted at percept.text.received had exactly 1 event each (\"n=29 min=1 median=1 max=1\") -- a user's message does not root the chain that answers it",
      "simorgh/ledger/backends/jsonl.py is 815 lines; simorgh/ledger/backends/sqlite.py is 275 lines and already exists; ~/.simorgh/simorgh.toml has no [ledger] section, so ledger/config.py:18 `backend = \"jsonl\"` is in force",
      "simorgh/bus/trace.py:1-2 \"every message -> Ledger stream `trace:<trace_id>`\""
    ],
    "why_it_matters": "For one process on one disk the file-per-stream layout is the worst of both worlds: it has SQLite's write amplification without its indexes, it makes `ls` and backups slow, and it makes the append-only-Ledger principle (which is right) look expensive. Tracing that produces one-event chains is pure cost.",
    "recommendation": "Make sqlite the default ledger backend (the code exists; migrate_v1.py shows a migration is a known shape). Stop writing traces into the Ledger: either propagate trace_id through request/reply so a percept roots the whole turn (then trace only percept.*, task.*, action.*), or write traces to one rotating file outside the Ledger. Zero-sample `ui.hook.received`, `world.camera.event`, `persona.state.changed`, `ui.notice`, `tool.registered` today as a one-line config change.",
    "confidence": 0.85
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Measure ledger directory sizes and file counts | 1.4G /Users/saeed/.simorgh/ledger blobs heads idem index.json LOCK snapshots streams ---streams 118215 ---idem 90755 355M /Users/saeed/.simorgh/ledger/idem 696M |
| 2 | Bash | Count stream files by prefix and age; show a sample trace stream |  1 voice%3Aturns.jsonl 1 verify%3Afe1234ff5c0c.jsonl 1 verify%3Afd27f3be972a.jsonl 1 verify%3Afc892e053e59.jsonl 1 verify%3Afbf9066cdf23.jsonl 1 verify%3Afa2924 |
| 3 | Bash | Tally stream prefixes, trace root event types and trace depths | 88356 trace 26737 action 2431 task 350 verify 310 reflect 5 memory 5 curiosity 5 cognition 3 persona 2 guardian 2 execution 1 voice --- root types (sample 800)  |
| 4 | Bash | Read bus trace, bus config, ledger config and user toml |  815 simorgh/ledger/backends/jsonl.py 275 simorgh/ledger/backends/sqlite.py 176 simorgh/bus/trace.py 96 simorgh/bus/config.py 67 simorgh/ledger/config.py 1429 t |
| 5 | Bash | Read retention defaults, idem index code, sqlite backend surface, prior-review mentions of tracing | --- compaction retention 34-# that", which is a question asked within hours, so a week of them was 35-# never read and only ever slowed the boot that had to sta |
| 6 | Bash | Compare sqlite and jsonl backend method surfaces; check idem files for trace streams | --- jsonl.py 425-450 offsets[stored.seq] = meta.bytes self._offsets[event.stream] = (meta.bytes + len(line), offsets) else: # somebody else wrote to this file;  |
| 7 | Bash | Check trace_id propagation through envelope and chat path, and sqlite test presence | --- envelope trace_id derivation 52: trace_id: str 70: trace_id: str \| None = None, 98: trace_id=trace_id or str(uuid.uuid4()), 116: trace_id=self.trace_id, 126 |
| 8 | Bash | Check whether a chat turn's downstream messages carry the percept's trace_id | --- context.py 200-222 # mode this Worker's own `BusClient` is bound to an instance- # qualified source (`orchestration@w1`), and `ReservedTopologyPolicy` # aut |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every number and code citation in the finding reproduces on the live ledger and in the current code. ~/.simorgh/ledger is 1.4 GB: streams/ 696 MB with 118,215 files, idem/ 355 MB with 90,755 files. Stream prefixes: 88,356 trace / 26,737 action / 2,431 task / 350 verify. No trace stream is older than 2 days (find -mtime +2 -> 0; oldest trace Sep 16 13:57, newest Sep 18 17:14), so the 88k traces are a ~41-44k/day steady state under the DEFAULT_RETENTION {"trace:": "2d"} at simorgh/ledger/compaction.py:36, not a backlog. Of 3,000 sampled traces, 2,293 (76%) hold exactly one event, 555 two, 140 three. Root types in an 800 sample are dominated by broadcasts (ui.hook.received, world.camera.event, persona.state.changed, ui.notice, system.status.request, tool.registered, voice.listening) and none of those are in the zero-sample list at simorgh/bus/config.py:61-65 (which zeroes system.tick.*, system.metrics, system.health, cognition.provider.status, _inbox.#). All 29 traces rooted at percept.text.received contain exactly one event: the turn's downstream messages are minted with trace_id=session.task_id (simorgh/orchestration/worker.py:277, context.py:249-266), so a user's message never roots the chain that answers it — context.py:206-218 acknowledges this as a partial fix with ~15 call sites still minting fresh trace ids. simorgh/bus/trace.py:1-2 confirms 'every message -> Ledger stream trace:<trace_id>'. ledger/config.py:18 defaults backend="jsonl"; ~/.simorgh/simorgh.toml has no [ledger] table, so it is in force. The sqlite backend (simorgh/ledger/backends/sqlite.py, 275 lines) implements the full backend surface except sweep_unreferenced_blobs and is exercised in tests/simorgh/ledger/test_backends.py, so the recommendation to switch is feasible. One materially NEW fact the skeptic pass adds, strengthening the finding: trace events carry the message id as idempotency_key (sample stream shows "idempotency_key":"d83cf8ae..."), and JsonlBackend.append writes an idem line whenever the key is truthy (jsonl.py:432-435, 442-448), so every trace stream costs TWO files — 88,356 of the 90,755 idem files (355 MB) are trace idem indexes that can never dedupe anything useful. What is already known: 'Ledger default backend is JSONL and ~1.4 GB' appears in the known list; neither docs/architecture-audit-2026.md nor docs/architecture-review-2026-09-18.html mentions tracing at all (grep 'trace' -> no hits), so the trace-volume, one-event-chain, orphaned-percept-root and two-files-per-trace analysis is new. Minor inaccuracies in the claim: the sample-800 root-type counts are roughly double what I measure (108 ui.hook.received vs 216) though the ranking is identical, and the sample list is at config.py:61-65 and also zeroes _inbox.#. Classification stands as (a) wrong-design for scale plus (b) a right principle (append-only ledger) undermined by the file-per-stream implementation and by tracing that does not follow the causal chain it exists to reconstruct.

### evidence

- du -sh ~/.simorgh/ledger -> 1.4G; du -sh idem streams -> 355M idem, 696M streams; ls streams | wc -l -> 118215; ls idem | wc -l -> 90755
- stream prefixes: 88356 trace / 26737 action / 2431 task / 350 verify / 310 reflect; idem prefixes: 88356 trace / 2393 task -- every trace stream has a matching idem file
- find streams -name 'trace*' -mtime +2 | wc -l -> 0; oldest trace mtime Sep 16 13:57:30, newest Sep 18 17:14:18 (2026) -> ~88k traces in ~51h, ~41k/day steady state
- trace depth, sample 3000 files via wc -l: 2293 x 1 line, 555 x 2, 140 x 3, 11 x 14, 1 x 67, 1 x 4044
- root types, sample 800 (first line payload.type): ui.hook.received 108, world.camera.event 98, persona.state.changed 97, ui.notice 96, system.status.request 60, voice.listening 51, tool.registered 51, action.proposed 42, voice.transcript 39 ...
- grep -l percept.text.received over 6000 trace streams -> 29 files, all exactly 1 line
- simorgh/bus/config.py:61-65 trace_sample zeroes only system.tick.second/idle/sleep, system.metrics, system.health, cognition.provider.status, _inbox.# ; comment at :40-58 says volume is controlled 'by excluding whole types and by retention, never by thinning'
- simorgh/bus/trace.py:1-2 'every message -> Ledger stream trace:<trace_id>'
- simorgh/ledger/compaction.py:36 DEFAULT_RETENTION = {"trace:": "2d", "dead:": "30d", "activity": "90d"}
- simorgh/ledger/config.py:18 backend: str = "jsonl"; grep '^\[ledger' ~/.simorgh/simorgh.toml -> no [ledger] table
- simorgh/ledger/backends/jsonl.py:11 '<root>/idem/<escaped>.idx' per stream; :432-435 and :442-448 append an idem line whenever idempotency_key is truthy; sample trace event carries idempotency_key = message id
- wc -l: jsonl.py 815, sqlite.py 275; sqlite.py implements start/stop/head/append/find_by_idempotency/read/streams/write_snapshot/read_snapshot/delete_snapshot/truncate_below/delete_stream/put_blob/get_blob/stat/last_ts (lines 59-268); tests/simorgh/ledger/test_backends.py references SqliteBackend; simorgh/ledger/factory.py:29-32 selects it on backend == "sqlite"
- simorgh/orchestration/context.py:206-218: 'without it Message.new mints a fresh uuid4 per call and every message gets its own trace:<uuid> ledger stream ... Cognition's and Execution's internal requests still mint their own; threading a trace_id through those ~15 remaining call sites needs its own pass'
- simorgh/orchestration/worker.py:277 and :376: task messages minted with trace_id=task_id, not the percept's trace_id
- grep -n -i trace docs/architecture-audit-2026.md -> no output; grep -o -i '[^.]*trace[^.]*' docs/architecture-review-2026-09-18.html -> no output (tracing not covered by prior reviews)

**severity adjustment:** keep

**corrected claim:** The Ledger's default JSONL backend writes one stream file per stream and, because trace events carry the message id as an idempotency key, one idem index file per trace stream as well; the bus traces every message type not explicitly zeroed. Result on the live ledger: 118,215 stream files + 90,755 idem files (1.4 GB), of which 88,356 streams and 88,356 idem files are traces under two days old (~41k new trace streams per day at steady state, retention is running). 76% of traces hold a single event, most rooted at broadcasts (ui.hook.received, world.camera.event, persona.state.changed, ui.notice, system.status.request, tool.registered) that are not in the zero-sample list; all 29 sampled percept.text.received traces are one-event streams because the turn's task is minted under trace_id=task_id (worker.py:277), so the user's message never roots the chain that answers it.

