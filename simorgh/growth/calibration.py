"""Per-area calibration: stated confidence vs. empirical outcome.

Records every patch attempt's stated confidence and whether it actually
succeeded, computes a per-area calibration delta (stated minus empirical),
and exposes a correction factor the competence estimator can use to shrink
stated confidence toward empirical success.

Complements `simorgh/growth/monitors/calibration.py` (which computes Brier
scores over task types from the ledger) by being the write-side record the
estimator consumes: `record()` on each attempt, `delta()`/`correction_factor()`
per area, backed by the shared memory bus when one is available and by an
in-memory dict otherwise.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Callable

# Number of pseudo-observations in the shrinkage prior. With few samples the
# correction stays near 1 (no correction); it strengthens as evidence grows.
PRIOR_WEIGHT = 10.0


class CalibrationTable:
    """Stated confidence vs. empirical outcome, per area."""

    def __init__(self, *, bus: object | None = None, topic: str = "learn:calibration"):
        self._bus = bus
        self._topic = topic
        self._entries: dict[str, list[tuple[float, bool]]] = defaultdict(list)

    def record(self, task_type: str, stated_confidence: float, succeeded: bool) -> None:
        """Record one attempt: what we said and what actually happened."""
        stated = float(stated_confidence)
        if not 0.0 <= stated <= 1.0:
            raise ValueError(f"stated_confidence must be in [0,1], got {stated}")
        self._entries[task_type].append((stated, bool(succeeded)))
        if self._bus is not None and hasattr(self._bus, "publish"):
            self._bus.publish(self._topic, {
                "task_type": task_type,
                "stated_confidence": stated,
                "succeeded": bool(succeeded),
            })

    def stated_mean(self, area: str) -> float | None:
        entries = self._entries.get(area)
        if not entries:
            return None
        return sum(c for c, _ in entries) / len(entries)

    def empirical_rate(self, area: str) -> float | None:
        entries = self._entries.get(area)
        if not entries:
            return None
        return sum(1 for _, ok in entries if ok) / len(entries)

    def delta(self, area: str) -> float | None:
        """stated mean minus empirical rate. Positive = overconfident."""
        stated = self.stated_mean(area)
        empirical = self.empirical_rate(area)
        if stated is None or empirical is None:
            return None
        return stated - empirical

    def samples(self, area: str) -> int:
        return len(self._entries.get(area, ()))

    def correction_factor(self, area: str) -> float | None:
        """Factor to multiply a stated confidence by to calibrate it.

        Shrinkage toward the empirical rate:
            factor = 1 + (n / (n + PRIOR_WEIGHT)) * (empirical / stated - 1)
        Returns None (meaning "no correction known"; callers treat as 1) when
        there is no evidence or the stated mean is zero.
        """
        stated = self.stated_mean(area)
        empirical = self.empirical_rate(area)
        n = self.samples(area)
        if stated is None or empirical is None or n == 0 or stated <= 0.0:
            return None
        weight = n / (n + PRIOR_WEIGHT)
        factor = 1.0 + weight * (empirical / stated - 1.0)
        cap = 1.0 / stated
        return max(0.0, min(cap, factor))

    def areas(self) -> list[str]:
        return sorted(self._entries)

    def to_json(self) -> str:
        return json.dumps({a: [[c, 1 if ok else 0] for c, ok in e]
                           for a, e in self._entries.items()})

    def load_json(self, raw: str) -> None:
        for area, pairs in json.loads(raw).items():
            for c, ok in pairs:
                self._entries[area].append((float(c), bool(ok)))


def attach_estimator(table: CalibrationTable, estimator: object,
                     *, area_of: Callable[[str], str] | None = None) -> None:
    """Wire a calibration correction into a competence estimator.

    If the estimator exposes `set_calibration_hook`, install one; otherwise
    set a `calibration_correction(area) -> float` attribute it can call.
    """
    def correction(task_type: str) -> float:
        area = area_of(task_type) if area_of else task_type
        factor = table.correction_factor(area)
        return factor if factor is not None else 1.0

    if hasattr(estimator, "set_calibration_hook"):
        estimator.set_calibration_hook(correction)
    else:
        estimator.calibration_correction = correction  # type: ignore[attr-defined]
