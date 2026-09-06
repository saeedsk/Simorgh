"""Aggregates `system.metrics`/`system.health` into in-memory tables
(justified caches -- section 4: derivable from the `system` stream on
replay, not the durable record itself) and answers
`system.status.request` (docs/blueprint/subsystems/03-kernel.md section
3.3). Timeout expectation for the reply is 2s -- everything here is
already in memory, no Ledger read on the hot path.

Also two small periodic publishers for the dashboard's observe tier
(02-system-architecture.md section 6.2):

- `ProcessMetricsPublisher` -- OS-level process resource usage
  (memory/CPU/load/threads) was not tracked anywhere before this; it
  rides the same `system.metrics` channel every other subsystem's own
  gauges already use, under `subsystem: "process"`, so it needs zero
  changes to `StatusServer`/`MetricsTable` above -- just a new
  publisher and a new dashboard panel over it.
- `MetricsHistoryWriter` -- section 6.2's own "value over time" item.
  `system.metrics` is sampled to 0.0 in the Bus's default `trace_sample`
  (`simorgh/bus/config.py`), so mining `trace:<trace_id>` for it is a
  dead end in practice, not just theoretically lossy -- exactly the
  "impractical" case section 6.2 itself anticipates, and exactly why it
  names a dedicated low-frequency stream as the more likely answer. This
  writer snapshots `MetricsTable.per_subsystem` (already kept warm by
  `StatusServer`) to its own Ledger stream, `metrics:history`, on its
  own schedule -- independent of trace sampling, and cheap because it
  is one append of already-in-memory data, not a Ledger read.
"""

from __future__ import annotations

import asyncio
import copy
import os
import sys
import threading
import uuid

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event, Message
from simorgh.contracts.protocols import Bus, Clock, Ledger

from .state import SystemStateMachine
from .supervisor import Supervisor

HISTORY_STREAM = "metrics:history"
HISTORY_EVENT_TYPE = "system.metrics_history"


class MetricsTable:
    def __init__(self) -> None:
        self.per_subsystem: dict[str, dict] = {}

    def record(self, message: Message) -> None:
        p = message.payload
        entry = self.per_subsystem.setdefault(p["subsystem"], {"counters": {}, "gauges": {}})
        entry["counters"] = p.get("counters", {})
        entry["gauges"] = p.get("gauges", {})


class StatusServer:
    def __init__(
        self,
        *,
        bus: Bus,
        clock: Clock,
        run_id: str,
        mode: str,
        state: SystemStateMachine,
        supervisor: Supervisor,
        metrics: MetricsTable,
        boot_time: float,
        source: str = "kernel",
    ) -> None:
        self._bus = bus
        self._clock = clock
        self._run_id = run_id
        self._mode = mode
        self._state = state
        self._supervisor = supervisor
        self._metrics = metrics
        self._boot_time = boot_time
        self._source = source
        self._metrics_sub = None
        self._health_sub = None
        self._status_sub = None

    async def start(self) -> None:
        self._metrics_sub = await self._bus.subscribe(topics.SYSTEM_METRICS, self._on_metrics)
        self._health_sub = await self._bus.subscribe(topics.SYSTEM_HEALTH, self._on_health)
        self._status_sub = await self._bus.subscribe(topics.SYSTEM_STATUS_REQUEST, self._on_status_request,
                                                      group="kernel-status")

    async def stop(self) -> None:
        for sub in (self._metrics_sub, self._health_sub, self._status_sub):
            if sub is not None:
                await sub.unsubscribe()

    async def _on_metrics(self, message: Message) -> None:
        self._metrics.record(message)

    async def _on_health(self, message: Message) -> None:
        pass  # the supervisor's own poll is the source of truth for status(); this just keeps the table warm

    def snapshot(self) -> dict:
        # `LAYERS` gives each subsystem's boot-order layer for free -- a
        # dashboard groups by it without duplicating the ordering itself.
        # Kernel isn't a member of its own `LAYERS` (it's the composition
        # root, see `registry.py`'s own docstring), so it has no layer.
        from .registry import LAYERS

        layer_of = {name: i for i, layer in enumerate(LAYERS) for name in layer}
        subsystems = [
            {
                "name": s.name, "version": getattr(s.service, "version", ""), "status": s.status,
                "detail": s.last_health.detail if s.last_health is not None else "",
                "restarts": s.restarts, "layer": layer_of.get(s.name),
            }
            for s in self._supervisor.services.values()
        ]
        return {
            "run_id": self._run_id,
            "mode": self._mode,
            "state": self._state.state,
            "uptime_seconds": self._clock.now() - self._boot_time,
            "subsystems": subsystems,
            "metrics": self._metrics.per_subsystem,
        }

    async def _on_status_request(self, message: Message) -> None:
        await self._bus.reply(message, type=topics.SYSTEM_STATUS_REPLY, payload=self.snapshot())


