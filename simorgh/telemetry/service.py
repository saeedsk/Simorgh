"""`TelemetryService`: the Kernel's implementation of
`contracts.protocols.Telemetry` over one `TelemetryStore`.

A span or sample is appended to an in-memory buffer and nothing else
happens on the caller's path. One writer task waits for the first row,
lets a batch gather for `flush_interval_s` (or until `batch_rows` are
waiting), and writes the batch in one transaction on a worker thread.
Idle, the writer task is parked on an event and never wakes.

The Kernel builds one at boot, hands it to every `Context` as
`ctx.telemetry`, calls `on_sleep_tick()` from `system.tick.sleep` for
retention, and calls `stop()` after the subsystems have stopped, which
flushes whatever is buffered. It is not a supervised subsystem: like
the ledger it is the Kernel's own and outlives every service.
"""

from __future__ import annotations

import asyncio
import contextvars
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Mapping

from simorgh.contracts.protocols import Clock, Logger

from .config import Config
from .store import SampleRow, SpanRow, TelemetryStore, encode

FILENAME = "telemetry.sqlite"

# The innermost open span of this task, so a nested `span()` of the same
# trace finds its parent without being told. asyncio copies the context
# into every task it creates, so a child task inherits it too.
_CURRENT: contextvars.ContextVar["RecordingSpan | None"] = contextvars.ContextVar(
    "simorgh_telemetry_span", default=None)


def new_span_id() -> str:
    return uuid.uuid4().hex[:16]


class RecordingSpan:
    """The `Span` a real `span()` yields."""

    __slots__ = ("trace_id", "span_id", "parent_id", "name", "start", "attrs")

    def __init__(self, name: str, trace_id: str, parent_id: str | None, start: float,
                 attrs: Mapping[str, Any] | None) -> None:
        self.name = name
        self.trace_id = trace_id
        self.parent_id = parent_id
        self.span_id = new_span_id()
        self.start = start
        self.attrs: dict[str, Any] = dict(attrs or {})

    def set(self, key: str, value: Any) -> None:
        self.attrs[key] = value


