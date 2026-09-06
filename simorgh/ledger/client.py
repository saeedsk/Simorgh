"""`LedgerClient` -- the `contracts.protocols.Ledger` implementation
every subsystem talks to (and the only ledger module a subsystem may
import: `02` section 4 module rules). It layers what every backend
would otherwise have to repeat onto a small mechanical storage engine:

- validation before any write: stream grammar, canonical/NaN-free
  payload, and the blob threshold (a string larger than
  `inline_threshold` must be a `blob:` ref, so one file-content payload
  can never bloat a stream and slow every future replay);
- idempotency: an append whose key is already recorded returns the
  existing seq and writes nothing, so at-least-once delivery on the Bus
  can never double-record;
- CAS via `expected_seq` (delegated to the backend, the same on every
  engine -- this is how Planning guarantees a single claimant);
- `tail()` delivery -- in-process after each own append, plus a poll
  loop for cross-process backends -- with per-stream cursors so a
  subscriber never sees an event twice;
- `rebuild()`/`materialize()` for projections; `compact()` for record
  compaction; counters for `system.metrics`.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import replace
from typing import Any, Awaitable, Callable

from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Clock

from .api import ConflictError, LedgerBackend, Projection, ValidationError
from .blobs import is_ref
from .projection import materialize as _materialize
from .projection import rebuild as _rebuild
from .streams import validate_stream

TailHandler = Callable[[Event], Awaitable[None]]


class _Tail:
    """One `tail()` subscription: an exact stream, or every stream under
    a prefix (an argument ending in `:`)."""

    def __init__(self, client: "LedgerClient", pattern: str, handler: TailHandler) -> None:
        self.pattern = pattern
        self.handler = handler
        self._client = client
        self.cursors: dict[str, int] = {}
        self.poll_task: asyncio.Task | None = None
        self.active = True

    def matches(self, stream: str) -> bool:
        if self.pattern.endswith(":"):
            return stream.startswith(self.pattern)
        return stream == self.pattern

    async def deliver(self, event: Event) -> None:
        if not self.active or event.seq <= self.cursors.get(event.stream, 0):
            return
        self.cursors[event.stream] = event.seq
        try:
            await self.handler(event)
        except Exception:  # noqa: BLE001 -- a subscriber's bug must not break the appender
            pass

    async def unsubscribe(self) -> None:
        self.active = False
        if self.poll_task is not None:
            self.poll_task.cancel()
            try:
                await self.poll_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self.poll_task = None
        self._client._tails.discard(self)


class LedgerClient:
    def __init__(
        self,
        backend: LedgerBackend,
        *,
        clock: Clock | None = None,
        inline_threshold: int = 4096,
        tail_poll_ms: int = 100,
        source: str = "ledger",
    ) -> None:
        self.backend = backend
        self._clock = clock
        self.inline_threshold = inline_threshold
        self.tail_poll_ms = tail_poll_ms
        self.source = source
        self._tails: set[_Tail] = set()
        self.counters: dict[str, int] = {
            "appends": 0, "conflicts": 0, "dedupes": 0, "blobs_put": 0, "validation_errors": 0,
        }
        self.last_error: str | None = None
        self.started = False

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self.backend.start()
        self.started = True

    async def stop(self) -> None:
        for tail in list(self._tails):
            await tail.unsubscribe()
        await self.backend.stop()
        self.started = False

    def _now(self) -> float:
        if self._clock is not None:
            return self._clock.now()
        import time

        return time.time()

    # ------------------------------------------------------------- validation
    def _validate(self, stream: str, event: Event) -> Event:
        try:
            validate_stream(stream)
        except ValueError as exc:
            self.counters["validation_errors"] += 1
            raise ValidationError(str(exc)) from None
        if event.stream != stream:
            event = replace(event, stream=stream)
        if not isinstance(event.payload, dict):
            self.counters["validation_errors"] += 1
            raise ValidationError("payload must be an object")
        problems: list[str] = []
        self._walk(event.payload, "$", problems)
        if problems:
            self.counters["validation_errors"] += 1
            raise ValidationError("; ".join(problems))
        if not event.type:
            self.counters["validation_errors"] += 1
            raise ValidationError("event.type is required")
        if event.ts is None or (isinstance(event.ts, float) and math.isnan(event.ts)):
            event = replace(event, ts=self._now())
        return event

    def _walk(self, value: Any, path: str, problems: list[str]) -> None:
        if isinstance(value, str):
            if len(value) > self.inline_threshold and not is_ref(value):
                problems.append(f"{path}: {len(value)} chars inline exceeds {self.inline_threshold}; store it with put_blob and reference it")
        elif isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            problems.append(f"{path}: NaN/Infinity is not storable")
        elif isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    problems.append(f"{path}: non-string key {key!r}")
                self._walk(item, f"{path}.{key}", problems)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                self._walk(item, f"{path}[{i}]", problems)
        elif value is not None and not isinstance(value, (bool, int, float)):
            problems.append(f"{path}: {type(value).__name__} is not JSON-serializable")

    # ------------------------------------------------------------------- core
    async def append(self, stream: str, event: Event, *, expected_seq: int | None = None) -> int:
        event = self._validate(stream, event)
        if event.idempotency_key:
            existing = await self.backend.find_by_idempotency(stream, event.idempotency_key)
            if existing is not None:
                self.counters["dedupes"] += 1
                return existing
        try:
            seq = await self.backend.append(event, expected_seq=expected_seq)
        except Exception as exc:
            from .api import ConflictError, LedgerUnavailable

            if isinstance(exc, ConflictError):
                self.counters["conflicts"] += 1
            elif isinstance(exc, LedgerUnavailable):
                self.last_error = str(exc)
            raise
        self.counters["appends"] += 1
        self.last_error = None
        stored = replace(event, seq=seq)
        for tail in list(self._tails):
            if tail.matches(stream):
                await tail.deliver(stored)
        return seq

    async def head(self, stream: str) -> int:
        return await self.backend.head(stream)

    async def read(self, stream: str, *, from_seq: int = 0, limit: int | None = None) -> list[Event]:
        return await self.backend.read(stream, from_seq=from_seq, limit=limit)

    async def streams(self, prefix: str) -> list[str]:
        return await self.backend.streams(prefix)

    async def delete_stream(self, stream: str) -> None:
        await self.backend.delete_stream(stream)

    # ------------------------------------------------------------------- tail
    async def tail(self, stream: str, handler: TailHandler) -> _Tail:
        """Deliver every event appended to `stream` (or to every stream
        under a prefix ending in `:`) from now on. Own appends are
        delivered in-process; on a cross-process backend a poll loop
        also picks up other writers' appends."""
        tail = _Tail(self, stream, handler)
        self._tails.add(tail)
        if getattr(self.backend, "cross_process", False) and self.tail_poll_ms > 0:
            tail.poll_task = asyncio.create_task(self._poll(tail))
        return tail

    async def _poll(self, tail: _Tail) -> None:
        interval = max(0.005, self.tail_poll_ms / 1000.0)
        try:
            while tail.active:
                streams = (await self.backend.streams(tail.pattern) if tail.pattern.endswith(":")
                           else [tail.pattern])
                for stream in streams:
                    cursor = tail.cursors.get(stream, 0)
                    for event in await self.backend.read(stream, from_seq=cursor + 1, limit=None):
                        await tail.deliver(event)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- polling must never die silently... but must never crash the loop
            tail.active = False

    # -------------------------------------------------------------- snapshots
    async def snapshot(self, stream: str, state: dict, at_seq: int) -> None:
        await self.backend.write_snapshot(stream, state, at_seq)

    async def load_snapshot(self, stream: str) -> tuple[dict, int] | None:
        return await self.backend.read_snapshot(stream)

    async def rebuild(self, projection: Projection, stream: str) -> int:
        return await _rebuild(self.backend, projection, stream)

    async def materialize(self, projection: Projection, stream: str) -> int:
        return await _materialize(self.backend, projection, stream)

    # ------------------------------------------------------------------ blobs
    async def put_blob(self, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        ref = await self.backend.put_blob(bytes(data), content_type=content_type)
        self.counters["blobs_put"] += 1
        return ref

    async def get_blob(self, ref: str) -> bytes:
        return await self.backend.get_blob(ref)

    # ------------------------------------------------------------- compaction
    async def compact(self, stream: str, *, before_seq: int, keep_snapshot: bool = True) -> int:
        removed = await self.backend.truncate_below(stream, before_seq)
        if not keep_snapshot:
            await self.backend.delete_snapshot(stream)
        return removed


__all__ = ["LedgerClient", "TailHandler", "ConflictError"]
