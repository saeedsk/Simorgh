# refute:correctness:Compaction's blob sweep reads the entire

*Workflow: review · Phase: Refute · Agent id: `ae2fdd3d6c6321e98` · Tool calls: 5*

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
  
  
  You are a SKEPTIC. A reader claimed the following finding about concern "bus-ledger-substrate". Your job is to try to REFUTE it by reading the code it cites and the code around it. Lens: is the claim factually true of the code today (not history)? does the evidence support it? is it already in the known-findings list above?
  
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
| 1 | Bash | Read sweep_unreferenced_blobs in jsonl backend |  # over, so the mark goes with it; compaction never does. for path in (self._stream_path(stream), self._snapshot_path(stream), self._idem_path(stream), self._he |
| 2 | Bash | Read ledger service compaction path and config |  self._first_compaction: asyncio.Task \| None = None self.compactions = 0 self.last_report: dict \| None = None def _adopt(self, config: Config) -> None: self.con |
| 3 | Bash | Check for to_thread use, compaction loop shape, live ledger backend and sizes | --- regex 57:_BLOB_REF_BYTES = re.compile(rb"blob:(?:sha256:)?([0-9a-f]{64})") 752: for match in _BLOB_REF_BYTES.finditer(data): --- run_compaction 86:async def |
| 4 | Bash | Reproduce the blob sweep timing read-only on the live ledger and count compaction reasons | 18: backend: str = "jsonl" --- compaction stream ledger%3Acompaction.jsonl ledger%3Acompaction.jsonl events= 129 stream ledger%3Acompaction.jsonl reasons {'star |
| 5 | Bash | Check whether prior reviews already cover this and whether the ledger service runs on the main loop | docs/architecture-audit-2026.md:23:5. **Cognition Compaction Pipeline:** A 5-layer graduated pipeline (budget reduction → snip → microcompact → read-time collap |

## Structured reply

**refuted:** False

**verdict:** confirmed

**reasoning:** Every element of the claim holds against the code as it exists today and against a fresh read-only measurement on the live ledger. (1) simorgh/ledger/backends/jsonl.py:719-762: `sweep_unreferenced_blobs` is declared `async def` but its body is entirely synchronous -- `os.scandir` over `streams/` and `snapshots/`, `Path(entry.path).read_bytes()` on every file, and `_BLOB_REF_BYTES.finditer(data)` (regex at line 57) -- with no `await` and no `asyncio.to_thread`. `grep -n "to_thread\|run_in_executor" simorgh/ledger/service.py simorgh/ledger/compaction.py simorgh/ledger/backends/jsonl.py simorgh/ledger/client.py` returns nothing, so nothing in the ledger path offloads to a thread. (2) simorgh/ledger/service.py:141-144 awaits `sweep()` directly from `_compact`, which is awaited from `_compact_after_start` (line 87-101, created as an asyncio task in `start()` at line 64-65) and from the `system.tick.sleep` bus handler `_on_sleep` (line 117-123). So it runs on the kernel's single event loop; kernel/registry.py:141 constructs `LedgerService(ledger_client)` inline like every other subsystem, and `grep -n "to_thread\|Thread(\|run_in_executor\|new_event_loop" simorgh/kernel/*.py` returns nothing -- there is no thread isolation for the ledger. (3) simorgh/ledger/config.py:31 `compact_after_start_s: float = 30.0`; config.py:18 `backend: str = "jsonl"` and ~/.simorgh/simorgh.toml has no `backend` override, so the jsonl backend with the sweep is what runs live. (4) The sweep runs unconditionally on every pass -- service.py:141-144 executes before the `if report.streams_deleted or report.events_truncated` gate at line 146, so a pass that deletes nothing still pays the full scan. (5) Reproduced read-only on the live directory: 118,215 stream files + 1 snapshot, `blob sweep read+regex: 14.676s wall, 3.765s cpu, files=118216, bytes=390MB, refs=21312` -- consistent with (slightly worse than) the finding's 10.958 s figure; 3.8 s of that is pure CPU regex on the loop thread even with a warm cache. (6) `~/.simorgh/ledger/streams/ledger%3Acompaction.jsonl` has 129 events with reasons `{'start': 120, 'sleep_tick': 9}`, exactly as claimed; and since the compaction event is only appended when something was deleted (service.py:146), 129 is a lower bound on passes actually paid. Not in the known-findings list: the audit doc mentions `sweep_unreferenced_blobs` only as unimplemented on SqliteBackend (architecture-audit-2026.md:128) and the third-opinion doc's "Synchronous REPL Blocking" is about the REPL, not the ledger. The known finding "STT latency degrades under self-inflicted load" is a symptom; this is a distinct, new, periodic mechanism. Classification: (b)+(c) -- the design (async backend interface, single loop, background compaction) is fine, but the implementation hides a 4-15 s synchronous scan behind `async def`, which is a genuine bug. Severity 'high' is warranted: the freeze lands 30 s after every boot, when the creator is most likely mid-interaction, and blocks voice, TUI, HTTP and every bus handler.

### evidence

- simorgh/ledger/backends/jsonl.py:719-762 -- `async def sweep_unreferenced_blobs` with body `for subdir in ("streams", "snapshots"): ... with os.scandir(directory) as it: for entry in it: ... data = Path(entry.path).read_bytes() ... for match in _BLOB_REF_BYTES.finditer(data)`; no await, no to_thread
- simorgh/ledger/backends/jsonl.py:57 -- `_BLOB_REF_BYTES = re.compile(rb"blob:(?:sha256:)?([0-9a-f]{64})")`
- simorgh/ledger/service.py:141-144 -- `sweep = getattr(self.client.backend, "sweep_unreferenced_blobs", None); if sweep is not None: ... payload["blobs_swept"] = await sweep()` -- runs before the `if report.streams_deleted or report.events_truncated` gate at line 146, so every pass sweeps
- simorgh/ledger/service.py:64-65 -- `if self.config.compact_after_start_s > 0: self._first_compaction = asyncio.create_task(self._compact_after_start(), name="ledger-first-compaction")`; lines 87-101 `await asyncio.sleep(self.config.compact_after_start_s); await self._compact("start")`
- simorgh/ledger/service.py:117-123 -- `_on_sleep` bus handler for SYSTEM_TICK_SLEEP awaits `self._compact("sleep_tick", cause=message)` on the loop
- simorgh/ledger/config.py:18 `backend: str = "jsonl"`; config.py:31 `compact_after_start_s: float = 30.0`; `grep -n backend ~/.simorgh/simorgh.toml` -> no override, so jsonl runs live
- `grep -n "to_thread\|run_in_executor" simorgh/ledger/service.py simorgh/ledger/compaction.py simorgh/ledger/backends/jsonl.py simorgh/ledger/client.py` -> (no output)
- `grep -n "to_thread\|Thread(\|run_in_executor\|new_event_loop" simorgh/kernel/*.py` -> (no output); simorgh/kernel/registry.py:141 `"ledger": lambda: LedgerService(ledger_client)` -- same loop as every other subsystem
- simorgh/ledger/compaction.py:86-124 -- `run_compaction` is a per-stream loop of awaits on the same synchronous jsonl backend (`for stream in await backend.streams("")`, `read_snapshot`, `last_ts`, `truncate_below`, `delete_stream`), none of which yield to a thread
- Live ledger: `ls ~/.simorgh/ledger/streams | wc -l` -> 118215; `du -sh` -> streams 696M, snapshots 108K, blobs 325M (256 blobs)
- Reproduced read-only (python3 scandir+read_bytes+finditer over streams/ and snapshots/): `blob sweep read+regex: 14.676s wall, 3.765s cpu, files=118216, bytes=390MB, refs=21312`
- `~/.simorgh/ledger/streams/ledger%3Acompaction.jsonl`: 129 events; payload.reason counts `{'start': 120, 'sleep_tick': 9}` -- and service.py:146 only records a pass that deleted/truncated, so this undercounts passes actually paid
- Not already known: docs/architecture-audit-2026.md:128 mentions `sweep_unreferenced_blobs` only as unimplemented on SqliteBackend; docs/architecture-third-opinion-2026-09-18.md:140 'Synchronous REPL Blocking' concerns the REPL, not the ledger; no prior doc mentions event-loop blocking by compaction

**severity adjustment:** keep

