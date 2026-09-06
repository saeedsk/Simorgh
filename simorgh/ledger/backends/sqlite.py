"""SQLite backend (02-ledger section 4.3): one WAL-mode database, the
recommended engine for `local-multi` mode -- several processes on one
host append through `BEGIN IMMEDIATE`, which serializes writers with a
busy timeout instead of an advisory file lock, and the `(stream, seq)`
primary key makes compare-and-swap a plain INSERT: a duplicate key is a
lost race, mapped to `ConflictError`.

All SQLite calls run in a worker thread (`asyncio.to_thread`) behind one
lock, so the event loop is never blocked (05 section 2) and the single
connection is never used concurrently.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

from simorgh.contracts.envelope import Event, canonical_json

from ..api import BlobNotFound, ConflictError, LedgerUnavailable
from ..blobs import parse_ref, sha256_hex
from ..streams import validate_stream

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  stream TEXT NOT NULL, seq INTEGER NOT NULL, type TEXT NOT NULL, ts REAL NOT NULL,
  trace_id TEXT, causation_id TEXT, idempotency_key TEXT, payload TEXT NOT NULL,
  PRIMARY KEY(stream, seq));
CREATE TABLE IF NOT EXISTS idempotency(stream TEXT NOT NULL, key TEXT NOT NULL, seq INTEGER NOT NULL,
  PRIMARY KEY(stream, key));
CREATE TABLE IF NOT EXISTS snapshots(stream TEXT PRIMARY KEY, at_seq INTEGER NOT NULL, state TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS blobs(sha256 TEXT PRIMARY KEY, content_type TEXT NOT NULL, size INTEGER NOT NULL, data BLOB NOT NULL);
"""


