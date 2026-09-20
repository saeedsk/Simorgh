"""Calibration tracking (spec section 5, `CalibrationTable`): stated
confidence vs. empirical outcome, per task type, with a Brier score and
binned accuracy. Requires `calibration_min_samples` before emitting
anything, to avoid noise from a handful of samples (spec section 3.5).
"""

from __future__ import annotations

import math
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
        self._unusable: dict[str, int] = {}

    def record(self, task_type: str, stated: float, hit: bool) -> bool:
        """Record one (stated confidence, outcome) pair. False means the
        sample was unusable and was NOT recorded.

        A stated confidence is a probability, and only `critique.py`
        ever clamped one: `_on_outcome_recorded`, `_on_verify_result`
        and `_on_task_terminal` all pass the wire value through with
        nothing but an `isinstance(x, (int, float))` check, which NaN,
        inf and -3.0 all satisfy. Each of those used to reach
        `summary()` and take the whole pass down with it -- `-3.0`
        indexed `bins[-30]` (IndexError), NaN and inf died in `int()`
        -- and because the pass loops over task types, every type after
        the bad one silently never published, on that tick and every
        tick after (observer bulk5-02, 2026-09-10).

        Discarded rather than clamped, deliberately: clamping -3.0 to
        0.0 would fold a producer's bug into a confident-looking
        calibration figure, and this subsystem's whole job is to be the
        thing that says something true. `unusable()` keeps the count so
        "could not measure" stays distinguishable from "measured".
        """
        value = float(stated)
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            self._unusable[task_type] = self._unusable.get(task_type, 0) + 1
            return False
        self._by_type.setdefault(task_type, []).append((value, hit))
        return True

    def unusable(self, task_type: str) -> int:
        """Samples dropped by `record` for this task type."""
        return self._unusable.get(task_type, 0)

    def summary(self, task_type: str) -> Calibration | None:
        samples = self._by_type.get(task_type, [])
        if len(samples) < self._config.calibration_min_samples:
            return None

        # `max(1, ...)`: `[reflection] calibration.bins = 0` is a
        # misconfiguration, not a reason for the pass to die on a
        # ZeroDivisionError in `i / n_bins` before anything is
        # published.
        n_bins = max(1, self._config.calibration_bins)
        edges = [i / n_bins for i in range(n_bins + 1)]
        bins: list[list[float | int]] = [[edges[i], edges[i + 1], 0, 0] for i in range(n_bins)]
        brier_sum = 0.0
        for stated, hit in samples:
            idx = min(max(int(stated * n_bins), 0), n_bins - 1)
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
