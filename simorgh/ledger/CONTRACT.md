# ledger -- contract

One-line status: layer 0 · 2,798 lines · 14 test files · lock: `ledger` in docs/modules/locks.toml

## Purpose

The ledger is the append-only record of everything that happened: named streams of immutable `Event`s with a per-stream monotonic `seq`, compare-and-swap appends (`expected_seq`), idempotency keys, snapshots for projections, content-addressed blobs for anything over the inline threshold, and retention. It owns storage semantics only; it does not decide who may write which stream (`streams.KNOWN_PREFIXES` is informational, `streams.py:16-18`) and does not interpret payloads. It must never renumber, reorder or silently drop an event (a corrupt line is a gap, not the end of the stream), never let a stream's head go backwards, and never accept a payload string over `blob_inline_threshold` that is not a `blob:` ref. The shaping decision: one `LedgerClient` layers validation, idempotency, tail delivery and counters over small mechanical backends (`memory`, `jsonl`, `sqlite`, `dynamodb`) behind `api.LedgerBackend`, and the Kernel hands the same client to every subsystem as `Context.ledger`. The live backend is `jsonl`: one file per stream plus sidecars.

## Files

| File | For |
|---|---|
| `simorgh/ledger/__init__.py` | re-exports client, config, errors, factory, `Service` |
| `simorgh/ledger/api.py` | `LedgerBackend` protocol, `Projection` base, error types |
| `simorgh/ledger/backends/__init__.py` | package docstring naming the four engines |
| `simorgh/ledger/backends/dynamodb.py` | DynamoDB + S3 engine behind adapter protocols; unused live |
| `simorgh/ledger/backends/jsonl.py` | live default: one JSONL file per stream, head marks, idempotency sidecars, blob dir, blob sweep |
| `simorgh/ledger/backends/memory.py` | reference semantics for tests |
| `simorgh/ledger/backends/sqlite.py` | WAL SQLite engine, CAS on `(stream, seq)`; unused live |
| `simorgh/ledger/blobs.py` | `blob:<sha256>` refs and the on-disk blob store |
| `simorgh/ledger/client.py` | `LedgerClient`: validation, idempotency, CAS, `tail`, snapshots, blobs, counters |
| `simorgh/ledger/compaction.py` | `DEFAULT_RETENTION`, `RetentionPolicy`, `run_compaction` |
| `simorgh/ledger/config.py` | `[ledger]` dataclass and `SIMORGH_LEDGER_*` env overrides |
| `simorgh/ledger/factory.py` | `make_backend`/`make_ledger`, optional jsonl fallback |
| `simorgh/ledger/idempotency.py` | per-stream idempotency-key index (jsonl cache) |
| `simorgh/ledger/migrate_v1.py` | maps v1 `memory.jsonl` records to v2 streams |
| `simorgh/ledger/projection.py` | `rebuild`/`materialize`: snapshot then replay |
| `simorgh/ledger/service.py` | the ledger's `Service`: compaction on sleep tick and after start, metrics, health |
| `simorgh/ledger/streams.py` | stream-name grammar, filename escaping, `KNOWN_PREFIXES`, `COMPACTION_STREAM` |

## Consumes

| Topic | Schema | Where | Does |
|---|---|---|---|
| `system.tick.sleep` | `messages/system.py::SystemTickSleep` | simorgh/ledger/service.py:63 | validates the payload, then runs one retention pass and the blob sweep |

## Produces

| Topic | Schema | Where | When |
|---|---|---|---|
| `system.metrics` | `messages/system.py::SystemMetrics` | simorgh/ledger/service.py:169 | after every compaction pass (sleep tick or the start pass): backend `stat()`, client counters, last report |

## Ledger streams

The ledger writes one stream of its own; every other stream is written by its owning module through `Context.ledger`.

| Stream | Named in | Also read by | Retention |
|---|---|---|---|
| `ledger:compaction` | simorgh/ledger/streams.py:42 (`COMPACTION_STREAM`), appended in service.py:151 only when a pass removed something | - | never compacted (`ledger:` is the protected prefix, compaction.py:104) |
| `v1:<id>` idempotency keys onto `task:*`, `learn:patches`, `learn:skills`, `cognition:budget`, `curiosity:interests`, `memory:semantic`, `memory:episodic`, `activity`, `guardian:rejected` | simorgh/ledger/migrate_v1.py:30-46 (`route_v1`) | simorgh/kernel/migrate_v1.py (performs the appends) | per the target stream |

Retention for every stream is decided here, in `compaction.py:47-53` `DEFAULT_RETENTION`, merged with `[ledger.retention]`; the longest matching prefix wins and no match means forever:

| Prefix | Window |
|---|---|
| `trace:` | 2d |
| `dead:` | 30d |
| `activity` | 90d |
| `metrics:history`, `curiosity:ticks`, `persona:state`, `execution:inflight` | 7d |
| `execution:tools`, `cognition:summaries:`, `voice:turns`, `action:` | 30d |
| `cognition:budget:` | 3d |
| `verify:`, `reflect:` | 90d |
| everything else | forever (truncated to snapshot minus `keep_tail` only if a snapshot exists) |

