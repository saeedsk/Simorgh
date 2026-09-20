"""JSONL <-> SQLite, both ways, at the level of the files (stage 9 item 5).

The two backends store the same things -- events with a per-stream seq,
idempotency keys, heads that never go backwards, content-addressed
blobs -- in two layouts. This moves a ledger between them without
going through `append`, because `append` assigns `seq = head + 1` and a
stream with a gap (a corrupt line is a gap, not an ending) would be
silently renumbered. Renumbering is the one thing the ledger contract
forbids, so every event keeps the seq it had.

Snapshots are not migrated. They are caches of projections that any
reader rebuilds from the events; carrying them across would only give
a stale cache a longer life.

`ensure_migrated` is the reason the default could flip to SQLite at
all: the live `simorgh.toml` has no `[ledger]` section, so a new default
would have booted Sim against an EMPTY database and it would have
forgotten everything it knew. When the backend is SQLite, the database
does not exist yet and a JSONL ledger does, the JSONL ledger is imported
first, once, and left in place.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from simorgh.contracts.envelope import Event, canonical_json
from simorgh.ledger.blobs import sha256_hex
from simorgh.ledger.streams import escape, unescape

#: Where the SQLite ledger lives under a ledger data dir (`factory.make_backend`).
SQLITE_NAME = "ledger.sqlite3"


@dataclass
class Report:
    direction: str
    streams: int = 0
    events: int = 0
    blobs: int = 0
    heads_carried: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict:
        return {"direction": self.direction, "streams": self.streams, "events": self.events,
                "blobs": self.blobs, "heads_carried": self.heads_carried, "problems": list(self.problems)}


# ----------------------------------------------------------------- JSONL side

def _jsonl_streams(root: Path) -> list[str]:
    streams_dir = root / "streams"
    if not streams_dir.is_dir():
        return []
    return sorted(unescape(p.stem) for p in streams_dir.glob("*.jsonl"))


def _jsonl_events(root: Path, stream: str, problems: list[str]):
    path = root / "streams" / f"{escape(stream)}.jsonl"
    try:
        raw = path.read_bytes()
    except OSError as exc:
        problems.append(f"{stream}: unreadable ({exc})")
        return
    for lineno, line in enumerate(raw.split(b"\n"), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            # A corrupt line is a gap, not an ending -- and not a
            # problem to report either: the JSONL backend already
            # treats it exactly this way.
            continue
        if not isinstance(row, dict) or not row.get("seq"):
            continue
        yield row


def _jsonl_head(root: Path, stream: str, last_seq: int) -> int:
    """The head is the mark file when the file can no longer prove it,
    else the last seq; the mark only ever goes up, so take the max."""
    try:
        mark = int((root / "heads" / f"{escape(stream)}.head").read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        mark = 0
    return max(mark, last_seq)


def _jsonl_blobs(root: Path):
    blobs = root / "blobs"
    if not blobs.is_dir():
        return
    for path in sorted(blobs.glob("*/*")):
        if path.suffix in (".meta", ".tmp") or not path.is_file():
            continue
        data = path.read_bytes()
        if sha256_hex(data) != path.name:
            continue        # a ref is a promise; a blob that broke it is left behind, not carried
        content_type = "application/octet-stream"
        meta = path.with_name(path.name + ".meta")
        try:
            content_type = str(json.loads(meta.read_text(encoding="utf-8")).get("content_type") or content_type)
        except (OSError, ValueError):
            pass
        yield path.name, content_type, data


# ---------------------------------------------------------------- SQLite side

def _open(db: Path) -> sqlite3.Connection:
    from simorgh.ledger.backends.sqlite import _SCHEMA

    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def jsonl_to_sqlite(root: Path, db: Path) -> Report:
    """Import a JSONL ledger into a SQLite one. Idempotent: an event
    already there (same stream and seq) is left alone."""
    root, db = Path(root), Path(db)
    report = Report(direction="jsonl->sqlite")
    conn = _open(db)
    try:
        for stream in _jsonl_streams(root):
            report.streams += 1
            last = 0
            conn.execute("BEGIN")
            for row in _jsonl_events(root, stream, report.problems):
                seq = int(row["seq"])
                last = max(last, seq)
                conn.execute(
                    "INSERT OR IGNORE INTO events(stream, seq, type, ts, trace_id, causation_id, idempotency_key, payload)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (stream, seq, str(row.get("type") or ""), float(row.get("ts") or 0.0), row.get("trace_id"),
                     row.get("causation_id"), row.get("idempotency_key"), canonical_json(row.get("payload") or {})))
                if row.get("idempotency_key"):
                    conn.execute("INSERT OR IGNORE INTO idempotency(stream, key, seq) VALUES (?,?,?)",
                                 (stream, row["idempotency_key"], seq))
                report.events += 1
            head = _jsonl_head(root, stream, last)
            if head:
                conn.execute("INSERT INTO heads(stream, seq) VALUES (?,?) "
                             "ON CONFLICT(stream) DO UPDATE SET seq=MAX(heads.seq, excluded.seq)", (stream, head))
                report.heads_carried += 1
            conn.execute("COMMIT")
        conn.execute("BEGIN")
        for digest, content_type, data in _jsonl_blobs(root):
            conn.execute("INSERT OR IGNORE INTO blobs(sha256, content_type, size, data) VALUES (?,?,?,?)",
                         (digest, content_type, len(data), data))
            report.blobs += 1
        conn.execute("COMMIT")
    finally:
        conn.close()
    return report


def sqlite_to_jsonl(db: Path, root: Path) -> Report:
    """Export a SQLite ledger to the JSONL layout, seqs preserved. Writes
    each stream file whole; an existing file for the same stream is
    replaced, because two half-truths are worse than one."""
    root, db = Path(root), Path(db)
    report = Report(direction="sqlite->jsonl")
    if not db.exists():
        report.problems.append(f"{db}: no such database")
        return report
    conn = sqlite3.connect(str(db))
    try:
        (root / "streams").mkdir(parents=True, exist_ok=True)
        (root / "heads").mkdir(exist_ok=True)
        (root / "idem").mkdir(exist_ok=True)
        streams = [r[0] for r in conn.execute("SELECT DISTINCT stream FROM events UNION SELECT stream FROM heads ORDER BY 1")]
        for stream in streams:
            report.streams += 1
            lines, idem, last = [], [], 0
            for seq, type_, ts, trace_id, causation_id, key, payload in conn.execute(
                    "SELECT seq, type, ts, trace_id, causation_id, idempotency_key, payload FROM events"
                    " WHERE stream=? ORDER BY seq", (stream,)):
                row = {"stream": stream, "type": type_, "ts": ts, "trace_id": trace_id, "causation_id": causation_id,
                       "payload": json.loads(payload), "seq": seq, "idempotency_key": key}
                lines.append(canonical_json(row) + "\n")
                if key:
                    idem.append(f"{key}\t{seq}\n")
                last = seq
                report.events += 1
            (root / "streams" / f"{escape(stream)}.jsonl").write_text("".join(lines), encoding="utf-8")
            if idem:
                (root / "idem" / f"{escape(stream)}.idx").write_text("".join(idem), encoding="utf-8")
            head_row = conn.execute("SELECT seq FROM heads WHERE stream=?", (stream,)).fetchone()
            head = max(last, int(head_row[0]) if head_row else 0)
            if head > last:
                # The file cannot prove this head; the mark carries it.
                (root / "heads" / f"{escape(stream)}.head").write_text(f"{head}\n", encoding="utf-8")
                report.heads_carried += 1
        for digest, content_type, size, data in conn.execute("SELECT sha256, content_type, size, data FROM blobs"):
            path = root / "blobs" / digest[:2] / digest
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.with_name(path.name + ".meta").write_text(
                json.dumps({"content_type": content_type, "size": size}), encoding="utf-8")
            report.blobs += 1
    finally:
        conn.close()
    return report


# --------------------------------------------------------------- the safety net

def ensure_migrated(data_dir: Path) -> Report | None:
    """Import a JSONL ledger into SQLite once, if SQLite is about to be
    opened where only JSONL exists. Returns the report, or None when
    there was nothing to do. The JSONL files are left where they are."""
    data_dir = Path(data_dir)
    db = data_dir / SQLITE_NAME
    if db.exists() or not _jsonl_streams(data_dir):
        return None
    return jsonl_to_sqlite(data_dir, db)


def compare(root: Path, db: Path) -> list[str]:
    """Per-stream head and event count, both sides; the differences."""
    root, db = Path(root), Path(db)
    conn = sqlite3.connect(str(db))
    try:
        sq = {s: (int(n), int(h)) for s, n, h in conn.execute(
            "SELECT e.stream, COUNT(*), COALESCE(MAX(h.seq), MAX(e.seq)) FROM events e"
            " LEFT JOIN heads h ON h.stream=e.stream GROUP BY e.stream")}
    finally:
        conn.close()
    out: list[str] = []
    for stream in _jsonl_streams(root):
        rows = list(_jsonl_events(root, stream, []))
        n = len(rows)
        head = _jsonl_head(root, stream, max((int(r["seq"]) for r in rows), default=0))
        got = sq.get(stream)
        if n == 0 and got is None:
            continue
        if got != (n, head):
            out.append(f"{stream}: jsonl has {n} events, head {head}; sqlite has {got}")
    return out


__all__ = ["Report", "SQLITE_NAME", "compare", "ensure_migrated", "jsonl_to_sqlite", "sqlite_to_jsonl"]
