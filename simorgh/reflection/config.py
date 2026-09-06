"""`simorgh.toml [reflection]` (spec section 3.5)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    health_window: int = 12
    health_extreme: float = 0.9
    health_pinned_n: int = 5
    health_load_ceiling: float = 0.95
    health_oscillation_warn: int = 6
    health_oscillation_critical: int = 8

    drift_check_every_steps: int = 8
    drift_heuristic_threshold: float = 0.5
    drift_emit_threshold: float = 0.6
    stall_idle_seconds: float = 1800.0

    critique_max_tokens: int = 400

    pattern_window_seconds: float = 86400.0
    pattern_min_rate: float = 0.5
    pattern_min_samples: int = 3

    calibration_bins: int = 10
    calibration_min_samples: int = 10

    review_timeout_s: float = 8.0
    max_concurrent_reviews: int = 2

    @classmethod
    def from_mapping(cls, data: dict | None) -> "Config":
        data = data or {}
        health = data.get("health") or {}
        drift = data.get("drift") or {}
        pattern = data.get("pattern") or {}
        calibration = data.get("calibration") or {}
        return cls(
            health_window=int(health.get("window", 12)),
            health_extreme=float(health.get("extreme", 0.9)),
            health_pinned_n=int(health.get("pinned_n", 5)),
            health_load_ceiling=float(health.get("load_ceiling", 0.95)),
            health_oscillation_warn=int(health.get("oscillation_flips_warn", 6)),
            health_oscillation_critical=int(health.get("oscillation_flips_critical", 8)),
            drift_check_every_steps=int(data.get("drift_check_every_steps", 8)),
            drift_heuristic_threshold=float(data.get("drift_heuristic_threshold", 0.5)),
            drift_emit_threshold=float(data.get("drift_emit_threshold", 0.6)),
            stall_idle_seconds=float(data.get("stall_idle_seconds", 1800.0)),
            critique_max_tokens=int(data.get("critique_max_tokens", 400)),
            pattern_window_seconds=float(pattern.get("window_seconds", 86400.0)),
            pattern_min_rate=float(pattern.get("min_rate", 0.5)),
            pattern_min_samples=int(pattern.get("min_samples", 3)),
            calibration_bins=int(calibration.get("bins", 10)),
            calibration_min_samples=int(calibration.get("min_samples", 10)),
        )
