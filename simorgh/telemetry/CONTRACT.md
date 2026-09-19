# telemetry -- contract

One-line status: layer 0 · ~500 lines · 2 test files · lock: `telemetry` in docs/modules/locks.toml

## Purpose

Telemetry holds operational measurements that are not decisions: spans (one timed operation inside a trace, with a parent, a status and attributes) and samples (one value of a named series at a time). They live in one SQLite file, `<data_dir>/telemetry.sqlite`, in WAL mode, so the JSONL decision log can hold only decisions (stage 1 item 1; evaluation B2, P4). The shaping decision: recording is an append to an in-memory buffer and nothing else on the caller's path; one writer task writes a batch in one transaction on a worker thread 250 ms after its first row (or at `batch_rows`), with no fsync per row. Retention is by age per table (spans 14 d, samples 7 d), and samples older than a day are thinned to one per minute per series. The store is the Kernel's own, like the ledger: built at boot, handed to every `Context` as `ctx.telemetry`, flushed and closed at shutdown. It is not a supervised subsystem and has no `Service` in `LAYERS`. It must never raise into the code it measures (an unencodable attribute is stored as its `repr`; a failed write is counted, not propagated) and never lose a buffered row on a clean shutdown. It imports only `simorgh.contracts` and the standard library (`tests/simorgh/test_module_boundaries.py`).

As of this item nothing writes to it but tests: routing bus tracing and metrics into it is stage 1 item 3, per-stage spans are item 4.

## Files

| File | For |
|---|---|
| `simorgh/telemetry/__init__.py` | re-exports `Config`, `FILENAME`, `RecordingSpan`, `TelemetryService`, `TelemetryStore` |
| `simorgh/telemetry/config.py` | `[telemetry]` dataclass and `from_mapping` (negative values refused) |
| `simorgh/telemetry/store.py` | `TelemetryStore`: schema, batched insert, trace and series reads, retention and downsampling; synchronous, one connection behind a lock |
| `simorgh/telemetry/service.py` | `TelemetryService`: implements `contracts.protocols.Telemetry`; the buffer, the writer task, `flush`, `query`, `series`, `maintain`, `on_sleep_tick`, `stop` |

## Consumes

Telemetry subscribes to nothing itself. The Kernel subscribes to `system.tick.sleep` on its behalf and calls `TelemetryService.on_sleep_tick()` (`simorgh/kernel/service.py:335`, `_on_sleep_tick`).

