"""The default backend: one append-only JSONL file per stream, fsync'd
per append, with v1's own durability discipline carried over verbatim
from `src/memory/long_term.py` -- a crash loses at most the record that
was mid-write, and a rewrite (truncation) goes tmp -> fsync ->
`os.replace` so the file is always old-or-new, never partial.

On-disk layout (02-ledger section 4.2):

    <root>/streams/<escaped>.jsonl   one canonical-JSON Event per line
    <root>/snapshots/<escaped>.json  {"at_seq", "state", "ts"}
    <root>/idem/<escaped>.idx        "key\tseq" lines (a cache; rebuilt if stale)
    <root>/blobs/<aa>/<sha256>       content-addressed, with .meta sidecars
    <root>/index.json                {stream: {head, bytes, last_ts}} for humans
    <root>/LOCK                      advisory lock taken around each append

Multi-process: an advisory `fcntl` lock is held around each append (not
for the backend's lifetime), so several processes on one host can share
a directory; `sqlite` is still the recommended backend for that mode.
`read_v1_records` is re-exported here because this backend owns the v1
file format.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from simorgh.contracts.envelope import Event, canonical_json

from ..api import ConflictError, LedgerUnavailable
from ..blobs import LocalBlobStore
from ..idempotency import IdempotencyIndex
from ..migrate_v1 import read_v1_records, route_v1
from ..streams import escape, unescape, validate_stream

try:  # POSIX advisory locks; on platforms without fcntl the lock is a no-op
    import fcntl
except ImportError:  # pragma: no cover - platform-dependent
    fcntl = None  # type: ignore[assignment]


class _StreamMeta:
    __slots__ = ("head", "bytes", "last_ts")

    def __init__(self, head: int = 0, size: int = 0, last_ts: float | None = None) -> None:
        self.head, self.bytes, self.last_ts = head, size, last_ts

    def as_dict(self) -> dict:
        return {"head": self.head, "bytes": self.bytes, "last_ts": self.last_ts}


class JsonlBackend:
    cross_process = True  # other processes may append under the file lock

    def __init__(self, root: str | Path, *, fsync: bool = True) -> None:
        self.root = Path(root)
        self._fsync = fsync
        self._meta: dict[str, _StreamMeta] = {}
        self._idem = IdempotencyIndex()
        self._locks: dict[str, asyncio.Lock] = {}
        self._blobs = LocalBlobStore(self.root / "blobs", fsync=fsync)
        self.recovered: list[str] = []  # streams whose trailing partial line was truncated on start
        self._started = False

    # ------------------------------------------------------------------ paths
    def _stream_path(self, stream: str) -> Path:
        return self.root / "streams" / f"{escape(stream)}.jsonl"

    def _snapshot_path(self, stream: str) -> Path:
        return self.root / "snapshots" / f"{escape(stream)}.json"

    def _idem_path(self, stream: str) -> Path:
        return self.root / "idem" / f"{escape(stream)}.idx"

    def _lock_for(self, stream: str) -> asyncio.Lock:
        return self._locks.setdefault(stream, asyncio.Lock())

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        try:
            for sub in ("streams", "snapshots", "idem", "blobs"):
                (self.root / sub).mkdir(parents=True, exist_ok=True)
            (self.root / "LOCK").touch(exist_ok=True)
        except OSError as exc:
            raise LedgerUnavailable(f"ledger dir {self.root} is not writable: {exc}") from None
        self._meta.clear()
        self.recovered.clear()
        for path in sorted((self.root / "streams").glob("*.jsonl")):
            stream = unescape(path.stem)
            self._scan_stream(stream, path)
        self._write_index()
        self._started = True

    async def stop(self) -> None:
        self._write_index()
        self._started = False

    def _scan_stream(self, stream: str, path: Path) -> None:
        """Rebuild head/bytes/last_ts and the idempotency cache from the
        file itself, truncating a trailing partial line (a crash
        mid-write) rather than failing on it."""
        head = 0
        last_ts: float | None = None
        good_end = 0
        events: list[Event] = []
        with open(path, "rb") as fh:
            data = fh.read()
        pos = 0
        while pos < len(data):
            nl = data.find(b"\n", pos)
            if nl == -1:
                break  # trailing partial line
            line = data[pos:nl]
            try:
                event = Event.from_dict(json.loads(line.decode("utf-8")))
            except Exception:  # noqa: BLE001 -- any unparseable line ends the good region
                break
            events.append(event)
            head = max(head, event.seq)
            last_ts = event.ts
            good_end = nl + 1
            pos = nl + 1
        if good_end != len(data):
            self._truncate_file(path, good_end)
            self.recovered.append(stream)
        self._meta[stream] = _StreamMeta(head, good_end, last_ts)
        self._idem.rebuild(stream, events)

    @staticmethod
    def _truncate_file(path: Path, size: int) -> None:
        with open(path, "r+b") as fh:
            fh.truncate(size)
            fh.flush()
            os.fsync(fh.fileno())

    def _write_index(self) -> None:
        try:
            tmp = self.root / "index.json.tmp"
            tmp.write_text(
                json.dumps({s: m.as_dict() for s, m in sorted(self._meta.items())}, indent=1),
                encoding="utf-8",
            )
            os.replace(tmp, self.root / "index.json")
        except OSError:
            pass  # the index is for humans; the files are the truth

    # ------------------------------------------------------------------- core
    async def head(self, stream: str) -> int:
        meta = self._meta.get(stream)
        if meta is None:
            path = self._stream_path(stream)
            if path.exists():  # appended by another process since start
                self._scan_stream(stream, path)
                meta = self._meta.get(stream)
        return meta.head if meta else 0

    def _refresh_if_grown(self, stream: str) -> None:
        """Another process may have appended: if the file is longer than
        we last saw, rescan (cheap for per-id streams)."""
        path = self._stream_path(stream)
        meta = self._meta.get(stream)
        if path.exists():
            size = path.stat().st_size
            if meta is None or size != meta.bytes:
                self._scan_stream(stream, path)

    async def append(self, event: Event, *, expected_seq: int | None) -> int:
        validate_stream(event.stream)
        path = self._stream_path(event.stream)
        async with self._lock_for(event.stream):
            with self._file_lock():
                self._refresh_if_grown(event.stream)
                meta = self._meta.setdefault(event.stream, _StreamMeta())
                if expected_seq is not None and expected_seq != meta.head:
                    raise ConflictError(event.stream, expected_seq, meta.head)
                stored = Event(**{**event.to_dict(), "seq": meta.head + 1})
                line = (canonical_json(stored.to_dict()) + "\n").encode("utf-8")
                try:
                    with open(path, "ab") as fh:
                        fh.write(line)
                        fh.flush()
                        if self._fsync:
                            os.fsync(fh.fileno())
                except OSError as exc:
                    raise LedgerUnavailable(f"append to {event.stream} failed: {exc}") from None
                meta.head = stored.seq
                meta.bytes += len(line)
                meta.last_ts = stored.ts
                self._idem.record(event.stream, stored.idempotency_key, stored.seq)
                self._append_idem_line(event.stream, stored.idempotency_key, stored.seq)
        return stored.seq

    def _file_lock(self):
        return _FileLock(self.root / "LOCK")

    def _append_idem_line(self, stream: str, key: str | None, seq: int) -> None:
        if not key:
            return
        try:
            with open(self._idem_path(stream), "a", encoding="utf-8") as fh:
                fh.write(f"{key}\t{seq}\n")
        except OSError:
            pass  # a cache; rebuilt from the stream on next start

    async def find_by_idempotency(self, stream: str, key: str) -> int | None:
        self._refresh_if_grown(stream)
        return self._idem.get(stream, key)

    async def read(self, stream: str, *, from_seq: int, limit: int | None) -> list[Event]:
        path = self._stream_path(stream)
        if not path.exists():
            return []
        out: list[Event] = []
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.endswith("\n"):
                    break  # partial trailing line: not yet durable
                try:
                    event = Event.from_dict(json.loads(line))
                except Exception:  # noqa: BLE001
                    break
                if event.seq >= from_seq:
                    out.append(event)
                    if limit is not None and len(out) >= limit:
                        break
        return out

    async def streams(self, prefix: str) -> list[str]:
        names = [unescape(p.stem) for p in (self.root / "streams").glob("*.jsonl")]
        return sorted(n for n in names if n.startswith(prefix) and self._stream_path(n).stat().st_size > 0)

    # -------------------------------------------------------------- snapshots
    async def write_snapshot(self, stream: str, state: dict, at_seq: int) -> None:
        path = self._snapshot_path(stream)
        self._atomic_write(path, json.dumps({"at_seq": at_seq, "state": state, "ts": time.time()}).encode("utf-8"))

    async def read_snapshot(self, stream: str) -> tuple[dict, int] | None:
        path = self._snapshot_path(stream)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return dict(data["state"]), int(data["at_seq"])
        except (OSError, ValueError, KeyError, TypeError):
            return None  # corrupt snapshot: caller replays from seq 1

    async def delete_snapshot(self, stream: str) -> None:
        path = self._snapshot_path(stream)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------- compaction
    async def truncate_below(self, stream: str, seq: int) -> int:
        """Rewrite the stream keeping only events with `seq >= seq`,
        atomically (tmp -> fsync -> replace), exactly v1's `_rewrite`."""
        async with self._lock_for(stream):
            with self._file_lock():
                self._refresh_if_grown(stream)
                events = await self.read(stream, from_seq=0, limit=None)
                kept = [e for e in events if e.seq >= seq]
                removed = len(events) - len(kept)
                if removed == 0:
                    return 0
                body = b"".join((canonical_json(e.to_dict()) + "\n").encode("utf-8") for e in kept)
                self._atomic_write(self._stream_path(stream), body)
                meta = self._meta.setdefault(stream, _StreamMeta())
                meta.bytes = len(body)
                meta.head = kept[-1].seq if kept else meta.head  # head never regresses
                meta.last_ts = kept[-1].ts if kept else meta.last_ts
                self._idem.forget_below(stream, seq)
                idem_lines = "".join(f"{k}\t{s}\n" for k, s in self._idem.items(stream))
                self._atomic_write(self._idem_path(stream), idem_lines.encode("utf-8"))
        return removed

    async def delete_stream(self, stream: str) -> None:
        async with self._lock_for(stream):
            with self._file_lock():
                for path in (self._stream_path(stream), self._snapshot_path(stream), self._idem_path(stream)):
                    if path.exists():
                        path.unlink()
                self._meta.pop(stream, None)
                self._idem.forget_stream(stream)

    def _atomic_write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
                fh.flush()
                if self._fsync:
                    os.fsync(fh.fileno())
            os.replace(tmp, path)
        except OSError as exc:
            raise LedgerUnavailable(f"rewrite of {path.name} failed: {exc}") from None

    # ------------------------------------------------------------------ blobs
    async def put_blob(self, data: bytes, *, content_type: str) -> str:
        try:
            return self._blobs.put(data, content_type=content_type)
        except OSError as exc:
            raise LedgerUnavailable(f"blob write failed: {exc}") from None

    async def get_blob(self, ref: str) -> bytes:
        return self._blobs.get(ref)

    # ------------------------------------------------------------------ stats
    async def stat(self) -> dict:
        by_prefix: dict[str, int] = {}
        for stream, meta in self._meta.items():
            head, sep, _ = stream.partition(":")
            by_prefix[head + sep] = by_prefix.get(head + sep, 0) + meta.bytes
        free_fraction = None
        try:
            usage = shutil.disk_usage(self.root)
            free_fraction = usage.free / usage.total if usage.total else None
        except OSError:
            pass
        return {
            "streams": sum(1 for m in self._meta.values() if m.bytes),
            "events": sum(m.head for m in self._meta.values()),
            "snapshots": len(list((self.root / "snapshots").glob("*.json"))) if (self.root / "snapshots").exists() else 0,
            "bytes_total": sum(m.bytes for m in self._meta.values()),
            "bytes_by_prefix": by_prefix,
            "free_fraction": free_fraction,
            **self._blobs.stat(),
        }

    async def last_ts(self, stream: str) -> float | None:
        self._refresh_if_grown(stream)
        meta = self._meta.get(stream)
        return meta.last_ts if meta else None


class _FileLock:
    """Advisory, process-wide, held only around one append/rewrite."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fh = None

    def __enter__(self) -> "_FileLock":
        if fcntl is not None:
            self._fh = open(self._path, "a+")
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


__all__ = ["JsonlBackend", "read_v1_records", "route_v1"]
