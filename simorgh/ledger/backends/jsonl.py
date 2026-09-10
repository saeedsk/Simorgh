"""The default backend: one append-only JSONL file per stream, fsync'd
per append, with v1's own durability discipline carried over verbatim
from `src/memory/long_term.py` -- a crash loses at most the record that
was mid-write, and a rewrite (truncation) goes tmp -> fsync ->
`os.replace` so the file is always old-or-new, never partial.

On-disk layout (02-ledger section 4.2):

    <root>/streams/<escaped>.jsonl   one canonical-JSON Event per line
    <root>/snapshots/<escaped>.json  {"at_seq", "state", "ts"}
    <root>/idem/<escaped>.idx        "key\tseq" lines (a cache; rebuilt if stale)
    <root>/heads/<escaped>.head      the highest seq ever issued, written only
                                     when the file can no longer prove it --
                                     compaction removing events, or a scan
                                     finding the file shorter than the head we
                                     already knew; cleared by delete_stream
    <root>/blobs/<aa>/<sha256>       content-addressed, with .meta sidecars
    <root>/index.json                {stream: {head, bytes, last_ts}}; read at start
                                     so an unchanged stream is never re-read
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
import re
import shutil
import time
from collections import OrderedDict
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

# Matches a blob ref wherever it appears in a stream's raw JSON lines --
# scanning bytes directly (rather than parsing each event) is what makes
# a sweep over every stream affordable at the sizes retention already
# has to cope with (02-ledger's own trace-volume incident: 190k+ files).
_BLOB_REF_BYTES = re.compile(rb"blob:(?:sha256:)?([0-9a-f]{64})")


class _StreamMeta:
    __slots__ = ("head", "bytes", "last_ts")

    def __init__(self, head: int = 0, size: int = 0, last_ts: float | None = None) -> None:
        self.head, self.bytes, self.last_ts = head, size, last_ts

    def as_dict(self) -> dict:
        return {"head": self.head, "bytes": self.bytes, "last_ts": self.last_ts}


class JsonlBackend:
    cross_process = True  # other processes may append under the file lock
    #: How many per-stream `asyncio.Lock`s to keep. Comfortably more
    #: than any plausible number of concurrently-written streams, and a
    #: hard ceiling instead of one per stream ever seen.
    _MAX_LOCKS = 4096

    def __init__(self, root: str | Path, *, fsync: bool = True) -> None:
        self.root = Path(root)
        self._fsync = fsync
        self._meta: dict[str, _StreamMeta] = {}
        # stream -> (file size when built, {seq: byte offset}); see `read`.
        self._offsets: dict[str, tuple[int, dict[int, int]]] = {}
        self._idem = IdempotencyIndex()
        # Bounded, LRU, and only ever evicting an idle lock -- see
        # `_lock_for`. A plain dict here grew one Lock per stream ever
        # written, for the life of the process.
        self._locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()
        self._blobs = LocalBlobStore(self.root / "blobs", fsync=fsync)
        self.recovered: list[str] = []  # streams whose trailing partial line was truncated on start
        # stream -> how many DURABLE (newline-terminated) lines the last
        # full pass could not parse. A trailing partial line is not in
        # here: that is a crash mid-append, whose seq was never handed
        # out, and truncating it is the correct repair. An interior bad
        # line is different -- everything after it is real, acked data,
        # and `read`, `_scan_stream` and `truncate_below` used to treat
        # it as the end of the stream. See `_scan_stream`.
        self.corrupt: dict[str, int] = {}
        # Streams whose `.idx` cache has been read (or rebuilt by a scan).
        # Loading 191k of these at boot would just move the cost, so a
        # stream's keys are read the first time anything asks about them.
        self._idem_loaded: set[str] = set()
        self._index_dirty = False
        self.scanned_on_start = 0
        self.trusted_on_start = 0
        self._started = False

    # ------------------------------------------------------------------ paths
    def _stream_path(self, stream: str) -> Path:
        return self.root / "streams" / f"{escape(stream)}.jsonl"

    def _snapshot_path(self, stream: str) -> Path:
        return self.root / "snapshots" / f"{escape(stream)}.json"

    def _idem_path(self, stream: str) -> Path:
        return self.root / "idem" / f"{escape(stream)}.idx"

    def _head_path(self, stream: str) -> Path:
        """The durable high-water mark, written whenever the file can no
        longer prove the head: `truncate_below` removing events, or
        `_scan_stream` finding a file shorter than a head already handed
        out.

        Head is otherwise derived from the file, which is correct for
        every state except the ones that shorten it: a compaction pass
        that keeps nothing leaves a 0-byte file, and a rescan reads head
        0 out of it; a tail lost to a partial fsync or a bad copy reads
        a head lower than what `append` already returned to a caller.

        `index.json` is not that mark -- `_read_index` treats it as
        disposable by design (absent/truncated/old layout all mean "empty
        index"), and `_refresh_if_grown` rescans whenever another process
        changed the size. So the mark is its own tiny file, written only
        when the file itself can no longer answer for the head, and
        cleared only by `delete_stream`.
        """
        return self.root / "heads" / f"{escape(stream)}.head"

    def _read_mark(self, stream: str) -> int:
        try:
            return int(self._head_path(stream).read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            return 0

    def _write_mark(self, stream: str, seq: int) -> None:
        if seq <= self._read_mark(stream):
            return  # the mark only ever goes up
        try:
            self._atomic_write(self._head_path(stream), f"{seq}\n".encode("utf-8"))
        except LedgerUnavailable:
            pass  # best effort: the events themselves are still the truth

    def _lock_for(self, stream: str) -> asyncio.Lock:
        """The per-stream serializer, from a table bounded by `_MAX_LOCKS`.

        It used to be a plain dict that only ever grew: one `asyncio.Lock`
        for every stream this process had ever appended to, kept for the
        life of the process. Measured 2026-09-10: 20,000 one-event
        `trace:` streams left 20,000 locks behind, and 178 bytes each
        extrapolates to ~34 MB on the creator's own 192,456-stream
        ledger -- all of it for streams written once and never touched
        again. `_meta` has to hold every stream (it is the index); a
        mutex for a stream nobody is writing does not.

        Only an idle lock is evicted -- not locked, nobody waiting -- so
        eviction can never hand two writers of one stream two different
        locks. Nothing awaits between this call and the `async with`
        that takes the lock, so a lock handed out here cannot be evicted
        before it is acquired.
        """
        lock = self._locks.get(stream)
        if lock is not None:
            self._locks.move_to_end(stream)
            return lock
        while len(self._locks) >= self._MAX_LOCKS:
            victim = None
            for key, candidate in self._locks.items():  # least recently used first
                if not candidate.locked() and not candidate._waiters:  # noqa: SLF001
                    victim = key
                    break
            if victim is None:
                break  # every lock is in use: hold more rather than break one
            del self._locks[victim]
        lock = self._locks[stream] = asyncio.Lock()
        return lock

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        try:
            for sub in ("streams", "snapshots", "idem", "blobs", "heads"):
                (self.root / sub).mkdir(parents=True, exist_ok=True)
            (self.root / "LOCK").touch(exist_ok=True)
        except OSError as exc:
            raise LedgerUnavailable(f"ledger dir {self.root} is not writable: {exc}") from None
        self._meta.clear()
        self._idem_loaded.clear()
        self.recovered.clear()
        # Live-caught, 2026-09-07: booting took 38 seconds on the
        # creator's real ledger. This loop used to `_scan_stream` every
        # file unconditionally -- open, read whole, JSON-parse every line
        # -- for all 192,456 of them (190,865 are one-file-per-message
        # `trace:<id>` streams). 40 of the 43 profiled seconds were here.
        #
        # `index.json` already records `{head, bytes, last_ts}` per stream
        # and was written on every start and stop and read by nobody, and
        # the `.idx` files this module's own docstring calls "a cache;
        # rebuilt if stale" were likewise write-only. So: trust the index
        # for any stream whose file is still exactly the recorded length,
        # and scan only the ones that grew, shrank, or are unknown. That
        # is one `stat()` per stream instead of a full read.
        #
        # This keeps crash recovery intact. Appends only ever grow a file,
        # so a process that died mid-write leaves a size the index does
        # not have, which puts that stream straight back on the scan path
        # where its trailing partial line is truncated as before.
        index = self._read_index()
        scanned = 0
        # `os.scandir` over `Path.glob`: glob builds a Path per entry and
        # stats it to decide it is a file, then `sorted()` compares those
        # Paths, then this loop stats each one again -- 267k stat calls
        # and 3.1M Path comparisons for 192k streams. scandir hands back
        # the name and a cached stat from the one directory read, and the
        # names sort as plain strings.
        entries = []
        with os.scandir(self.root / "streams") as it:
            for entry in it:
                if entry.name.endswith(".jsonl"):
                    entries.append((entry.name, entry))
        for name, entry in sorted(entries, key=lambda item: item[0]):
            stream = unescape(name[: -len(".jsonl")])
            known = index.get(stream)
            if known is not None and known.bytes == entry.stat().st_size:
                self._meta[stream] = known
                continue
            # `known.head` is the floor: it was recorded at the last
            # clean start or stop, so every seq up to it was handed out
            # for real. A file that has GROWN since is rescanned to a
            # higher head anyway; a file that has SHRUNK (a lost tail, a
            # partial fsync, somebody's editor) must not be allowed to
            # lower it and reissue a number twice.
            self._scan_stream(stream, self.root / "streams" / name,
                              floor=known.head if known is not None else 0)
            scanned += 1
        self.scanned_on_start = scanned
        self.trusted_on_start = len(self._meta) - scanned
        self._index_dirty = self._meta_differs_from(index)
        self._write_index()
        self._started = True

    async def stop(self) -> None:
        self._write_index()
        self._started = False

    # --------------------------------------------------------------- index io
    def _read_index(self) -> dict[str, _StreamMeta]:
        """The persisted `{stream: {head, bytes, last_ts}}` map. Any
        problem reading it -- absent, truncated, written by an older
        layout -- means an empty index, which costs a full scan and is
        never wrong."""
        try:
            raw = json.loads((self.root / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, _StreamMeta] = {}
        for stream, meta in raw.items():
            if isinstance(meta, dict) and isinstance(meta.get("bytes"), int):
                out[stream] = _StreamMeta(int(meta.get("head") or 0), meta["bytes"], meta.get("last_ts"))
        return out

    def _meta_differs_from(self, index: dict[str, _StreamMeta]) -> bool:
        if set(index) != set(self._meta):
            return True
        return any(index[s].bytes != m.bytes or index[s].head != m.head for s, m in self._meta.items())

    def _scan_stream(self, stream: str, path: Path, *, floor: int = 0) -> None:
        """Rebuild head/bytes/last_ts and the idempotency cache from the
        file itself, truncating a trailing partial line (a crash
        mid-write) rather than failing on it.

        Two rules here are asymmetric on purpose, and both were wrong
        before (observer, 2026-09-10):

        * A line with no terminating newline is a crash mid-append. Its
          seq was never returned to a caller, so removing it loses
          nothing and the number is free to be issued again -- this is
          the one thing that may shorten the file.
        * A COMPLETE line that will not parse is corruption in the
          middle of durable, already-acked data. Everything after it is
          real. This used to `break` at that line and then truncate the
          file to it, so one flipped byte silently deleted every record
          that followed. Now the bad line is counted in `self.corrupt`,
          the scan carries on past it, and nothing is removed.

        `floor` (and the durable mark, and any head this process already
        knows) is a lower bound on the result: the head of a stream
        never goes backwards, so a file that came back SHORTER than we
        last saw it cannot make `append` reissue a sequence number.
        """
        # Any rewrite of the file makes the read-offset index
        # (`read`) meaningless -- the size check there would catch it,
        # but a rewrite is exactly where a stale byte offset must be
        # thrown away rather than relied on to look wrong.
        self._offsets.pop(stream, None)
        head = 0
        last_ts: float | None = None
        complete_end = 0  # end of the last newline-terminated line, parseable or not
        corrupt = 0
        events: list[Event] = []
        with open(path, "rb") as fh:
            data = fh.read()
        pos = 0
        while pos < len(data):
            nl = data.find(b"\n", pos)
            if nl == -1:
                break  # trailing partial line: a crash mid-append
            line = data[pos:nl]
            complete_end = nl + 1
            pos = nl + 1
            try:
                event = Event.from_dict(json.loads(line.decode("utf-8")))
            except Exception:  # noqa: BLE001 -- durable but unreadable; keep it and keep going
                corrupt += 1
                continue
            events.append(event)
            head = max(head, event.seq)
            last_ts = event.ts
        if complete_end != len(data):
            self._truncate_file(path, complete_end)
            self.recovered.append(stream)
        if corrupt:
            self.corrupt[stream] = corrupt
        else:
            self.corrupt.pop(stream, None)
        # A compaction that kept nothing leaves a file with no seq in it
        # at all; the mark is the only remaining record of what this
        # stream has already handed out. `floor` and any head this
        # process already knows are the same rule for a file that has
        # lost its tail some other way.
        known = self._meta[stream].head if stream in self._meta else 0
        from_file, head = head, max(head, self._read_mark(stream), floor, known)
        if head > from_file:
            # The file can no longer prove this head, and `index.json`
            # is disposable by design -- without a durable mark the next
            # boot would reissue those numbers. Only in this case: a
            # write per scanned stream would be 192k files on the
            # creator's ledger, for nothing.
            self._write_mark(stream, head)
        self._meta[stream] = _StreamMeta(head, complete_end, last_ts)
        self._idem.rebuild(stream, events)
        self._idem_loaded.add(stream)
        self._index_dirty = True

    @staticmethod
    def _truncate_file(path: Path, size: int) -> None:
        with open(path, "r+b") as fh:
            fh.truncate(size)
            fh.flush()
            os.fsync(fh.fileno())

    def _write_index(self) -> None:
        # 21MB of JSON on the creator's ledger; rewriting it when not one
        # byte of it changed cost 1.6s of every boot and shutdown.
        if not self._index_dirty and (self.root / "index.json").exists():
            return
        try:
            tmp = self.root / "index.json.tmp"
            tmp.write_text(
                json.dumps({s: m.as_dict() for s, m in sorted(self._meta.items())}, indent=1),
                encoding="utf-8",
            )
            os.replace(tmp, self.root / "index.json")
            self._index_dirty = False
        except OSError:
            pass  # the files are the truth; a missing index just costs a rescan

    # ------------------------------------------------------------------- core
    async def head(self, stream: str) -> int:
        meta = self._meta.get(stream)
        if meta is None:
            path = self._stream_path(stream)
            if path.exists():  # appended by another process since start
                self._scan_stream(stream, path)
                meta = self._meta.get(stream)
        return max(meta.head if meta else 0, self._read_mark(stream))

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
                # Keep the read-offset index (`read`) in step rather than
                # discarding it on every append: an appender that
                # invalidates its own index leaves an incremental reader
                # parsing the whole file on every poll, which is the cost
                # the index exists to remove.
                cached = self._offsets.get(event.stream)
                if cached is not None:
                    size_when_built, offsets = cached
                    if size_when_built == meta.bytes:
                        offsets[stored.seq] = meta.bytes
                        self._offsets[event.stream] = (meta.bytes + len(line), offsets)
                    else:  # somebody else wrote to this file; our offsets may be nonsense
                        self._offsets.pop(event.stream, None)
                meta.head = stored.seq
                meta.bytes += len(line)
                meta.last_ts = stored.ts
                if stored.idempotency_key:
                    self._ensure_idem_loaded(event.stream)
                self._idem.record(event.stream, stored.idempotency_key, stored.seq)
                self._append_idem_line(event.stream, stored.idempotency_key, stored.seq)
                self._index_dirty = True
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
        self._ensure_idem_loaded(stream)
        return self._idem.get(stream, key)

    def _ensure_idem_loaded(self, stream: str) -> None:
        """Read one stream's `.idx` cache on first use. A stream trusted
        from the index at start has had no keys in memory until now; a
        stream that was scanned already rebuilt them from the events
        themselves and is marked loaded there."""
        if stream in self._idem_loaded:
            return
        self._idem_loaded.add(stream)
        try:
            raw = self._idem_path(stream).read_text(encoding="utf-8")
        except OSError:
            return  # no cache file: nothing was ever appended with a key
        for line in raw.splitlines():
            key, _, seq = line.partition("\t")
            if key and seq.isdigit():
                self._idem.record(stream, key, int(seq))

    #: Streams shorter than this never get an offset index: parsing a
    #: couple of hundred lines is cheaper than the bookkeeping, and the
    #: creator's ledger has ~190k one-event `trace:` streams that would
    #: otherwise each carry a dict for nothing.
    _OFFSET_INDEX_MIN_EVENTS = 256

    async def read(self, stream: str, *, from_seq: int, limit: int | None) -> list[Event]:
        """Every event of `stream` from `from_seq` on.

        `from_seq` used to cost the same as reading the whole stream:
        the loop opened the file, JSON-parsed every line, and threw away
        the ones below the cursor. Anything keeping an incremental view
        of a stream therefore paid full price per poll -- Memory's
        recall index reads two streams per recall and that was 58 ms of
        an 86 ms call at 10,000 records each (2026-09-10).

        So a full pass records the byte offset of each seq, and a later
        `from_seq` seeks straight to it. The index is in-process only,
        keyed by the file size it was built at, and DISCARDED if the
        file has changed length -- appends only ever grow the file, and
        a shrink or a rewrite (`truncate_below`) puts the stream back on
        the full-scan path. Belt and braces: the first event read after
        a seek must actually be `from_seq`, or the seek is abandoned and
        the whole file is parsed. A wrong offset can therefore cost a
        redundant read, never a wrong answer.
        """
        path = self._stream_path(stream)
        if not path.exists():
            return []
        if from_seq > 1:
            seeked = self._read_from_offset(stream, path, from_seq, limit)
            if seeked is not None:
                return seeked
        out: list[Event] = []
        offsets: dict[int, int] = {}
        position = 0
        corrupt = 0
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                start = position
                position += len(line.encode("utf-8"))
                if not line.endswith("\n"):
                    break  # partial trailing line: not yet durable
                try:
                    event = Event.from_dict(json.loads(line))
                except Exception:  # noqa: BLE001 -- durable but unreadable: skip it, do not stop
                    # This used to `break`, which reported one flipped
                    # byte as the end of the stream: `head` still said 5
                    # while `read` returned 2 events, no error, no log,
                    # and every projection rebuilt itself short
                    # (observer, 2026-09-10). One unreadable record is a
                    # gap; it is not a shorter history.
                    corrupt += 1
                    continue
                offsets[event.seq] = start
                if event.seq >= from_seq:
                    out.append(event)
                    if limit is not None and len(out) >= limit:
                        # A partial pass indexes only what it saw; it must
                        # not be recorded as covering the whole file.
                        return out
        # A full pass is also the one place that can tell whether this
        # stream still holds unreadable records; `truncate_below` asks.
        if corrupt:
            self.corrupt[stream] = corrupt
        else:
            self.corrupt.pop(stream, None)
        if len(offsets) >= self._OFFSET_INDEX_MIN_EVENTS:
            try:
                self._offsets[stream] = (path.stat().st_size, offsets)
            except OSError:
                self._offsets.pop(stream, None)
        return out

    def _read_from_offset(self, stream: str, path, from_seq: int, limit: int | None):
        """`[Event]` read by seeking to `from_seq`, or None to say the
        caller should parse the file itself."""
        cached = self._offsets.get(stream)
        if cached is None:
            return None
        size_when_built, offsets = cached
        # A tail poll asks for `head + 1` -- one past the last event --
        # far more often than for an exact interior seq: that is what an
        # incremental reader does every time it checks for new records.
        # Seeking to the highest seq we know and skipping forward from
        # there answers it for the cost of one line, where insisting on
        # an exact hit sent the commonest call of all down the full-parse
        # path and the index bought nothing (measured: no change at all
        # in Memory's 86 ms recall until this case was handled).
        start_seq = from_seq if from_seq in offsets else max(offsets)
        if start_seq > from_seq:
            return None
        start = offsets[start_seq]
        try:
            if path.stat().st_size < size_when_built:
                self._offsets.pop(stream, None)  # rewritten or truncated: the offsets are meaningless
                return None
        except OSError:
            return None
        out: list[Event] = []
        with open(path, "r", encoding="utf-8") as fh:
            fh.seek(start)
            first = True
            for line in fh:
                if not line.endswith("\n"):
                    break
                try:
                    event = Event.from_dict(json.loads(line))
                except Exception:  # noqa: BLE001 -- a gap, not the end (see the full pass above)
                    continue
                if first:
                    first = False
                    if event.seq != start_seq:
                        self._offsets.pop(stream, None)
                        return None  # the offset did not point where it claimed: parse it properly
                if event.seq < from_seq:
                    continue
                out.append(event)
                if limit is not None and len(out) >= limit:
                    break
        return out

    async def streams(self, prefix: str) -> list[str]:
        """Every non-empty stream under `prefix`. Planning calls this on
        every rebuild, so it walks the directory once with `scandir` and
        filters on the *unescaped* name before touching a size, instead of
        globbing 192k Paths and stat-ing every one of them (0.9s of the
        creator's boot). `escape` is not prefix-preserving in general, so
        the name still has to be unescaped before the prefix test."""
        out = []
        try:
            with os.scandir(self.root / "streams") as it:
                for entry in it:
                    if not entry.name.endswith(".jsonl"):
                        continue
                    name = unescape(entry.name[: -len(".jsonl")])
                    if not name.startswith(prefix):
                        continue
                    if entry.stat().st_size > 0:
                        out.append(name)
        except OSError:
            return []
        return sorted(out)

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
        # Any rewrite of the file makes the read-offset index
        # (`read`) meaningless -- the size check there would catch it,
        # but a rewrite is exactly where a stale byte offset must be
        # thrown away rather than relied on to look wrong.
        self._offsets.pop(stream, None)
        async with self._lock_for(stream):
            with self._file_lock():
                self._refresh_if_grown(stream)
                events = await self.read(stream, from_seq=0, limit=None)
                if self.corrupt.get(stream):
                    # Compaction rewrites the file from what `read`
                    # returned. A record this pass could not parse is
                    # not in that list, so compacting would delete it
                    # for good -- turning "one line we cannot read" into
                    # "one line nobody can ever read again", silently,
                    # as retention housekeeping. Leave the stream alone
                    # and let a human look at it.
                    return 0
                kept = [e for e in events if e.seq >= seq]
                removed = len(events) - len(kept)
                if removed == 0:
                    return 0
                # Before anything is removed, write down what this stream
                # has already handed out. In memory `meta.head` survives
                # the rewrite, but nothing durable does: a rescan (index
                # lost, or another process seeing the size change) reads
                # head straight out of a file that may now be empty.
                self._write_mark(stream, max(self._meta[stream].head if stream in self._meta else 0,
                                             events[-1].seq if events else 0))
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
        # Any rewrite of the file makes the read-offset index
        # (`read`) meaningless -- the size check there would catch it,
        # but a rewrite is exactly where a stale byte offset must be
        # thrown away rather than relied on to look wrong.
        self._offsets.pop(stream, None)
        async with self._lock_for(stream):
            with self._file_lock():
                # Deleting the stream is the one thing that starts it
                # over, so the mark goes with it; compaction never does.
                for path in (self._stream_path(stream), self._snapshot_path(stream), self._idem_path(stream),
                             self._head_path(stream)):
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

    async def sweep_unreferenced_blobs(self, *, grace_seconds: float = 3600.0) -> int:
        """Delete blobs no live stream or snapshot still references.

        Live-caught: `run_compaction` deletes/truncates *streams* per
        retention, but nothing ever swept the blob store itself -- a
        `trace:` stream that expired after its 2-day window left the
        oversized payload it had pointed to sitting in `blobs/` forever,
        since content addressing means the same bytes may be shared by
        several streams and a naive "delete the blob when its one
        producing stream goes" would break that sharing. So: read what
        actually still points at each blob (scanning raw bytes across
        every remaining stream and snapshot file is far cheaper than
        parsing each event, and `blob:<sha256>` cannot appear by accident
        in any other field), and remove anything neither referenced nor
        younger than `grace_seconds` -- the grace period covers the
        window between `put_blob` and the event that will reference it
        landing (`TraceWriter.write_blob_body` runs before `write()`).
        """
        referenced: set[str] = set()
        for subdir in ("streams", "snapshots"):
            directory = self.root / subdir
            if not directory.exists():
                continue
            with os.scandir(directory) as it:
                for entry in it:
                    if not entry.is_file():
                        continue
                    try:
                        data = Path(entry.path).read_bytes()
                    except OSError:
                        continue
                    for match in _BLOB_REF_BYTES.finditer(data):
                        referenced.add(match.group(1).decode("ascii"))
        cutoff = time.time() - grace_seconds
        removed = 0
        for digest, mtime in self._blobs.list_digests():
            if digest in referenced:
                continue
            if mtime > cutoff:
                continue  # too young: may not be referenced yet
            if self._blobs.delete(digest):
                removed += 1
        return removed

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
