"""The telemetry tables: one SQLite file, WAL mode, two tables.

    spans(trace_id, span_id, parent_id, name, start, "end", status, attrs_json)
    samples(series, ts, value_json)

Synchronous and thread-safe (one connection behind one lock): the
service calls every method through `asyncio.to_thread`, so nothing here
ever runs on the event loop. `synchronous=NORMAL` under WAL means a
commit is not fsynced -- a power cut can lose the last batch, never
corrupt the file -- which is the trade telemetry wants and the decision
log does not.

`end` is an SQL keyword, so the column is quoted everywhere; readers get
it back as the dict key `end`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS spans(
  trace_id TEXT NOT NULL, span_id TEXT NOT NULL, parent_id TEXT, name TEXT NOT NULL,
  start REAL NOT NULL, "end" REAL NOT NULL, status TEXT NOT NULL, attrs_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS spans_trace ON spans(trace_id);
CREATE INDEX IF NOT EXISTS spans_start ON spans(start);
CREATE TABLE IF NOT EXISTS samples(series TEXT NOT NULL, ts REAL NOT NULL, value_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS samples_series_ts ON samples(series, ts);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
"""

SpanRow = tuple[str, str, "str | None", str, float, float, str, str]
SampleRow = tuple[str, float, str]


def encode(value: Any) -> str:
    """JSON for a column. Anything `json` cannot encode is stored as its
    `repr` string: telemetry never raises into the code it measures."""
    try:
        return json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False, default=repr)
    except (TypeError, ValueError):
        return json.dumps(repr(value))


