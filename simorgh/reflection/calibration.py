"""Calibration tracking (spec section 5, `CalibrationTable`): stated
confidence vs. empirical outcome, per task type, with a Brier score and
binned accuracy. Requires `calibration_min_samples` before emitting
anything, to avoid noise from a handful of samples (spec section 3.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config


@dataclass(frozen=True)
class Calibration:
    task_type: str
    stated_confidence: float  # mean stated confidence in-window
    empirical_accuracy: float  # hit rate in-window
    brier: float
    samples: int
    bins: tuple[tuple[float, float, int, int], ...]  # (lo, hi, n, hits)


class CalibrationTable:
    def __init__(self, config: Config | None = None) -> None:
        self._config = config or Config()
        self._by_type: dict[str, list[tuple[float, bool]]] = {}

    def record(self, task_type: str, stated: float, hit: bool) -> None:
        self._by_type.setdefault(task_type, []).append((stated, hit))

    def summary(self, task_type: str) -> Calibration | None:
        samples = self._by_type.get(task_type, [])
        if len(samples) < self._config.calibration_min_samples:
            return None

        n_bins = self._config.calibration_bins
        edges = [i / n_bins for i in range(n_bins + 1)]
        bins: list[list[float | int]] = [[edges[i], edges[i + 1], 0, 0] for i in range(n_bins)]
        brier_sum = 0.0
        for stated, hit in samples:
            idx = min(int(stated * n_bins), n_bins - 1)
            bins[idx][2] += 1
            if hit:
                bins[idx][3] += 1
            brier_sum += (stated - (1.0 if hit else 0.0)) ** 2

        mean_stated = sum(s for s, _ in samples) / len(samples)
        accuracy = sum(1 for _, h in samples if h) / len(samples)
        return Calibration(
            task_type=task_type,
            stated_confidence=mean_stated,
            empirical_accuracy=accuracy,
            brier=brier_sum / len(samples),
            samples=len(samples),
            bins=tuple(tuple(b) for b in bins),  # type: ignore[misc]
        )

    def task_types(self) -> list[str]:
        return list(self._by_type)
