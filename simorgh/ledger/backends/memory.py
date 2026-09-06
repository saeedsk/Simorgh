"""In-memory backend: a dict of lists. Deterministic, dependency-free,
and the reference semantics every other backend's parity tests are
checked against. Not durable -- for tests and `single`-mode dry runs.
"""

from __future__ import annotations

from dataclasses import replace

from simorgh.contracts.envelope import Event

from ..api import ConflictError
from ..blobs import InMemoryBlobStore


class InMemoryBackend:
    cross_process = False

    def __init__(self) -> None:
        self._events: dict[str, list[Event]] = {}
        self._snapshots: dict[str, tuple[dict, int]] = {}
        self._blobs = InMemoryBlobStore()

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def head(self, stream: str) -> int:
        events = self._events.get(stream)
        return events[-1].seq if events else 0

    async def append(self, event: Event, *, expected_seq: int | None) -> int:
        head = await self.head(event.stream)
        if expected_seq is not None and expected_seq != head:
            raise ConflictError(event.stream, expected_seq, head)
        stored = replace(event, seq=head + 1)
        self._events.setdefault(event.stream, []).append(stored)
        return stored.seq

    async def find_by_idempotency(self, stream: str, key: str) -> int | None:
        for event in self._events.get(stream, ()):
            if event.idempotency_key == key:
                return event.seq
        return None

    async def read(self, stream: str, *, from_seq: int, limit: int | None) -> list[Event]:
        out = [e for e in self._events.get(stream, ()) if e.seq >= from_seq]
        return out[:limit] if limit is not None else out

    async def streams(self, prefix: str) -> list[str]:
        return sorted(s for s, evs in self._events.items() if evs and s.startswith(prefix))

    async def write_snapshot(self, stream: str, state: dict, at_seq: int) -> None:
        self._snapshots[stream] = (dict(state), at_seq)

    async def read_snapshot(self, stream: str) -> tuple[dict, int] | None:
        found = self._snapshots.get(stream)
        return (dict(found[0]), found[1]) if found else None

    async def delete_snapshot(self, stream: str) -> None:
        self._snapshots.pop(stream, None)

    async def truncate_below(self, stream: str, seq: int) -> int:
        events = self._events.get(stream, [])
        kept = [e for e in events if e.seq >= seq]
        removed = len(events) - len(kept)
        self._events[stream] = kept
        return removed

    async def delete_stream(self, stream: str) -> None:
        self._events.pop(stream, None)
        self._snapshots.pop(stream, None)

    async def put_blob(self, data: bytes, *, content_type: str) -> str:
        return self._blobs.put(data, content_type=content_type)

    async def get_blob(self, ref: str) -> bytes:
        return self._blobs.get(ref)

    async def stat(self) -> dict:
        return {
            "streams": sum(1 for evs in self._events.values() if evs),
            "events": sum(len(evs) for evs in self._events.values()),
            "snapshots": len(self._snapshots),
            "bytes_total": sum(len(e.to_json()) + 1 for evs in self._events.values() for e in evs),
            **self._blobs.stat(),
        }

    async def last_ts(self, stream: str) -> float | None:
        events = self._events.get(stream)
        return events[-1].ts if events else None


__all__ = ["InMemoryBackend"]
