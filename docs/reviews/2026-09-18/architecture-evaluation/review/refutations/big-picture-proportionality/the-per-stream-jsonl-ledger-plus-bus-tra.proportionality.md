# refute:proportionality:The per-stream JSONL ledger plus bus tra

*Workflow: review · Phase: Refute · Agent id: `a28160c93a973a976` · Tool calls: 12*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "big-picture-proportionality". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
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
| 1 | Bash | Measure ledger directory sizes and stream counts | 1.4G . blobs heads idem index.json LOCK snapshots streams ---streams 118215 ---idem 90755 355M idem ---prefix 1 voice%3Aturns.jsonl 1 verify%3Afe1234ff5c0c.json |
| 2 | Bash | Count trace streams by prefix, age, root type, and depth | [('trace', 88356), ('action', 26737), ('task', 2431), ('verify', 350), ('reflect', 310), ('memory', 5), ('cognition', 5), ('curiosity', 5), ('persona', 3), ('gu |
| 3 | Bash | Read ledger config, bus config, and trace source |  815 simorgh/ledger/backends/jsonl.py 275 simorgh/ledger/backends/sqlite.py 176 simorgh/bus/trace.py 67 simorgh/ledger/config.py 1333 total --- ledger/config.py |
| 4 | Bash | Read retention defaults, jsonl layout, sqlite backend, and migration tooling | Exit code 1 --- retention defaults 34-# that", which is a question asked within hours, so a week of them was 35-# never read and only ever slowed the boot that  |
| 5 | Bash | Check trace_id propagation, percept handling, fsync per append, and boot index scan | --- trace_id propagation in bus client 145: trace_id: str \| None = None, 163: type, source=self._source, payload=payload, trace_id=trace_id, partition_key=parti |
| 6 | Bash | Trace percept handling, reply publishing, append fsync path, and stream enumeration cost | --- percept.text.received simorgh/interface/service.py:1005: # A voice turn is `percept.text.received{channel: "voice"}` from the simorgh/interface/telegram.py: |
| 7 | Bash | Check trace_id propagation in orchestration, idem fsync, boot scan, and index size | --- orchestration: does the turn chain carry the percept's trace_id? 36: topics.PERCEPT_TEXT_RECEIVED, topics.TOOL_REGISTERED, 98: self._percept_sub = await ctx |
| 8 | Bash | Check how orchestration builds the think request, measure boot scan time and trace byte volume | --- orchestration _on_percept -> how the think request is built 56: # handler timeout cannot cancel a long turn (see `_on_percept`). 98: self._percept_sub = awa |
| 9 | Bash | Read percept handler and break down ledger bytes by stream family | --- _on_percept 263-320 async def _on_percept(self, message) -> None: text = message.payload.get("text", "") if not text or not self._workers: return session_id |
| 10 | Bash | Compare apparent versus on-disk sizes and confirm think request drops the percept trace | --- apparent vs on-disk 652M . 404M streams 48M idem 188M blobs 1.4G . 696M streams 355M idem 325M blobs --- session.py think request 1225-1240 and session.prof |
| 11 | Bash | Check compaction support in sqlite backend and bus config overrides | --- what backend methods compaction needs 89: for stream in await backend.streams(""): 95: snapshot = await backend.read_snapshot(stream) 101: removed = await b |
| 12 | Bash | Check sqlite backend has last_ts for compaction | simorgh/ledger/backends/sqlite.py:267: async def last_ts(self, stream: str) -> float \| None: simorgh/ledger/api.py:94: async def last_ts(self, stream: str) -> f |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** Every number in the finding reproduces, and the mechanism behind the "one-event percept chain" is real and verifiable in code: orchestration/service.py:263-283 hands only text/session_id into worker.run_percept_chat, and session.py:1232 builds the think request with Message.new(...) and no trace_id, so a fresh uuid roots the answer; the Message.reply/caused and bus.new(caused_by=) helpers that would keep the chain exist (contracts/envelope.py:109-129, bus/client.py:140-163) but are not used on this path. That is the project's own "unconnected wire" shape, not a new design flaw. The default retention "trace:":"2d" (ledger/compaction.py:36) is working: 0 traces older than 2 days, 42,731 in the last 24h, so ~43k/day is the steady state, and bus/config.py:60-63 zeroes only ticks/metrics/health/provider.status/_inbox while the top roots are ui.notice, world.camera.event, persona.state.changed, ui.hook.received, system.status.request, tool.registered.

Two things are overstated. (1) The "1.4 GB" is mostly filesystem block rounding of tiny files, not data: apparent size is 652 MB total, idem is 48 MB apparent vs 355 MB on disk, streams 404 vs 696 MB, and the 88,356 trace streams hold 144 MB apparent (avg 1.6 KB). This actually sharpens the design point (file-per-stream is what makes it 1.4 GB) but the byte figure should not be cited as ledger volume. (2) The operational pain is smaller than "high" suggests at this scale: the boot scan already trusts index.json (jsonl.py:200-235) and a live measurement of scandir+stat over all 118,215 streams took 0.32 s, index load 0.08 s. The write cost per traced message is one fsync'd append (jsonl.py:409-413) plus an unfsynced idem line, on an event loop that is otherwise waiting on an LLM. Nothing here is on the user-visible path.

Proportionality of the recommendation: zeroing five more broadcast types in trace_sample is a one-line change with an obvious payoff and no risk (the config comment at bus/config.py:40-58 already explains why whole-type exclusion is the right knob). Propagating trace_id through the percept path is a small, correct fix that makes the surviving traces answer the only question they exist for. Switching the default backend to sqlite is feasible (sqlite.py:161-267 implements streams/truncate_below/delete_stream/last_ts so compaction works; it is exercised in tests/simorgh/ledger/test_backends.py:330,437; migrate_v1.py exists) but it is a migration of a live 650 MB ledger for a benefit that is currently ~1 GB of block padding and slower `ls`, so it is a reasonable medium-priority cleanup rather than a high-severity architectural error. Category: (b) right design (append-only Ledger, whole-type trace exclusion, retention) undermined by two implementation gaps (broadcast types not excluded; percept chain broken), plus a backend default that is disproportionate to a one-laptop scale but not harmful today.

### evidence

- du -sh ~/.simorgh/ledger -> 1.4G; du -sh -A (apparent) -> 652M total, streams 404M (on-disk 696M), idem 48M (on-disk 355M), blobs 188M (on-disk 325M)
- ls streams | wc -l -> 118215; ls idem | wc -l -> 90755; prefix counts: trace 88356 / action 26737 / task 2431 / verify 350 / reflect 310
- find streams -name 'trace*' -mtime +2 | wc -l -> 0; -mmin -1440 -> 42731 (steady state ~43k trace streams/day); simorgh/ledger/compaction.py:36 DEFAULT_RETENTION = {"trace:": "2d", ...}
- trace stream apparent bytes: 144,289,993 over 88,356 files (avg 1633 B); trace idem apparent bytes 4,823,858 over 88,356 files -> the 355M idem dir is block rounding
- sample of 800 trace streams: roots ui.notice 110, world.camera.event 107, persona.state.changed 98, ui.hook.received 92, system.status.request 74, voice.listening 66, tool.registered 33; depth: 624 have 1 event, 132 have 2, 39 have 3; all 5 percept.text.received roots had exactly 1 event
- simorgh/bus/config.py:60-63 trace_sample zeroes only system.tick.second/idle/sleep, system.metrics, system.health, cognition.provider.status, _inbox.#; ~/.simorgh/simorgh.toml has no [bus] trace_sample override and no [ledger] section
- simorgh/ledger/config.py:18 backend: str = "jsonl"; simorgh/bus/trace.py:1-2 'every message -> Ledger stream trace:<trace_id>'; trace.py:96-105 _to_event sets idempotency_key=message.id so every traced message also appends an idem line
- simorgh/orchestration/service.py:263-283 _on_percept passes only session_id/text/channel/who to worker.run_percept_chat (worker.py:387) -- the percept Message is dropped; simorgh/orchestration/session.py:1232 req = Message.new(topics.COGNITION_THINK, ...) with no trace_id -> contracts/envelope.py:98 assigns a fresh uuid4; the reply/caused helpers at envelope.py:109-129 and bus/client.py:140-163 (caused_by=) exist and are unused here
- simorgh/ledger/backends/jsonl.py:397-440 append: one open/write/flush/os.fsync per event (fsync=True default at config.py:20) plus _append_idem_line (jsonl.py:442-449, no fsync)
- simorgh/ledger/backends/jsonl.py:200-235: boot trusts index.json and stats each stream; measured live: index.json (12.8 MB) load 0.08s, os.scandir+stat over 118,215 streams 0.32s
- wc -l: jsonl.py 815, sqlite.py 275; sqlite.py:161 streams(), :193 truncate_below(), :216 delete_stream(), :267 last_ts() -> compaction.py:89-124 works on sqlite; tests/simorgh/ledger/test_backends.py:330,437 construct SqliteBackend; simorgh/ledger/migrate_v1.py exists

**severity adjustment:** lower

**corrected claim:** The bus traces every message type except six heartbeat/metrics types into the Ledger as one JSONL stream per trace_id, and the chat path breaks trace_id propagation (orchestration/service.py:263-283 drops the percept Message; session.py:1232 builds the think request with a fresh trace), so ~43k trace streams/day are written, ~78% of them single-event chains rooted at broadcasts (ui.notice, world.camera.event, persona.state.changed, ui.hook.received, system.status.request, tool.registered) that answer nothing. Retention (2d) is working, so this is a steady state, not growth. The 1.4 GB on disk is mostly APFS block rounding of ~207k tiny files (652 MB apparent; traces 144 MB, idem 4.8 MB apparent vs 355 MB on disk); boot already trusts index.json and the full stat pass takes ~0.3 s, so the cost today is disk padding, slow directory operations and backups, and traces that cannot answer 'what happened after the user said X'. Fix in order of payoff/effort: add the five broadcast types to trace_sample (one line), pass the percept through so the turn shares its trace_id (small, uses existing Message.caused/bus.new(caused_by=)), and only then consider making sqlite the default backend, which is a supported and tested but non-trivial migration.

