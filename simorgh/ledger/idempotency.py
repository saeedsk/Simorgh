"""Per-stream idempotency-key index (02-ledger section 7: dedupe in the
store, not only in handlers). At-least-once delivery on the Bus makes
duplicates normal; an append whose `idempotency_key` was already recorded
for that stream returns the existing seq and writes nothing, so every
projection stays correct even if a handler forgets to check.

The index is a cache: it is always rebuildable from the stream itself
(every event carries its key), which is what the `jsonl` backend does on
start when its `idem/` sidecar is missing or stale.
"""

from __future__ import annotations

from collections.abc import Iterable

from simorgh.contracts.envelope import Event


class IdempotencyIndex:
    def __init__(self) -> None:
        self._by_stream: dict[str, dict[str, int]] = {}

    def get(self, stream: str, key: str) -> int | None:
        return self._by_stream.get(stream, {}).get(key)

    def record(self, stream: str, key: str | None, seq: int) -> None:
        if key:
            self._by_stream.setdefault(stream, {})[key] = seq

    def forget_stream(self, stream: str) -> None:
        self._by_stream.pop(stream, None)

    def forget_below(self, stream: str, seq: int) -> None:
        keys = self._by_stream.get(stream)
        if keys:
            for key in [k for k, s in keys.items() if s < seq]:
                del keys[key]

    def rebuild(self, stream: str, events: Iterable[Event]) -> None:
        self._by_stream[stream] = {e.idempotency_key: e.seq for e in events if e.idempotency_key}

    def items(self, stream: str) -> list[tuple[str, int]]:
        return sorted(self._by_stream.get(stream, {}).items(), key=lambda kv: kv[1])


__all__ = ["IdempotencyIndex"]
