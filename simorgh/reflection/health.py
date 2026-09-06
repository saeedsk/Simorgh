"""Health/stability monitoring (spec section 5.1) -- a straight port of
v1's `src/orchestrator/health.py` `HealthMonitor`, adapted from "all of
window pinned" to "the last `pinned_n` consecutive transitions pinned"
per this spec's own thresholds, and from a return-a-list-of-issues shape
to a single current `Finding` plus change-only emission (the caller only
publishes `reflect.health.finding` when severity actually changes --
see `service.py` -- so a persistently-critical state doesn't spam one
event per `persona.state.changed`).

Pure and synchronous by design (spec section 5, "Internal design"): this
must keep working with zero providers, so it never calls out to anything.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config

INFO = "info"
WARN = "warn"
CRITICAL = "critical"

NONE = "none"
REQUEST_RESET = "request_reset"


@dataclass(frozen=True)
class Sample:
    valence: float
    arousal: float
    cognitive_load: float
    source: str
    ts: float


@dataclass(frozen=True)
class Finding:
    severity: str  # info | warn | critical
    detail: str
    action_taken: str  # none | request_reset | request_pause_hint


class HealthMonitor:
    """Ring buffer of the last `window` persona-state transitions. Call
    `observe()` on every non-loop-guarded `persona.state.changed`, then
    `inspect()` to get the *current* finding (not a diff) -- the caller
    decides whether it's worth emitting by comparing to the last severity
    it saw.
    """

    def __init__(self, config: Config | None = None) -> None:
        self._config = config or Config()
        self._buf: list[Sample] = []

    def observe(self, valence: float, arousal: float, cognitive_load: float, source: str, ts: float) -> None:
        if source == "health_reset":
            # Loop guard (spec section 3.1): the reset we ourselves
            # requested is not a fresh signal to re-inspect.
            return
        self._buf.append(Sample(valence, arousal, cognitive_load, source, ts))
        if len(self._buf) > self._config.health_window:
            self._buf = self._buf[-self._config.health_window :]

    def inspect(self) -> Finding | None:
        c = self._config
        buf = self._buf
        if not buf:
            return None

        pinned_tail = buf[-c.health_pinned_n :]
        if len(pinned_tail) >= c.health_pinned_n:
            if all(abs(s.valence) >= c.health_extreme for s in pinned_tail):
                return Finding(CRITICAL, f"valence pinned at an extreme for the last {len(pinned_tail)} transitions", REQUEST_RESET)
            if all(abs(s.arousal) >= c.health_extreme for s in pinned_tail):
                return Finding(CRITICAL, f"arousal pinned at an extreme for the last {len(pinned_tail)} transitions", REQUEST_RESET)

        if len(buf) >= c.health_window and all(s.cognitive_load >= c.health_load_ceiling for s in buf):
            return Finding(CRITICAL, f"cognitive load has stayed at or above {c.health_load_ceiling} across the window", REQUEST_RESET)

        flips = sum(
            1 for a, b in zip(buf, buf[1:])
            if a.valence != 0 and b.valence != 0 and (a.valence > 0) != (b.valence > 0)
        )
        if flips >= c.health_oscillation_critical:
            return Finding(CRITICAL, f"valence is oscillating rapidly ({flips} sign flips in the window)", REQUEST_RESET)
        if flips >= c.health_oscillation_warn:
            return Finding(WARN, f"valence is oscillating ({flips} sign flips in the window)", NONE)

        # 3-pinned warn, per spec section 5.1 ("warn at 6 flips or 3 pinned")
        if len(pinned_tail) >= 3:
            near = pinned_tail[-3:]
            if all(abs(s.valence) >= c.health_extreme for s in near) or all(abs(s.arousal) >= c.health_extreme for s in near):
                return Finding(WARN, "valence or arousal has been pinned at an extreme for 3 recent transitions", NONE)

        return None
