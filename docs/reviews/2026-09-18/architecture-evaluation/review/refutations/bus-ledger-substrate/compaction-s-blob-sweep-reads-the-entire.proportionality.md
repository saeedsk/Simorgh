# refute:proportionality:Compaction's blob sweep reads the entire

*Workflow: review · Phase: Refute · Agent id: `a00e124464e203c52` · Tool calls: 10*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "bus-ledger-substrate". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: even if true, is it actually an architectural problem at this system's scale (one laptop, one family, one developer), or is the recommendation disproportionate / would create more work than it saves?
  
  FINDING:
  {
    "title": "Compaction's blob sweep reads the entire ledger synchronously on the event loop, 30 s after every boot and every 6 h",
    "kind": "bug",
    "severity": "high",
    "claim": "sweep_unreferenced_blobs reads every stream file's bytes with plain open().read() inside an async method with no to_thread, and the ledger Service awaits it on the event loop, so the whole process (voice, TUI, HTTP, every bus handler) stalls for roughly ten seconds at +30 s after each boot and on each sleep tick.",
    "evidence": [
      "simorgh/ledger/backends/jsonl.py:739-753 -- `for subdir in (\"streams\", \"snapshots\"): ... data = Path(entry.path).read_bytes()` with no to_thread",
      "simorgh/ledger/service.py:141-144 -- `sweep = getattr(self.client.backend, \"sweep_unreferenced_blobs\", None) ... payload[\"blobs_swept\"] = await sweep()`",
      "simorgh/ledger/service.py:65 and simorgh/ledger/config.py:31 -- first pass is `asyncio.create_task(self._compact_after_start())` after `compact_after_start_s: float = 30.0`",
      "measured in isolation on the live ledger dir: `(c) blob sweep read+regex: 10.958s wall, 3.579s cpu, 390MB, 21312 refs`",
      "ledger:compaction stream: `compaction passes=129 reasons={'start': 120, 'sleep_tick': 9}` -- 120 boots each paid this",
      "run_compaction's per-stream loop is also synchronous: `(a) streams('') scandir+stat over 118215 files: 0.306s`, `(b) snapshot exists() x118215: 0.372s`"
    ],
    "why_it_matters": "A ten-second freeze of the single event loop is exactly the 'Sim went silent' symptom; it lands right when the creator has just restarted and is typing or talking. The known finding 'STT latency degrades under self-inflicted load' has this as one concrete, periodic source.",
    "recommendation": "Run run_compaction + sweep under asyncio.to_thread (the JSONL backend is synchronous anyway and holds its own locks), and only sweep blobs when the pass actually deleted or truncated something. Longer term keep a per-blob reference count updated at append/delete time instead of rescanning 390 MB.",
    "confidence": 0.92
  }
  
  Default to refuted=true if you cannot verify the claim yourself against file:line evidence. Verify with commands where cheap (grep, python -c, wc). Do not boot the system or run the suite. Return only the structured verdict.