| Topic | Schema | Where | Does |
|---|---|---|---|
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/kernel/service.py:335 (Kernel, on this package's behalf) | one retention pass, skipped when one ran within `maintain_min_interval_s` wall-clock seconds |

From `simorgh.contracts.protocols`: `Telemetry`, `Span`, `Clock`, `Logger` (the shapes it implements and is handed).

## Produces

Nothing on the bus. It writes two SQLite tables:

| Table | Columns | Indexes | Retention |
|---|---|---|---|
| `spans` | `trace_id, span_id, parent_id, name, start, "end", status, attrs_json` | `spans_trace(trace_id)`, `spans_start(start)` | rows whose `start` is older than `span_retention_days` (14) |
| `samples` | `series, ts, value_json` | `samples_series_ts(series, ts)`, `samples_ts(ts)` | rows older than `sample_retention_days` (7); rows older than `downsample_after_days` (1) thinned to the last-written row per `(series, downsample_bucket_s)` bucket |

`end` is an SQL keyword and is quoted in every statement; `status` is `ok`, `error` (the body raised an `Exception`; `attrs.error` holds `"<Type>: <message>"`) or `cancelled`.

## Ledger streams

None. Telemetry is deliberately not in the ledger.

## Config

`[telemetry]` in simorgh.toml, read by the Kernel (`kernel/service.py`, `Kernel.boot`); dataclass in `simorgh/telemetry/config.py`. The section is in `kernel/configcheck.py` `KERNEL_SECTIONS` and its class in `_config_classes`, so a mistyped key is reported at boot.

| Key | Default | Read in the package |
|---|---|---|
| `enabled` | `True` | yes (by the Kernel: false opens no file and hands out `NULL_TELEMETRY`) |
| `flush_interval_s` | `0.25` | yes (`service._write_loop`) |
| `batch_rows` | `500` | yes (`service._enqueue`) |
| `max_buffer_rows` | `50000` | yes (`service._enqueue`: oldest dropped and counted beyond it) |
| `span_retention_days` | `14.0` | yes (`maintain`) |
| `sample_retention_days` | `7.0` | yes (`maintain`) |
| `downsample_after_days` | `1.0` | yes (`maintain`) |
| `downsample_bucket_s` | `60.0` | yes (`maintain`) |
| `maintain_after_start_s` | `60.0` | yes (`start`: one pass this long after start; 0 disables) |
| `maintain_min_interval_s` | `600.0` | yes (`on_sleep_tick`) |

No environment variables. The file path is fixed: `<[runtime] data_dir>/telemetry.sqlite`.

## Public Python surface

- `TelemetryService(path, *, config=None, clock=None, logger=None, monotonic=time.monotonic)`: implements `Telemetry`.
  - `async start()`, `async stop()` (flushes, then closes; a row recorded after stop is dropped and counted).
  - `span(name, *, trace_id, parent_id=None, attrs=None)`: async context manager yielding a `RecordingSpan` (`trace_id`, `span_id` 16 hex, `parent_id`, `name`, `start`, `attrs`, `set(key, value)`). Without `parent_id`, the innermost open span of the same trace in this task (a `contextvars` variable, inherited by child tasks) is the parent.
  - `sample(series, value, ts=None)`: `value` any JSON-able; `ts` defaults to the clock's now.
  - `event(name, *, trace_id, span_id, parent_id=None, ts=None, attrs=None)`: a finished zero-length span with the caller's id. The bus writes one per traced message (stage 1 item 3). `store.read_trace(path, trace_id)` reads a file read-only (`simorgh trace`).
  - `async query(trace_id) -> list[dict]`: flushes first; keys `trace_id, span_id, parent_id, name, start, end, status, attrs`; ordered by `start`, a parent before its children on equal starts.
  - `async series(series, *, since=None, until=None) -> list[dict]`: flushes first; keys `series, ts, value`.
  - `async flush()`, `async maintain(now=None) -> {"spans", "samples", "downsampled"}`, `async on_sleep_tick() -> dict | None`.
  - Attributes: `counters` (`spans`, `samples`, `flushes`, `dropped`, `write_errors`, `maintain_runs`), `last_retention`, `path`, `store`, `config`.
- `TelemetryStore(path)`: synchronous `open`, `close`, `write(spans, samples)`, `spans(trace_id)`, `samples(series, since=, until=)`, `counts()`, `retain(now=, span_max_age_s=, sample_max_age_s=, downsample_after_s=, bucket_s=)`. Call it from a worker thread.
- `Config`, `FILENAME = "telemetry.sqlite"`.
- Module-level state: `service._CURRENT`, a `ContextVar` holding the innermost open span per task.

## Invariants

- Recording (`span` exit, `sample`) never touches SQLite and never raises; every SQLite call runs in `asyncio.to_thread`.
- A batch is one transaction; `synchronous=NORMAL` under WAL (no fsync per commit).
- Idle, the writer task waits on an event and does not wake.
- A span's exception is re-raised unchanged after the row is recorded with status `error`; cancellation is recorded as `cancelled` and re-raised.
- `stop()` writes every buffered row before closing; `query`/`series`/`maintain` flush before reading.
- The buffer never holds more than `max_buffer_rows`; overflow drops the oldest row of the same kind and counts it in `dropped`.
- Retention never deletes a span younger than `span_retention_days` or a sample younger than `downsample_after_days`; downsampling is idempotent.
- Imports: `simorgh.contracts` and the standard library only.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract telemetry`.

- `tests/simorgh/telemetry/test_store.py` -- WAL file, table columns and indexes; 10k spans then one trace by index; start/end/status/attrs; nested and child-task parent ids; exception marks `error` and re-raises; cancellation; batching by timer and by size; stop flushes everything; bounded buffer; retention by age; one sample per minute per series; sleep-tick rate limit; the after-start pass; every config key read.
- `tests/simorgh/telemetry/test_kernel_wiring.py` -- a booted Kernel puts one store on every Context, the sleep tick runs retention, shutdown flushes, `enabled = false` hands out the no-op.
- `tests/simorgh/contracts/test_telemetry_protocol.py` -- the protocol's no-op and the `Context.telemetry` default.

## Known issues (2026-09-18 evaluation)

- B2 / P4: the store exists but nothing writes to it yet; trace streams still go to the ledger until stage 1 item 3.
- `WorkerKernel` (local-multi) builds its Contexts without a store, so a worker process records nothing. Deliberate: `WorkerKernel` is frozen in stage 1 item 10.

## Planned changes (roadmap)

- Stage 1 item 3: `bus/trace.py::TraceWriter` writes one span per message here (name = topic, parent = causation id) with a per-prefix sampling rate; `metrics:history`, `curiosity:ticks`, `persona:state` become samples; `simorgh trace <id>` reads `query`.
- Stage 1 item 4: per-stage spans on the daily path (STT, speaker id, think, guardian decide, tool run, verify, TTS synth, playback) via `ctx.telemetry.span(...)`.
- Stage 1 item 5: a deadline breach is recorded as a span event.

## Working on this module

Lock it first (`python tools/modlock.py claim telemetry --by <you> --task "..."`), commit the lock, edit only `simorgh/telemetry/`, `tests/simorgh/telemetry/` and this file; a change to the `Telemetry` protocol in `simorgh/contracts/` needs the `contracts` lock and a note in the kernel's CONTRACT.md. Run `python tools/modtest.py telemetry` before committing; commit subject `telemetry: <what changed>`.
