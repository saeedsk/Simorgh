"""The trace writer: every message -> Ledger stream `trace:<trace_id>`,
sampled per type (docs/blueprint/subsystems/01-bus.md section 5.6; 03
section 5 "Tracing").

The bus never blocks on the Ledger. Writes go through a bounded queue
drained by a background task; under overload the writer drops with a
counter rather than slowing publishers, and if the Ledger is down it
degrades to a bounded in-memory buffer plus a `degraded` health signal
(section 8) -- delivery is unaffected either way. Payload bodies over
`blob_threshold` are stored as blobs and referenced, so a 200 KB tool
result never lands inline in a trace event.

The Ledger arrives as a protocol-typed object (`contracts.protocols.Ledger`);
this package does not import `simorgh.ledger` (boundary rule).
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from typing import Callable, Mapping

from simorgh.contracts.envelope import Event, Message, canonical_json
from simorgh.contracts.protocols import Ledger
from simorgh.contracts.topics import matches

Rng = Callable[[], float]


class TraceWriter:
    def __init__(
        self,
        ledger: Ledger | None,
        *,
        sample: Mapping[str, float] | None = None,
        blob_threshold: int = 4096,
        queue_size: int = 10_000,
        buffer_size: int = 10_000,
        rng: Rng | None = None,
        enabled: bool = True,
    ) -> None:
        self._ledger = ledger
        self._sample = dict(sample or {})
        self._blob_threshold = blob_threshold
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self._buffer: deque[Event] = deque(maxlen=buffer_size)  # fallback when the ledger is down
        self._rng = rng or random.random
        self._enabled = enabled and ledger is not None
        self._task: asyncio.Task | None = None
        self.dropped = 0
        self.written = 0
        self.failed = 0
        self.degraded = False

    # -- sampling ----------------------------------------------------------
    def sample_rate(self, type_name: str) -> float:
        """Most specific pattern wins; exact type first, then patterns in
        declaration order; default 1.0."""
        if type_name in self._sample:
            return float(self._sample[type_name])
        for pattern, rate in self._sample.items():
            if matches(pattern, type_name):
                return float(rate)
        return 1.0

    def should_trace(self, message: Message) -> bool:
        if not self._enabled:
            return False
        rate = self.sample_rate(message.type)
        if rate >= 1.0:
            return True
        if rate <= 0.0:
            return False
        return self._rng() < rate

    # -- writing -----------------------------------------------------------
    def write(self, message: Message) -> None:
        """Non-blocking; safe to call from `publish`. Lazily starts the
        drain task on first use rather than requiring every caller to
        remember an explicit `start()` first -- a writer that silently
        queues without ever draining (because `start()` was never called)
        fails the same way as no tracing at all, just quieter: nothing
        raises, the queue simply grows and nothing ever reaches the
        ledger. `start()`/`stop()` remain the explicit lifecycle the
        Service uses; this is the fallback for anything that forgets."""
        if not self.should_trace(message):
            return
        if self._enabled and self._task is None:
            self._task = asyncio.create_task(self._drain(), name="bus-trace-writer")
        event = self._to_event(message)
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1

    def _to_event(self, message: Message) -> Event:
        # The client has already replaced an oversized body with {"payload_ref": ...} (write_blob_body).
        envelope = message.to_dict()
        return Event(
            stream=f"trace:{message.trace_id}",
            type=message.type,
            ts=message.ts,
            trace_id=message.trace_id,
            causation_id=message.causation_id,
            payload=envelope,
            idempotency_key=message.id,
        )

    async def start(self) -> None:
        if self._enabled and self._task is None:
            self._task = asyncio.create_task(self._drain(), name="bus-trace-writer")

    async def stop(self) -> None:
        if self._task is None:
            return
        await self.flush()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def flush(self) -> None:
        """Drain whatever is queued right now (tests and shutdown)."""
        while not self._queue.empty():
            event = self._queue.get_nowait()
            await self._append(event)

    async def _drain(self) -> None:
        while True:
            event = await self._queue.get()
            await self._append(event)

    async def _append(self, event: Event) -> None:
        assert self._ledger is not None
        try:
            await self._ledger.append(event.stream, event)
            self.written += 1
            if self.degraded:
                self.degraded = False
                await self._replay_buffer()
        except Exception:  # noqa: BLE001 -- the ledger being down must never break delivery
            self.failed += 1
            self.degraded = True
            self._buffer.append(event)

    async def _replay_buffer(self) -> None:
        while self._buffer:
            event = self._buffer.popleft()
            try:
                await self._ledger.append(event.stream, event)  # type: ignore[union-attr]
                self.written += 1
            except Exception:  # noqa: BLE001
                self._buffer.appendleft(event)
                self.degraded = True
                return

    async def write_blob_body(self, message: Message) -> str | None:
        """For oversized payloads: store the body as a blob and return the
        ref. Called by the client *before* `write()` so the trace event can
        carry `payload_ref` instead of `_blob_pending`."""
        if self._ledger is None:
            return None
        body = canonical_json(message.payload).encode("utf-8")
        if len(body) <= self._blob_threshold:
            return None
        try:
            return await self._ledger.put_blob(body, content_type="application/json")
        except Exception:  # noqa: BLE001
            self.failed += 1
            return None


__all__ = ["TraceWriter"]