```

## What the agent did (tool trail)

| # | Tool | What | Result (first 160 chars) |
|---|---|---|---|
| 1 | Bash | Read blob sweep in JSONL backend |  tmp = path.with_name(path.name + ".tmp") try: with open(tmp, "wb") as fh: fh.write(data) fh.flush() if self._fsync: os.fsync(fh.fileno()) os.replace(tmp, path) |
| 2 | Bash | Read ledger service compaction path |  self._first_compaction: asyncio.Task \| None = None self.compactions = 0 self.last_report: dict \| None = None def _adopt(self, config: Config) -> None: self.con |
| 3 | Bash | Read ledger config defaults | """`[ledger]` configuration (02-ledger section 3.5). Loaded by the Kernel from `simorgh.toml`; `SIMORGH_LEDGER_BACKEND` and `SIMORGH_LEDGER_DIR` override the fi |
| 4 | Bash | Check for thread offloading in ledger and compaction | ---compaction 86:async def run_compaction(backend: LedgerBackend, policy: RetentionPolicy, *, now: float, 89: for stream in await backend.streams(""): 95: snaps |
| 5 | Bash | Inspect live ledger directory sizes and config | blobs heads idem index.json LOCK snapshots streams --- streams: files=118215 size=696M snapshots: files=1 size=108K blobs: files=256 size=325M --- toml |
| 6 | Bash | Check sleep tick interval and bus handler dispatch | simorgh/kernel/api.py:41: sleep_every_s: float = 6 * 3600 simorgh/kernel/config.py:80: "idle_threshold_s": float, "idle_tick_cooldown_s": float, "sleep_every_s" |
| 7 | Bash | Time a read-only replica of the blob sweep scan on the live ledger | 57:_BLOB_REF_BYTES = re.compile(rb"blob:(?:sha256:)?([0-9a-f]{64})") 752: for match in _BLOB_REF_BYTES.finditer(data): sweep scan: wall=2.82s cpu=2.82s files=11 |
| 8 | Bash | Read the tail of the compaction stream | ledger%3Acompaction.jsonl {"causation_id":"68ee5617-6b3b-45eb-9dc6-c3c60e7d4d43","idempotency_key":null,"payload":{"events_truncated":0,"reason":"sleep_tick","s |
| 9 | Bash | Locate the bus implementation and its dispatch model | __init__.py __pycache__ api.py bootprogress.py cli.py config.py configcheck.py context.py metrics.py migrate_v1.py README.md registry.py scheduler.py secrets.py |
| 10 | Bash | Check backend locking, single event loop, and thread offloading elsewhere | 183: lock = self._locks[stream] = asyncio.Lock() 401: with self._file_lock(): 439: def _file_lock(self): 647: with self._file_lock(): 688: with self._file_lock( |

## Structured reply

**refuted:** False

**verdict:** partly-true

**reasoning:** The structural claim is confirmed against the code. `sweep_unreferenced_blobs` (simorgh/ledger/backends/jsonl.py:721-761) is an `async def` whose body is entirely synchronous: `os.scandir` over `streams/` and `snapshots/`, `Path(entry.path).read_bytes()` on every file, and a regex `finditer` over each; there is no `to_thread`/`run_in_executor` anywhere in simorgh/ledger (grep returned nothing). `LedgerService._compact` (service.py:130-162) does `report = await run_compaction(...)` then `payload["blobs_swept"] = await sweep()` unconditionally whenever the backend has the method, and `run_compaction` (compaction.py:86-124) is likewise a loop of awaits over `async def` methods that do synchronous file IO. The first pass is scheduled with `asyncio.create_task(self._compact_after_start())` after `compact_after_start_s = 30.0` (service.py:65, config.py:31), and the sleep tick default is `sleep_every_s = 6*3600` (kernel/api.py:41). The Kernel runs everything under one `asyncio.run` (kernel/cli.py:381), so a synchronous body in any coroutine stalls every other coroutine (bus handlers, TUI, HTTP); this is a Python asyncio fact, not a guess. The live ledger has 118,215 stream files and the compaction stream is at seq 129 (`streams_seen` ~95k-110k per pass), so the pass really runs at the claimed cadence.

What is overstated is the magnitude. Replicating the exact scan (same regex, same dirs) on the live ledger just now took 2.82 s wall, 2.82 s CPU, 390 MB read, 21,312 refs, 237 MB RSS -- i.e. with a warm page cache it is CPU-bound at about 3 s, not 10 s. The reader's 10.96 s figure (3.6 s CPU) reflects a cold cache; after a normal Sim restart (process restart, not machine reboot) the cache is warm, so the typical per-boot stall is ~3 s plus run_compaction's own synchronous walk (~0.7 s measured by the reader). A 3-4 s full-process freeze 30 s after every boot and every 6 h is still a real bug, but 'roughly ten seconds' is the cold-cache worst case.

Two additional observations. (1) The sweep is unconditional -- it runs even when `run_compaction` deleted nothing -- so the 'only sweep when something changed' half of the recommendation is well-founded and trivially cheap. (2) A caveat on the recommendation: the JSONL backend's per-stream locks are `asyncio.Lock` (jsonl.py:183) and `run_compaction` mutates in-memory `_meta` via `truncate_below`/`delete_stream`, so wrapping the whole of `run_compaction` in `asyncio.to_thread` is not automatically safe against concurrent `append` on the loop; the blob sweep itself (read-only scan + blob-dir deletes) is safe to thread as-is. Minor side note: `blobs_swept` is put in `payload` but the appended `ledger.compacted` event uses `report.as_payload()`, so the swept count is never recorded in the ledger (visible in the compaction stream tail, which has no `blobs_swept` key).

At this system's scale the fix is proportionate: one `to_thread` around the sweep and one `if report.streams_deleted or report.events_truncated:` guard is a few lines and removes a user-visible freeze that lands exactly when the creator has just restarted and starts typing/talking. The reference-count 'longer term' suggestion is over-engineering for one laptop and can be dropped.

### evidence

- simorgh/ledger/backends/jsonl.py:721-761 -- `async def sweep_unreferenced_blobs`: `with os.scandir(directory) as it: for entry in it: ... data = Path(entry.path).read_bytes() ... for match in _BLOB_REF_BYTES.finditer(data)`; fully synchronous body, no thread offload
- simorgh/ledger/service.py:130-162 -- `report = await run_compaction(self.client.backend, self.policy, now=now)` then `sweep = getattr(self.client.backend, "sweep_unreferenced_blobs", None); if sweep is not None: payload["blobs_swept"] = await sweep()` -- unconditional, not gated on anything having been deleted
- simorgh/ledger/service.py:65 -- `self._first_compaction = asyncio.create_task(self._compact_after_start(), name="ledger-first-compaction")`; service.py:91-92 -- `await asyncio.sleep(self.config.compact_after_start_s); await self._compact("start")`
- simorgh/ledger/config.py:31 -- `compact_after_start_s: float = 30.0`; simorgh/kernel/api.py:41 -- `sleep_every_s: float = 6 * 3600`
- simorgh/kernel/cli.py:381 -- `return asyncio.run(_cmd_run(args.config))` (one event loop for the whole process)
- `grep -n "to_thread\|run_in_executor" simorgh/ledger/*.py simorgh/ledger/backends/jsonl.py` -> no output
- simorgh/ledger/compaction.py:86-124 -- `run_compaction` loops `for stream in await backend.streams("")` calling `read_snapshot`, `last_ts`, `truncate_below`, `delete_stream`, `read`, `head` -- all async-def wrappers over synchronous file IO
- Live ledger: `ls ~/.simorgh/ledger/streams | wc -l` -> 118215 files, 696M on disk; blobs: 256 files, 325M; snapshots: 1 file
- Measured replica of the sweep scan on the live ledger (same regex, same dirs): `sweep scan: wall=2.82s cpu=2.82s files=118216 bytes=390MB refs=21312 maxrss=237MB` -- warm cache, CPU-bound; the reader's 10.96 s / 3.58 s CPU figure is the cold-cache case
- ~/.simorgh/ledger/streams/ledger%3Acompaction.jsonl tail: seq 127-129, `"reason":"sleep_tick"`, `streams_seen` 110468 / 95272 / 106918, ts spaced 21600 s apart (6 h); no `blobs_swept` key in the recorded payload
- simorgh/ledger/backends/jsonl.py:183 -- `lock = self._locks[stream] = asyncio.Lock()` (asyncio, not threading, locks -- threading the whole run_compaction needs care; the blob sweep alone is safe to thread)

**corrected claim:** sweep_unreferenced_blobs reads every stream file synchronously inside an async method with no thread offload, and LedgerService._compact awaits it (plus the equally synchronous run_compaction walk) on the single event loop, unconditionally, 30 s after every boot and on every 6-hourly sleep tick. On the live ledger (118k files, 390 MB) the sweep alone is a ~3 s CPU-bound stall with a warm page cache and ~11 s cold; during that window every coroutine in the process (bus handlers, TUI, HTTP, voice control path) is frozen. It also runs even when the compaction pass deleted nothing.

**severity adjustment:** keep