How a window applies depends on activity, not on the name (since 2026-09-19, commit 6ce1c78): a stream whose last event is older than its window is deleted whole; otherwise events older than the window are truncated. (It used to depend on the name -- any `:` meant delete-only -- so the long-lived `metrics:history`, `curiosity:ticks` and friends were never trimmed.)

## Config

`[ledger]` in simorgh.toml; dataclass in `simorgh/ledger/config.py`.

| Key | Default | Read in the package |
|---|---|---|
| `backend` | `'jsonl'` | yes |
| `data_dir` | `'~/.simorgh/ledger'` | yes (via `Config.data_path`, factory.py) |
| `fsync` | `True` | yes |
| `snapshot_every` | `200` | NO (declared, never read; `Projection.snapshot_every` has its own default, api.py:105) |
| `blob_inline_threshold` | `4096` | yes |
| `tail_poll_ms` | `100` | yes |
| `keep_tail` | `50` | yes |
| `retention` | `field(default_factory=dict)` | yes |
| `compact_after_start_s` | `30.0` | yes |
| `allow_fallback` | `False` | yes |
| `dynamodb_table` | `''` | yes |
| `dynamodb_bucket` | `''` | yes |

Env overrides: `SIMORGH_LEDGER_BACKEND`, `SIMORGH_LEDGER_DIR` (`config.py:48-53`). `[ledger.dynamodb] table/bucket` and `[ledger.retention] keep_tail` are nested tables.

## Public Python surface

- `simorgh.ledger.Service` (`service.py`): `name="ledger"`, `consumes=(system.tick.sleep,)`, `produces=(system.metrics,)`, `__init__(client, config=None)`; reads `ctx.config` at `start` when no config was passed. Health: `down` before start or after a `LedgerUnavailable`; `degraded` under 5% free disk.
- `simorgh.ledger.client.LedgerClient`: the only ledger module other packages may import; implements `contracts.protocols.Ledger`: `append(stream, event, *, expected_seq)`, `head`, `read`, `streams(prefix)`, `delete_stream`, `tail(stream_or_prefix, handler)`, `snapshot`, `load_snapshot`, `rebuild`, `materialize`, `put_blob`, `get_blob`, `compact`; attributes `counters`, `last_error`, `started`, `backend`.
- Kernel-only: `make_ledger`, `make_backend`, `Config`.
- Exceptions: `ConflictError` (CAS lost), `ValidationError`, `LedgerUnavailable`, `BackendUnavailable`, `BlobNotFound`, all subclasses of `LedgerError` (`api.py`).
- Through `simorgh.contracts`: `Event` (`contracts/envelope.py`), the `Ledger` protocol (`contracts/protocols.py`), the stream-name grammar `is_valid_stream`/`MAX_STREAM_NAME` (`contracts/streamnames.py`).
- Module-level singletons: none in the package. Risk: the Kernel shares one unbound `LedgerClient` across all subsystems (`kernel/context.py:141`); `source="ledger"` on the client is never used to check writers (B7).

## Invariants

