"""Delivery counters and gauges, snapshotted into `system.metrics`
(docs/blueprint/subsystems/01-bus.md section 3.2). Plain dicts, no
locking: everything that touches them runs on the event loop."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class Metrics:
    counters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    per_type: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    request_latencies_ms: list[float] = field(default_factory=list)

    def inc(self, counter: str, type_name: str | None = None, n: int = 1) -> None:
        self.counters[counter] += n
        if type_name is not None:
            self.per_type[counter][type_name] += n

    def observe_request_latency(self, ms: float) -> None:
        self.request_latencies_ms.append(ms)
        if len(self.request_latencies_ms) > 1000:
            del self.request_latencies_ms[: len(self.request_latencies_ms) - 1000]

    def p50_request_ms(self) -> float:
        if not self.request_latencies_ms:
            return 0.0
        ordered = sorted(self.request_latencies_ms)
        return ordered[len(ordered) // 2]

    def snapshot(self, depths: dict[str, int], inflight: dict[str, int]) -> dict:
        """The `system.metrics` payload body for `subsystem: "bus"`."""
        gauges: dict = {f"queue_depth.{g}": d for g, d in depths.items()}
        gauges.update({f"inflight.{g}": n for g, n in inflight.items()})
        gauges["request_latency_ms_p50"] = self.p50_request_ms()
        return {"subsystem": "bus", "counters": dict(self.counters), "gauges": gauges}


__all__ = ["Metrics"]