def process_gauges() -> dict:
    """OS-level process resource usage, stdlib only (`resource.getrusage`,
    `os.getloadavg`) -- no `psutil`, no third-party dependency
    (04-build-plan-and-roadmap.md section 5). Every source here is
    best-effort: `resource` doesn't exist on Windows and `getloadavg`
    can be unavailable even on POSIX (e.g. some containers), so each is
    wrapped and simply omitted from the result rather than failing the
    whole publish -- a partial gauge set is still useful, a crashed
    publisher is not.
    """
    gauges: dict = {"threads": threading.active_count(), "cpu_count": os.cpu_count() or 0}
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        # `ru_maxrss` is KB on Linux, bytes on macOS/BSD -- the stdlib
        # gives no portable unit, so this is the one platform check
        # needed to make the gauge mean the same thing everywhere.
        divisor = 1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0
        gauges["rss_mb"] = round(usage.ru_maxrss / divisor, 2)
        gauges["user_cpu_s"] = round(usage.ru_utime, 3)
        gauges["sys_cpu_s"] = round(usage.ru_stime, 3)
    except (ImportError, AttributeError, OSError):
        pass
    try:
        load1, load5, load15 = os.getloadavg()
        gauges["load1"], gauges["load5"], gauges["load15"] = round(load1, 2), round(load5, 2), round(load15, 2)
    except (AttributeError, OSError):
        pass
    return gauges


class ProcessMetricsPublisher:
    """Periodic `system.metrics{subsystem: "process"}` publisher -- the
    Kernel's own process, since it is the one process every `single`-mode
    subsystem runs inside of (03-kernel.md section 5.1). Same channel,
    same `StatusServer`/`MetricsTable` aggregation every other
    subsystem's gauges already go through; no wiring changes needed
    there."""

    def __init__(self, *, bus: Bus, clock: Clock, interval_s: float, source: str = "kernel") -> None:
        self._bus = bus
        self._clock = clock
        self._interval = max(1.0, interval_s)
        self._source = source
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="kernel-process-metrics")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def publish_once(self) -> None:
        await self._bus.publish(Message.new(
            topics.SYSTEM_METRICS, source=self._source,
            payload={"subsystem": "process", "counters": {}, "gauges": process_gauges()},
            clock=self._clock.now,
        ))

    async def _loop(self) -> None:
        while True:
            await self._clock.sleep(self._interval)
            try:
                await self.publish_once()
            except Exception:  # noqa: BLE001 -- metrics reporting must never crash the loop
                pass


class MetricsHistoryWriter:
    """Periodic snapshot of `MetricsTable.per_subsystem` into the
    dedicated `metrics:history` Ledger stream (see module docstring for
    why not `trace:<trace_id>`). One append per tick regardless of how
    many subsystems are reporting -- cheap, and keeps `/api/history`'s
    read side to one stream instead of fanning out per subsystem."""

    def __init__(self, *, ledger: Ledger, clock: Clock, metrics: MetricsTable, interval_s: float) -> None:
        self._ledger = ledger
        self._clock = clock
        self._metrics = metrics
        self._interval = max(1.0, interval_s)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="kernel-metrics-history")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def snapshot_once(self) -> None:
        if not self._metrics.per_subsystem:
            return  # nothing reported yet -- an empty snapshot is noise, not signal
        now = self._clock.now()
        await self._ledger.append(HISTORY_STREAM, Event(
            stream=HISTORY_STREAM, type=HISTORY_EVENT_TYPE, ts=now, trace_id=str(uuid.uuid4()),
            causation_id=None, payload={"metrics": copy.deepcopy(self._metrics.per_subsystem)},
        ))

    async def _loop(self) -> None:
        while True:
            await self._clock.sleep(self._interval)
            try:
                await self.snapshot_once()
            except Exception:  # noqa: BLE001 -- history is observability, never allowed to crash the Kernel
                pass


__all__ = [
    "HISTORY_EVENT_TYPE", "HISTORY_STREAM", "MetricsHistoryWriter", "MetricsTable", "ProcessMetricsPublisher",
    "StatusServer", "process_gauges",
]
