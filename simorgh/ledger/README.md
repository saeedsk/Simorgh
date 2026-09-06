# `simorgh.ledger`

The append-only event store every durable fact in Simorgh v2 is a
projection over. Spec: [`docs/blueprint/subsystems/02-ledger.md`](../../docs/blueprint/subsystems/02-ledger.md);
protocol: `simorgh.contracts.protocols.Ledger` (`03` §6). Imports only
`simorgh.contracts` and the standard library (enforced by
`tests/simorgh/test_module_boundaries.py`).

| Module | What |
|---|---|
| `client.py` | `LedgerClient` — the `Ledger` implementation subsystems use: validation, idempotency, CAS, `tail`, `rebuild`/`materialize`, blobs, `compact`, counters. **The only module other packages may import.** |
| `api.py` | `LedgerBackend` protocol, `Projection` base, error types; re-exports contracts' `Event` |
| `backends/memory.py` | tests / dry runs |
| `backends/jsonl.py` | default: one fsync'd JSONL file per stream, atomic rewrites, partial-line recovery, advisory lock; owns the v1 file format (`read_v1_records`) |
| `backends/sqlite.py` | WAL database, `BEGIN IMMEDIATE` writers, PK-based CAS — the multi-process engine |
| `backends/dynamodb.py` | optional; conditional-put CAS, S3 blobs; lazy `boto3`; tested via fakes |
| `projection.py` | snapshot + replay |
| `compaction.py` | retention policy and record compaction (not context compaction) |
| `blobs.py` | content-addressed `blob:<sha256>` store |
| `idempotency.py` | per-stream key → seq cache, rebuildable from the stream |
| `migrate_v1.py` | `read_v1_records()` + `route_v1()` for the Kernel's `migrate-v1` |
| `service.py` | the `Subsystem`: compaction on `system.tick.sleep`, `system.metrics`, `health()` |
| `factory.py`, `config.py` | `make_ledger(config)`, `[ledger]` settings + env overrides |

## Using it

```python
from simorgh.ledger.client import LedgerClient          # subsystems
from simorgh.contracts.envelope import Event

seq = await ledger.append("task:t1", Event.from_message(msg, "task:t1"), expected_seq=4)  # CAS
events = await ledger.read("task:t1", from_seq=5)
sub = await ledger.tail("task:", handler)                # every task stream, from now on
ref = await ledger.put_blob(big_bytes, content_type="text/plain")   # -> "blob:<sha256>"
head = await ledger.rebuild(my_projection, "task:t1")   # snapshot + replay
```

Config (`simorgh.toml`):

| Key | Default | Meaning |
|---|---|---|
| `backend` | `jsonl` | `memory` / `jsonl` / `sqlite` / `dynamodb` (`SIMORGH_LEDGER_BACKEND` overrides) |
| `data_dir` | `~/.simorgh/ledger` | files for `jsonl`/`sqlite`; blobs under it (`SIMORGH_LEDGER_DIR` overrides) |
| `fsync` | `true` | fsync every `jsonl` append |
| `snapshot_every` | `200` | default `Projection` cadence |
| `blob_inline_threshold` | `4096` | strings longer than this must be `blob:` refs |
| `tail_poll_ms` | `100` | poll interval for cross-process tails |
| `retention.<prefix>` | `trace: 7d`, `dead: 30d`, `activity 90d`, else forever | record retention per stream prefix |
| `retention.keep_tail` | `50` | events kept below a snapshot |
| `allow_fallback` | `false` | fall back to `jsonl` if the configured backend's dependency is missing |
| `dynamodb.table`, `dynamodb.bucket` | — | required for `dynamodb` |

## Tests

`python3 -m unittest tests.simorgh.ledger` — invariants are parametrized
over `memory`, `jsonl`, `sqlite`; `dynamodb` runs against in-memory
fakes of its adapter protocols (no credentials, no network).

## Build log

- 2026-09-06 — Phase 0: built to the spec. Doc fixes noted in
  `00-README.md`'s changelog: `Event` is contracts' (no separate `id`
  field; identity is `idempotency_key`), blob refs are `blob:<sha256>`
  per `03`, engines live under `backends/`, and the advisory file lock
  is taken per append (spec §5.4) rather than for the backend's lifetime
  (§5.5 said both).

## Open questions

See spec §12. Defaults taken: no `trace_max_bytes` cap yet (retention
only); no Windows lock shim (the lock is a no-op without `fcntl`; use
`sqlite` for multi-process there).