class TelemetryService:
    def __init__(self, path: str | Path, *, config: Config | None = None, clock: Clock | None = None,
                 logger: Logger | None = None, monotonic: Callable[[], float] = time.monotonic) -> None:
        self.config = config or Config()
        self.store = TelemetryStore(path)
        self._clock = clock
        self._logger = logger
        self._monotonic = monotonic
        self._spans: list[SpanRow] = []
        self._samples: list[SampleRow] = []
        self._pending = asyncio.Event()  # a row is waiting
        self._full = asyncio.Event()  # `batch_rows` are waiting
        self._flush_lock = asyncio.Lock()
        self._writer: asyncio.Task | None = None
        self._after_start: asyncio.Task | None = None
        self._closed = False
        self._last_maintain: float | None = None
        self.counters: dict[str, int] = {
            "spans": 0, "samples": 0, "flushes": 0, "dropped": 0, "write_errors": 0, "maintain_runs": 0,
        }
        self.last_retention: dict[str, int] = {}

    @property
    def path(self) -> Path:
        return self.store.path

    # -------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await asyncio.to_thread(self.store.open)
        self._writer = asyncio.create_task(self._write_loop(), name="telemetry-writer")
        if self.config.maintain_after_start_s > 0:
            self._after_start = asyncio.create_task(self._maintain_after_start(), name="telemetry-after-start")
        if self._spans or self._samples:
            self._pending.set()

    async def stop(self) -> None:
        """Flush everything buffered, then close. Rows recorded after
        this are dropped and counted."""
        self._closed = True
        for task in (self._after_start, self._writer):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: BLE001
                    pass
        self._after_start = self._writer = None
        if self.store.is_open:
            await self.flush()
            await asyncio.to_thread(self.store.close)

    # ------------------------------------------------------------- recording
    def _now(self) -> float:
        return self._clock.now() if self._clock is not None else time.time()

    def _enqueue(self, buffer: list, row: tuple) -> None:
        if self._closed:
            self.counters["dropped"] += 1
            return
        if len(self._spans) + len(self._samples) >= self.config.max_buffer_rows:
            victim = buffer if buffer else (self._samples if self._samples else self._spans)
            victim.pop(0)
            self.counters["dropped"] += 1
        buffer.append(row)
        self._pending.set()
        if len(self._spans) + len(self._samples) >= self.config.batch_rows:
            self._full.set()

    @asynccontextmanager
    async def span(self, name: str, *, trace_id: str, parent_id: str | None = None,
                   attrs: Mapping[str, Any] | None = None) -> AsyncIterator[RecordingSpan]:
        if parent_id is None:
            outer = _CURRENT.get()
            if outer is not None and outer.trace_id == trace_id:
                parent_id = outer.span_id
        span = RecordingSpan(name, trace_id, parent_id, self._now(), attrs)
        token = _CURRENT.set(span)
        status = "ok"
        try:
            yield span
        except Exception as exc:
            status = "error"
            span.attrs.setdefault("error", f"{type(exc).__name__}: {exc}"[:500])
            raise
        except BaseException:
            status = "cancelled"
            raise
        finally:
            _CURRENT.reset(token)
            self.counters["spans"] += 1
            self._enqueue(self._spans, (span.trace_id, span.span_id, span.parent_id, span.name, span.start,
                                        self._now(), status, encode(span.attrs)))

    def event(self, name: str, *, trace_id: str, span_id: str, parent_id: str | None = None,
              ts: float | None = None, attrs: Mapping[str, Any] | None = None) -> None:
        """A finished zero-length span with the caller's id (a bus
        message: its id, its causation id as parent). Never raises."""
        at = float(self._now() if ts is None else ts)
        self.counters["spans"] += 1
        self._enqueue(self._spans, (trace_id, span_id, parent_id, name, at, at, "ok", encode(dict(attrs or {}))))

    def sample(self, series: str, value: Any, ts: float | None = None) -> None:
        self.counters["samples"] += 1
        self._enqueue(self._samples, (series, float(self._now() if ts is None else ts), encode(value)))

    # ---------------------------------------------------------------- writing
    async def flush(self) -> None:
        """Write everything buffered now, off the event loop."""
        async with self._flush_lock:
            spans, self._spans = self._spans, []
            samples, self._samples = self._samples, []
            self._pending.clear()
            self._full.clear()
            if not spans and not samples:
                return
            try:
                await asyncio.to_thread(self.store.write, spans, samples)
                self.counters["flushes"] += 1
            except Exception as exc:  # noqa: BLE001 -- telemetry never takes the system down
                self.counters["write_errors"] += 1
                self.counters["dropped"] += len(spans) + len(samples)
                if self._logger is not None:
                    self._logger.warning("telemetry.write_failed", error=str(exc), rows=len(spans) + len(samples))

    async def _write_loop(self) -> None:
        while True:
            await self._pending.wait()
            try:
                await asyncio.wait_for(self._full.wait(), timeout=self.config.flush_interval_s)
            except (asyncio.TimeoutError, TimeoutError):
                pass
            await self.flush()

    # ------------------------------------------------------------------ reads
    async def query(self, trace_id: str) -> list[dict]:
        await self.flush()
        if not self.store.is_open:
            return []
        return await asyncio.to_thread(self.store.spans, trace_id)

    async def series(self, series: str, *, since: float | None = None, until: float | None = None) -> list[dict]:
        await self.flush()
        if not self.store.is_open:
            return []
        return await asyncio.to_thread(self.store.samples, series, since=since, until=until)

    # -------------------------------------------------------------- retention
    async def maintain(self, now: float | None = None) -> dict[str, int]:
        """One retention pass: age out spans and samples, thin old
        samples to one per bucket per series."""
        await self.flush()
        if not self.store.is_open:
            return {}
        cfg = self.config
        try:
            removed = await asyncio.to_thread(
                self.store.retain, now=self._now() if now is None else now,
                span_max_age_s=cfg.span_retention_s, sample_max_age_s=cfg.sample_retention_s,
                downsample_after_s=cfg.downsample_after_s, bucket_s=cfg.downsample_bucket_s)
        except Exception as exc:  # noqa: BLE001
            self.counters["write_errors"] += 1
            if self._logger is not None:
                self._logger.warning("telemetry.retention_failed", error=str(exc))
            return {}
        self._last_maintain = self._monotonic()
        self.counters["maintain_runs"] += 1
        self.last_retention = removed
        return removed

    async def on_sleep_tick(self) -> dict[str, int] | None:
        """The Kernel's `system.tick.sleep` hook. Skipped (None) if a
        pass ran within `maintain_min_interval_s` of wall-clock time."""
        if (self._last_maintain is not None
                and self._monotonic() - self._last_maintain < self.config.maintain_min_interval_s):
            return None
        return await self.maintain()

    async def _maintain_after_start(self) -> None:
        await asyncio.sleep(self.config.maintain_after_start_s)
        await self.maintain()


__all__ = ["FILENAME", "RecordingSpan", "TelemetryService", "new_span_id"]