class TelemetryStore:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = Path(path)
        self._busy_timeout_ms = busy_timeout_ms
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------- lifecycle
    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(f"PRAGMA busy_timeout={int(self._busy_timeout_ms)}")
            conn.executescript(SCHEMA)
            self._conn = conn

    def close(self) -> None:
        with self._lock:
            conn, self._conn = self._conn, None
            if conn is not None:
                conn.close()

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    def _require(self) -> sqlite3.Connection:
        if self._conn is None:
            raise sqlite3.ProgrammingError(f"telemetry store {self.path} is not open")
        return self._conn

    # ----------------------------------------------------------------- writes
    def write(self, spans: Iterable[SpanRow], samples: Iterable[SampleRow]) -> None:
        """One transaction for the whole batch."""
        spans, samples = list(spans), list(samples)
        if not spans and not samples:
            return
        with self._lock:
            conn = self._require()
            conn.execute("BEGIN")
            try:
                if spans:
                    conn.executemany(
                        'INSERT INTO spans(trace_id, span_id, parent_id, name, start, "end", status, attrs_json)'
                        " VALUES (?,?,?,?,?,?,?,?)", spans)
                if samples:
                    conn.executemany("INSERT INTO samples(series, ts, value_json) VALUES (?,?,?)", samples)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ reads
    def spans(self, trace_id: str) -> list[dict]:
        with self._lock:
            rows = self._require().execute(
                'SELECT trace_id, span_id, parent_id, name, start, "end", status, attrs_json'
                " FROM spans WHERE trace_id=? ORDER BY start, rowid", (trace_id,)).fetchall()
        out = [{"trace_id": r[0], "span_id": r[1], "parent_id": r[2], "name": r[3], "start": r[4],
                "end": r[5], "status": r[6], "attrs": json.loads(r[7])} for r in rows]
        # A span's row is written when it ends, so a child precedes its
        # parent in insertion order; on an equal start (a coarse or fake
        # clock) put the parent first. Stable, so siblings keep theirs.
        parents = {row["span_id"]: row["parent_id"] for row in out}

        def depth(span_id: str) -> int:
            seen, n = {span_id}, 0
            while (span_id := parents.get(span_id)) in parents and span_id not in seen:  # type: ignore[assignment]
                seen.add(span_id)
                n += 1
            return n

        out.sort(key=lambda row: (row["start"], depth(row["span_id"])))
        return out

    def samples(self, series: str, *, since: float | None = None, until: float | None = None) -> list[dict]:
        sql, args = "SELECT ts, value_json FROM samples WHERE series=?", [series]
        if since is not None:
            sql, args = sql + " AND ts>=?", args + [since]
        if until is not None:
            sql, args = sql + " AND ts<?", args + [until]
        with self._lock:
            rows = self._require().execute(sql + " ORDER BY ts, rowid", args).fetchall()
        return [{"series": series, "ts": r[0], "value": json.loads(r[1])} for r in rows]

    def counts(self) -> dict[str, int]:
        with self._lock:
            conn = self._require()
            return {"spans": conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0],
                    "samples": conn.execute("SELECT COUNT(*) FROM samples").fetchone()[0]}

    # -------------------------------------------------------------- retention
    def prune(self, older_than_ts: float, *, spans: bool = False) -> dict[str, int]:
        """Delete samples older than `older_than_ts` in one transaction
        (and spans too when `spans` is True). Returns the rows removed."""
        with self._lock:
            conn = self._require()
            conn.execute("BEGIN")
            try:
                samples = conn.execute("DELETE FROM samples WHERE ts < ?", (older_than_ts,)).rowcount
                deleted_spans = 0
                if spans:
                    deleted_spans = conn.execute("DELETE FROM spans WHERE start < ?", (older_than_ts,)).rowcount
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return {"samples": samples, "spans": deleted_spans}

    def retain(self, *, now: float, span_max_age_s: float, sample_max_age_s: float,
               downsample_after_s: float, bucket_s: float) -> dict[str, int]:
        """Delete spans that started more than `span_max_age_s` ago and
        samples older than `sample_max_age_s`; then, among samples older
        than `downsample_after_s`, keep only the last-written row of each
        `(series, bucket)`. Returns the rows each step removed."""
        span_cutoff = now - span_max_age_s
        sample_cutoff = now - sample_max_age_s
        thin_cutoff = now - downsample_after_s
        with self._lock:
            conn = self._require()
            conn.execute("BEGIN")
            try:
                spans = conn.execute("DELETE FROM spans WHERE start < ?", (span_cutoff,)).rowcount
                samples = conn.execute("DELETE FROM samples WHERE ts < ?", (sample_cutoff,)).rowcount
                thinned = conn.execute(
                    "DELETE FROM samples WHERE ts < :cut AND rowid NOT IN ("
                    " SELECT MAX(rowid) FROM samples WHERE ts < :cut"
                    " GROUP BY series, CAST(ts / :bucket AS INTEGER))",
                    {"cut": thin_cutoff, "bucket": float(bucket_s)}).rowcount
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return {"spans": spans, "samples": samples, "downsampled": thinned}


__all__ = ["SCHEMA", "SampleRow", "SpanRow", "TelemetryStore", "encode"]


def read_trace(path: str | Path, trace_id: str) -> list[dict]:
    """Every span of `trace_id` from a telemetry file, opened read-only so a
    reader (`simorgh trace`) never writes beside a running instance. Empty
    when the file does not exist."""
    path = Path(path)
    if not path.exists():
        return []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    try:
        rows = conn.execute(
            'SELECT trace_id, span_id, parent_id, name, start, "end", status, attrs_json'
            " FROM spans WHERE trace_id=? ORDER BY start, rowid", (trace_id,)).fetchall()
    finally:
        conn.close()
    out = []
    for trace, span, parent, name, start, end, status, attrs in rows:
        try:
            decoded = json.loads(attrs) if attrs else {}
        except ValueError:
            decoded = {"raw": attrs}
        out.append({"trace_id": trace, "span_id": span, "parent_id": parent, "name": name, "start": start,
                    "end": end, "status": status, "attrs": decoded})
    return out


def last_sample(path: str | Path, series: str) -> dict | None:
    """The newest sample of `series`, read-only (`simorgh status`); None
    when the file or the series is absent."""
    path = Path(path)
    if not path.exists():
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
    try:
        row = conn.execute("SELECT ts, value_json FROM samples WHERE series=? ORDER BY ts DESC, rowid DESC LIMIT 1",
                           (series,)).fetchone()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return None if row is None else {"ts": row[0], "value": json.loads(row[1])}