class SqliteBackend:
    cross_process = True

    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self._busy_timeout_ms = busy_timeout_ms
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        def open_db() -> None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(f"PRAGMA busy_timeout={int(self._busy_timeout_ms)}")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_SCHEMA)
            self._conn = conn

        try:
            await asyncio.to_thread(open_db)
        except sqlite3.Error as exc:
            raise LedgerUnavailable(f"cannot open {self.path}: {exc}") from None

    async def stop(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            await asyncio.to_thread(conn.close)

    async def _run(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        if self._conn is None:
            raise LedgerUnavailable("sqlite backend not started")

        def locked() -> Any:
            with self._lock:
                try:
                    return fn(self._conn)  # type: ignore[arg-type]
                except sqlite3.OperationalError as exc:
                    raise LedgerUnavailable(str(exc)) from None

        return await asyncio.to_thread(locked)

    # ------------------------------------------------------------------- core
    @staticmethod
    def _head(conn: sqlite3.Connection, stream: str) -> int:
        row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events WHERE stream=?", (stream,)).fetchone()
        return int(row[0]) if row else 0

    async def head(self, stream: str) -> int:
        return await self._run(lambda c: self._head(c, stream))

    async def append(self, event: Event, *, expected_seq: int | None) -> int:
        validate_stream(event.stream)

        def op(conn: sqlite3.Connection) -> int:
            conn.execute("BEGIN IMMEDIATE")
            try:
                head = self._head(conn, event.stream)
                if expected_seq is not None and expected_seq != head:
                    raise ConflictError(event.stream, expected_seq, head)
                seq = head + 1
                try:
                    conn.execute(
                        "INSERT INTO events(stream, seq, type, ts, trace_id, causation_id, idempotency_key, payload)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (event.stream, seq, event.type, event.ts, event.trace_id, event.causation_id,
                         event.idempotency_key, canonical_json(event.payload)),
                    )
                except sqlite3.IntegrityError:
                    raise ConflictError(event.stream, expected_seq if expected_seq is not None else head, head)
                if event.idempotency_key:
                    conn.execute("INSERT OR IGNORE INTO idempotency(stream, key, seq) VALUES (?,?,?)",
                                 (event.stream, event.idempotency_key, seq))
                conn.execute("COMMIT")
                return seq
            except BaseException:
                conn.execute("ROLLBACK")
                raise

        return await self._run(op)

    async def find_by_idempotency(self, stream: str, key: str) -> int | None:
        def op(conn: sqlite3.Connection) -> int | None:
            row = conn.execute("SELECT seq FROM idempotency WHERE stream=? AND key=?", (stream, key)).fetchone()
            return int(row[0]) if row else None

        return await self._run(op)

    @staticmethod
    def _row_to_event(row: tuple) -> Event:
        stream, seq, type_, ts, trace_id, causation_id, idem, payload = row
        return Event(stream=stream, seq=seq, type=type_, ts=ts, trace_id=trace_id, causation_id=causation_id,
                     idempotency_key=idem, payload=json.loads(payload))

    async def read(self, stream: str, *, from_seq: int, limit: int | None) -> list[Event]:
        def op(conn: sqlite3.Connection) -> list[Event]:
            sql = ("SELECT stream, seq, type, ts, trace_id, causation_id, idempotency_key, payload FROM events"
                   " WHERE stream=? AND seq>=? ORDER BY seq")
            params: tuple = (stream, from_seq)
            if limit is not None:
                sql += " LIMIT ?"
                params += (limit,)
            return [self._row_to_event(r) for r in conn.execute(sql, params)]

        return await self._run(op)

    async def streams(self, prefix: str) -> list[str]:
        def op(conn: sqlite3.Connection) -> list[str]:
            rows = conn.execute("SELECT DISTINCT stream FROM events WHERE stream LIKE ? ORDER BY stream",
                                (prefix.replace("%", "\\%").replace("_", "\\_") + "%",)).fetchall()
            return [r[0] for r in rows if r[0].startswith(prefix)]

        return await self._run(op)

    # -------------------------------------------------------------- snapshots
    async def write_snapshot(self, stream: str, state: dict, at_seq: int) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute("INSERT OR REPLACE INTO snapshots(stream, at_seq, state, ts) VALUES (?,?,?,?)",
                         (stream, at_seq, json.dumps(state), time.time()))

        await self._run(op)

    async def read_snapshot(self, stream: str) -> tuple[dict, int] | None:
        def op(conn: sqlite3.Connection) -> tuple[dict, int] | None:
            row = conn.execute("SELECT state, at_seq FROM snapshots WHERE stream=?", (stream,)).fetchone()
            if not row:
                return None
            try:
                return dict(json.loads(row[0])), int(row[1])
            except (ValueError, TypeError):
                return None

        return await self._run(op)

    async def delete_snapshot(self, stream: str) -> None:
        await self._run(lambda c: c.execute("DELETE FROM snapshots WHERE stream=?", (stream,)))

    # ------------------------------------------------------------- compaction
    async def truncate_below(self, stream: str, seq: int) -> int:
        def op(conn: sqlite3.Connection) -> int:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute("DELETE FROM events WHERE stream=? AND seq<?", (stream, seq))
                conn.execute("DELETE FROM idempotency WHERE stream=? AND seq<?", (stream, seq))
                conn.execute("COMMIT")
                return cur.rowcount
            except BaseException:
                conn.execute("ROLLBACK")
                raise

        return await self._run(op)

    async def delete_stream(self, stream: str) -> None:
        def op(conn: sqlite3.Connection) -> None:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for table in ("events", "idempotency", "snapshots"):
                    conn.execute(f"DELETE FROM {table} WHERE stream=?", (stream,))
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

        await self._run(op)

    # ------------------------------------------------------------------ blobs
    async def put_blob(self, data: bytes, *, content_type: str) -> str:
        digest = sha256_hex(data)

        def op(conn: sqlite3.Connection) -> str:
            conn.execute("INSERT OR IGNORE INTO blobs(sha256, content_type, size, data) VALUES (?,?,?,?)",
                         (digest, content_type, len(data), sqlite3.Binary(data)))
            return f"blob:{digest}"

        return await self._run(op)

    async def get_blob(self, ref: str) -> bytes:
        digest = parse_ref(ref)

        def op(conn: sqlite3.Connection) -> bytes:
            row = conn.execute("SELECT data FROM blobs WHERE sha256=?", (digest,)).fetchone()
            if not row:
                raise BlobNotFound(ref)
            return bytes(row[0])

        return await self._run(op)

    # ------------------------------------------------------------------ stats
    async def stat(self) -> dict:
        def op(conn: sqlite3.Connection) -> dict:
            streams, events, payload_bytes = conn.execute(
                "SELECT COUNT(DISTINCT stream), COUNT(*), COALESCE(SUM(LENGTH(payload)),0) FROM events").fetchone()
            snapshots = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            blobs, blob_bytes = conn.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM blobs").fetchone()
            by_prefix: dict[str, int] = {}
            for stream, size in conn.execute("SELECT stream, SUM(LENGTH(payload)) FROM events GROUP BY stream"):
                head, sep, _ = stream.partition(":")
                by_prefix[head + sep] = by_prefix.get(head + sep, 0) + int(size)
            return {"streams": streams, "events": events, "snapshots": snapshots, "bytes_total": int(payload_bytes),
                    "bytes_by_prefix": by_prefix, "blobs": blobs, "blob_bytes": int(blob_bytes)}

        return await self._run(op)

    async def last_ts(self, stream: str) -> float | None:
        def op(conn: sqlite3.Connection) -> float | None:
            row = conn.execute("SELECT ts FROM events WHERE stream=? ORDER BY seq DESC LIMIT 1", (stream,)).fetchone()
            return float(row[0]) if row else None

        return await self._run(op)


__all__ = ["SqliteBackend"]
