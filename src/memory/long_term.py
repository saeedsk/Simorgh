"""Persistent, durable memory for Simorgh.

Continuity of self, per docs/SOUL.md's Philosophical Grounding, is
continuity of *record* rather than continuity of process: whatever process
is currently running should be able to reload the same memory a prior
process wrote. MemoryStore is the interface that guarantees that; the
concrete backend can be swapped (local disk today, a redundant multi-cloud
object store later -- see docs/EVOLUTION.md) without touching callers.
"""

from __future__ import annotations

import abc
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MemoryRecord:
    """One durable fact Simorgh has learned or experienced.

    `kind` is a free-form label; conventional values are "episodic"
    (something that happened), "semantic" (a fact learned), "procedural"
    (a skill or how-to), "outcome" (the result of a dispatched action, see
    src/orchestrator/reflection.py), and "lineage" (a record of a
    self-modification).
    """

    id: str
    kind: str
    content: str
    created_at: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(kind: str, content: str, **metadata: Any) -> "MemoryRecord":
        return MemoryRecord(
            id=str(uuid.uuid4()),
            kind=kind,
            content=content,
            created_at=time.time(),
            metadata=metadata,
        )


class MemoryStore(abc.ABC):
    """Interface for durable memory. Implementations must make `add`
    durable before returning -- a crash immediately after `add()` must not
    lose the record.
    """

    @abc.abstractmethod
    def add(self, record: MemoryRecord) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def get(self, record_id: str) -> MemoryRecord | None:
        raise NotImplementedError

    @abc.abstractmethod
    def query(
        self, kind: str | None = None, limit: int | None = None
    ) -> list[MemoryRecord]:
        """Return records, most recent first, optionally filtered by kind."""
        raise NotImplementedError

    @abc.abstractmethod
    def delete(self, record_id: str) -> bool:
        """Permanently remove a record. Returns True if it existed. Used
        for consolidation/pruning (src/orchestrator/consolidation.py), not
        by normal request-handling code paths.
        """
        raise NotImplementedError

    def remember(self, kind: str, content: str, **metadata: Any) -> MemoryRecord:
        """Convenience: build and store a MemoryRecord in one call."""
        record = MemoryRecord.create(kind, content, **metadata)
        self.add(record)
        return record


class InMemoryStore(MemoryStore):
    """Non-durable, process-local memory store. Useful for tests, and as
    the last-resort backend if even local disk isn't writable -- a process
    that can't persist memory should still be able to run this session.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, MemoryRecord] = {}
        self._order: list[str] = []

    def add(self, record: MemoryRecord) -> None:
        with self._lock:
            self._records[record.id] = record
            self._order.append(record.id)

    def get(self, record_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def query(
        self, kind: str | None = None, limit: int | None = None
    ) -> list[MemoryRecord]:
        with self._lock:
            return _filter_ordered(self._records, reversed(self._order), kind, limit)

    def delete(self, record_id: str) -> bool:
        with self._lock:
            if record_id not in self._records:
                return False
            del self._records[record_id]
            self._order.remove(record_id)
            return True


class JSONFileMemoryStore(MemoryStore):
    """Append-only JSON-Lines memory store on local disk.

    Each record is written and fsync'd before `add` returns, so a crash
    loses at most the record that was mid-write. On construction, all
    existing records are loaded into memory for fast querying.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._records: dict[str, MemoryRecord] = {}
        self._order: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = MemoryRecord(**json.loads(line))
                self._records[record.id] = record
                self._order.append(record.id)

    def add(self, record: MemoryRecord) -> None:
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(record)) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self._records[record.id] = record
            self._order.append(record.id)

    def get(self, record_id: str) -> MemoryRecord | None:
        with self._lock:
            return self._records.get(record_id)

    def query(
        self, kind: str | None = None, limit: int | None = None
    ) -> list[MemoryRecord]:
        with self._lock:
            return _filter_ordered(self._records, reversed(self._order), kind, limit)

    def delete(self, record_id: str) -> bool:
        with self._lock:
            if record_id not in self._records:
                return False
            del self._records[record_id]
            self._order.remove(record_id)
            self._rewrite()
            return True

    def _rewrite(self) -> None:
        """Compact the on-disk log to match in-memory state after a delete.
        O(n), but deletion is a maintenance-time operation, not a hot path.
        """
        with self._path.open("w", encoding="utf-8") as fh:
            for record_id in self._order:
                fh.write(json.dumps(asdict(self._records[record_id])) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


def _filter_ordered(
    records: dict[str, MemoryRecord],
    ids_newest_first: Any,
    kind: str | None,
    limit: int | None,
) -> list[MemoryRecord]:
    results = []
    for record_id in ids_newest_first:
        record = records[record_id]
        if kind is not None and record.kind != kind:
            continue
        results.append(record)
        if limit is not None and len(results) >= limit:
            break
    return results
