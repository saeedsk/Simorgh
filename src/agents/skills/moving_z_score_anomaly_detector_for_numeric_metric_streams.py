"""Moving z-score anomaly detector for numeric metric streams."""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Iterable, Iterator, NamedTuple, Optional, Union


class AnomalyResult(NamedTuple):
    """Result of an anomaly detection check on a single metric point."""

    value: float
    is_anomaly: bool
    z_score: float
    mean: float
    std: float
    timestamp: Any = None

    def __bool__(self) -> bool:
        """Allow evaluating the result directly as a boolean anomaly flag."""
        return self.is_anomaly


class MovingZScoreDetector:
    """Online streaming moving z-score anomaly detector.

    Maintains a sliding window of historical observations and evaluates
    incoming numeric values against the moving mean and standard deviation.
    """

    def __init__(
        self,
        window_size: int = 30,
        threshold: float = 3.0,
        min_periods: Optional[int] = None,
        ddof: int = 1,
        update_on_anomaly: bool = True,
        eps: float = 1e-9,
    ) -> None:
        if window_size < 2:
            raise ValueError(f"window_size must be >= 2, got {window_size}")
        if threshold <= 0:
            raise ValueError(f"threshold must be positive, got {threshold}")
        if ddof not in (0, 1):
            raise ValueError(f"ddof must be 0 or 1, got {ddof}")

        if min_periods is None:
            min_periods = max(ddof + 1, min(window_size, 5))
        elif min_periods < ddof + 1:
            raise ValueError(f"min_periods must be >= {ddof + 1}, got {min_periods}")
        elif min_periods > window_size:
            raise ValueError(f"min_periods cannot exceed window_size ({window_size})")

        self.window_size = window_size
        self.threshold = threshold
        self.min_periods = min_periods
        self.ddof = ddof
        self.update_on_anomaly = update_on_anomaly
        self.eps = eps

        self._window: deque[float] = deque(maxlen=window_size)

    def update(self, value: float, timestamp: Any = None) -> AnomalyResult:
        """Process a new value and return whether it is an anomaly."""
        val = float(value)
        if not math.isfinite(val):
            raise ValueError(f"Metric value must be finite, got {val}")

        n = len(self._window)
        if n < self.min_periods:
            self._window.append(val)
            running_mean = sum(self._window) / len(self._window)
            return AnomalyResult(
                value=val,
                is_anomaly=False,
                z_score=0.0,
                mean=running_mean,
                std=0.0,
                timestamp=timestamp,
            )

        # Compute baseline statistics from existing window
        mean = sum(self._window) / n
        denom = n - self.ddof
        variance = sum((x - mean) ** 2 for x in self._window) / denom if denom > 0 else 0.0
        std = math.sqrt(max(0.0, variance))

        diff = val - mean
        if std > self.eps:
            z_score = diff / std
        else:
            if abs(diff) <= self.eps:
                z_score = 0.0
            else:
                z_score = float("inf") if diff > 0 else float("-inf")

        is_anomaly = abs(z_score) >= self.threshold

        if not is_anomaly or self.update_on_anomaly:
            self._window.append(val)

        return AnomalyResult(
            value=val,
            is_anomaly=is_anomaly,
            z_score=z_score,
            mean=mean,
            std=std,
            timestamp=timestamp,
        )

    def batch_update(
        self,
        stream: Iterable[Union[float, int, tuple[Any, float], dict[str, Any]]],
    ) -> list[AnomalyResult]:
        """Process multiple points in sequence and return list of results."""
        results: list[AnomalyResult] = []
        for item in stream:
            if isinstance(item, dict):
                ts = item.get("timestamp", item.get("time"))
                val = item.get("value")
                if val is None:
                    val = item.get("val", item.get("metric"))
                results.append(self.update(val, timestamp=ts))
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                ts, val = item
                results.append(self.update(val, timestamp=ts))
            else:
                results.append(self.update(item))  # type: ignore[arg-type]
        return results

    def reset(self) -> None:
        """Reset detector state."""
        self._window.clear()

    @property
    def window(self) -> list[float]:
        """Return the current contents of the sliding window."""
        return list(self._window)

    @property
    def current_mean(self) -> Optional[float]:
        """Return the mean of the current window, or None if empty."""
        if not self._window:
            return None
        return sum(self._window) / len(self._window)

    @property
    def current_std(self) -> Optional[float]:
        """Return the standard deviation of the current window, or None if empty."""
        n = len(self._window)
        if n == 0:
            return None
        if n <= self.ddof:
            return 0.0
        m = sum(self._window) / n
        v = sum((x - m) ** 2 for x in self._window) / (n - self.ddof)
        return math.sqrt(max(0.0, v))

    def __len__(self) -> int:
        return len(self._window)


def detect_anomalies(
    stream: Iterable[Union[float, int, tuple[Any, float], dict[str, Any]]],
    window_size: int = 30,
    threshold: float = 3.0,
    min_periods: Optional[int] = None,
    ddof: int = 1,
    update_on_anomaly: bool = True,
) -> Iterator[AnomalyResult]:
    """Detect anomalies in a stream of numeric values, tuples, or dicts."""
    detector = MovingZScoreDetector(
        window_size=window_size,
        threshold=threshold,
        min_periods=min_periods,
        ddof=ddof,
        update_on_anomaly=update_on_anomaly,
    )
    for item in stream:
        if isinstance(item, dict):
            ts = item.get("timestamp", item.get("time"))
            val = item.get("value")
            if val is None:
                val = item.get("val", item.get("metric"))
            yield detector.update(val, timestamp=ts)
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            ts, val = item
            yield detector.update(val, timestamp=ts)
        else:
            yield detector.update(item)  # type: ignore[arg-type]