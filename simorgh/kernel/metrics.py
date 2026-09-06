"""Aggregates `system.metrics`/`system.health` into in-memory tables
(justified caches -- section 4: derivable from the `system` stream on
replay, not the durable record itself) and answers
`system.status.request` (docs/blueprint/subsystems/03-kernel.md section
3.3). Timeout expectation for the reply is 2s -- everything here is
already in memory, no Ledger read on the hot path.
"""

from __future__ import annotations

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import Bus, Clock

from .state import SystemStateMachine
from .supervisor import Supervisor


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


__all__ = ["MetricsTable", "StatusServer"]