- `append` rejects an invalid stream name, a non-object payload, NaN/Infinity, non-string keys, non-JSON values, an empty `type`, and any string longer than `blob_inline_threshold` that is not a `blob:` ref; nothing is written on rejection.
- An append whose `idempotency_key` is already recorded on that stream returns the existing `seq` and writes nothing.
- `append(..., expected_seq=n)` succeeds only if the stream head is `n`; otherwise it raises `ConflictError`. Every backend behaves the same (parity tests).
- `seq` starts at 1, increases by one per append, and the head of a stream never goes backwards, including after truncation, restart, or a lost index.
- An unparseable JSONL line is reported as a gap; events after it are still read with their own `seq`; compaction refuses to rewrite a stream with a corrupt line.
- A crash mid-write loses at most the record being written; start truncates a trailing partial line.
- Blob refs are content-addressed (`blob:<64 hex>`); `get_blob` verifies the digest; `put_blob` of identical bytes returns the same ref.
- `tail` never delivers the same `(stream, seq)` twice to one subscriber, and a subscriber's exception never fails the append.
- Compaction never touches `ledger:*`; a forever stream without a snapshot is never truncated.
- The blob sweep runs off the event loop (`asyncio.to_thread`, `JsonlBackend.sweep_unreferenced_blobs`) and its count is in the compaction record as `blobs_swept`.
- `JsonlBackend.streams(prefix)` (the `scandir` + `stat` walk that `run_compaction` starts every pass with) also runs on a worker thread (`_streams_sync`). Pinned in `tests/simorgh/ledger/test_blob_sweep_off_the_loop.py`.
- The ledger does not publish `system.health`; the Kernel polls `health()` and publishes a status change (kernel's health ticker).
- `ledger:compaction` gets an event only when a pass deleted or truncated something; `system.metrics` is published after every pass.

## Contract tests

The files below pin the interface above. Keep them green: `python tools/modtest.py --tier contract ledger`.

- `tests/simorgh/ledger/test_backends.py` -- the backend-parity invariants (append, CAS, idempotency, read, snapshots, blobs) across memory, jsonl, sqlite and dynamodb fakes.
- `tests/simorgh/ledger/test_head_never_regresses.py` -- the head never goes backwards in any backend, from any handed state.
- `tests/simorgh/ledger/test_a_corrupt_line_is_a_gap_not_an_ending.py` -- a bad line never hides, deletes or renumbers the rest.
- `tests/simorgh/ledger/test_compaction.py` -- `DEFAULT_RETENTION`, duration parsing, longest-prefix rule, per-id vs singleton handling, protected prefix.
- `tests/simorgh/ledger/test_streams.py` -- the stream-name grammar and filename escaping.
- `tests/simorgh/ledger/test_blobs.py` -- ref grammar, content addressing, digest check on read.
- `tests/simorgh/ledger/test_config_and_factory.py` -- `[ledger]` keys, env overrides, backend selection, the fallback rule.
- `tests/simorgh/ledger/test_service.py` -- the sleep tick runs compaction and publishes metrics; the start pass; health states.

## Known issues (2026-09-18 evaluation)

- B1 (high): the blob sweep read every stream file on the event loop. Fixed 2026-09-18, commit `aa05475` (stage 0 item 24): `to_thread`. The "skip when nothing was removed" half of the recommendation is not done; the sweep still runs on every pass.
- B9 (low): the compaction record omitted `blobs_swept`. Fixed 2026-09-18, commit `aa05475`.
- B3 (high): retention only ever deleted trace streams; "forever" streams grow. Partly fixed 2026-09-18 (stage 0 item 6, commit `62318d3`: more prefixes in `DEFAULT_RETENTION`). Still open for forever streams without a snapshot, and see the per-id problem below.
- B19 (low): `metrics:history` had no retention. Fixed 2026-09-19: the 7d entry (item 6) takes effect since compaction decides by activity (commit `6ce1c78`).
- B7 (medium): the ledger is an untyped, unguarded second channel; one unbound client for everyone; stream names duplicated as strings. Open; stage 1 item 8.
- B8 (low): the `sqlite` and `dynamodb` backends and cross-process `tail` polling serve modes nothing selects. Open; stage 1 item 10 freezes dynamodb.
- B2 / W4 (medium / high): one file plus an idempotency sidecar per trace id makes the jsonl ledger mostly trace files. Open; stage 1 item 3 (the bus stops writing `trace:` streams).
- L4 (medium): ~20 fsync'd appends per tool call and read-back of the action stream. Open.

Found while writing this contract, fixed 2026-09-19 (commit `6ce1c78`): retention on a long-lived stream whose name contains `:` (`metrics:history`, `voice:turns`, `curiosity:ticks`, ...) did nothing while it was written, because compaction treated every such name as per-id and delete-only. Pinned in `tests/simorgh/ledger/test_retention_truncates_live_streams.py`.

Also not in the catalogue, fixed 2026-09-19: `Service.publish_health()` had no caller, so the declared `system.health` was never published by the ledger; the method was deleted and `system.health` dropped from `produces` (the Kernel publishes health for every supervised service). `run_compaction`'s synchronous `scandir` + `stat` of every stream file now runs on a worker thread (`JsonlBackend._streams_sync`). Still open: `read_snapshot` is a synchronous file read per forever stream on the event loop, the same stall shape as B1 at smaller cost.

## Planned changes (roadmap)

- Stage 1 item 3: `trace:` streams stop being written (spans go to the telemetry store); `metrics:history`, `curiosity:ticks`, `persona:state` become telemetry samples. Target: under 500 stream files per day.
- Stage 1 item 8: `LedgerClient` takes a `source`; a writer table in `contracts/streamnames.py` says which source may append to which prefix; a violation is refused.
- Stage 1 item 10: `backends/dynamodb.py` moves under `simorgh/_frozen/`; the protocol and the sqlite backend stay.
- Stage 4 item 2: `session:<id>` streams, one append per turn, a snapshot every 50 turns; retention on `session:` of 90d.
- Stage 9 item 5: `[ledger] backend = "sqlite"` becomes the default after its own eval, with a JSONL export/import migration; JSONL stays available.

## Working on this module

Lock it first (`python tools/modlock.py claim ledger --by <you> --task "..."`), commit the lock, edit only `simorgh/ledger/`, `tests/simorgh/ledger/` and this file; a change to `simorgh/contracts/` needs the `contracts` lock and a note in every consumer's Consumes table. Run `python tools/modtest.py ledger` before committing; commit subject `ledger: <what changed>`.

- Writers (stage 1 item 8, 2026-09-19): `ledger.bound.BoundLedger(inner, source)` wraps the shared client per subsystem; `append`/`snapshot`/`compact`/`delete_stream` on a stream whose prefix is in `contracts.streamnames.WRITERS` raise `WriterViolation` unless the source (instance suffix stripped) is listed; reads pass through; unlisted streams are open. `SIMORGH_LEDGER_WRITER_AUDIT=<file>` records every write as `source<TAB>stream` (how the table was measured: 23,140 writes over the whole test tree). `streams.KNOWN_PREFIXES` stays informational.
