"""Stability watchdog: detects and corrects pathological drift in the
persona's affective state.

Grounded in a homeostasis model from affective neuroscience: a healthy
affect system doesn't just react, it actively regulates itself back toward
a viable range. HealthMonitor is that regulatory reflex sitting alongside
PersonaState.decay_toward_baseline -- decay handles gentle, routine
settling; HealthMonitor handles genuine pathology (state stuck, pinned, or
oscillating) that decay alone won't fix in time. See docs/EVOLUTION.md,
"Self-Healing."
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.persona_state import EmotionalState


class Severity(Enum):
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class StabilityIssue:
    severity: Severity
    description: str


class HealthMonitor:
    """Inspects a window of recent EmotionalState history for pinned
    extremes, sustained overload, or rapid oscillation, and can enforce a
    corrective reset when something CRITICAL is found.
    """

    def __init__(
        self,
        window: int = 5,
        extreme_threshold: float = 0.95,
        high_load_threshold: float = 0.9,
    ) -> None:
        if window < 2:
            raise ValueError("window must be at least 2")
        self._window = window
        self._extreme_threshold = extreme_threshold
        self._high_load_threshold = high_load_threshold

    def check(self, history: list[EmotionalState]) -> list[StabilityIssue]:
        recent = history[-self._window :]
        issues: list[StabilityIssue] = []

        if len(recent) < self._window:
            return issues

        if all(abs(s.valence) >= self._extreme_threshold for s in recent):
            issues.append(
                StabilityIssue(
                    Severity.CRITICAL,
                    f"valence pinned at an extreme for the last {len(recent)} transitions",
                )
            )
        if all(abs(s.arousal) >= self._extreme_threshold for s in recent):
            issues.append(
                StabilityIssue(
                    Severity.CRITICAL,
                    f"arousal pinned at an extreme for the last {len(recent)} transitions",
                )
            )
        if all(s.cognitive_load >= self._high_load_threshold for s in recent):
            issues.append(
                StabilityIssue(
                    Severity.WARNING,
                    "cognitive load has stayed at or above "
                    f"{self._high_load_threshold} for the last {len(recent)} transitions",
                )
            )

        sign_flips = sum(
            1
            for a, b in zip(recent, recent[1:])
            if a.valence != 0 and b.valence != 0 and (a.valence > 0) != (b.valence > 0)
        )
        if sign_flips >= self._window - 1:
            issues.append(
                StabilityIssue(
                    Severity.WARNING,
                    "valence is oscillating between positive and negative rapidly",
                )
            )

        return issues

    def enforce(self, bus: SharedMemoryBus) -> list[StabilityIssue]:
        """Check the bus's PersonaState history and, if any CRITICAL issue
        is found, reset mood to a safe neutral baseline. Cognitive load is
        left untouched -- being busy isn't itself an emergency. Returns the
        issues found (prior to any correction).
        """
        issues = self.check(bus.persona_state.history())
        if any(issue.severity is Severity.CRITICAL for issue in issues):
            bus.publish_state("health_monitor", valence=0.0, arousal=0.0)
        return issues
