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

    # -- distillation (distillation.py): turn a solved, tool-using
    # task into a reusable skill without being asked. Capped hard,
    # because the failure mode of eagerness is a skills directory
    # full of near-duplicates nobody trusts.
    distillation_enabled: bool = True
    max_distillations_per_day: int = 3
    skill_dir: str = "simorgh_skills"

    pattern_window_seconds: float = 86400.0
    pattern_min_rate: float = 0.5
    pattern_min_samples: int = 3
    # Repeated Guardian denials. One denial is Guardian working; the
    # same denial five times in an hour is a defect or a bad habit,
    # and either way it is Sim's job to raise, not the creator's to
    # read off the terminal (reflection/denials.py).
    denial_window_seconds: float = 3600.0
    denial_min_repeats: int = 5

    # -- monitors, alerts and the daily digest (digest.py;
    # platform-connectors-design.md section 6). Off until something
    # registers a monitor: an empty registry costs one dict lookup a
    # tick, but a digest that arrives every morning saying nothing at
    # all trains a person to delete it unread.
    monitors_enabled: bool = True
    #: One `warn` per monitor per window. The failure mode of a notifier
    #: is not silence, it is twenty messages in a minute.
    alert_warn_window_s: float = 3600.0
    #: `"22:00-07:00"`, or "" for none. Holds back `warn`, never
    #: `critical` -- see digest.py.
    quiet_hours: str = ""
    digest_enabled: bool = True
    #: Local hour the daily digest goes out.
    digest_hour: int = 8
    #: Sim speaks a critical alert aloud. Needs the `home` subsystem;
    #: until that exists this stays off and criticals go to `notify`.
    announce_critical: bool = False

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
            denial_window_seconds=float(data.get("denial_window_seconds", cls.denial_window_seconds)),
            denial_min_repeats=int(data.get("denial_min_repeats", cls.denial_min_repeats)),
            monitors_enabled=bool(data.get("monitors_enabled", cls.monitors_enabled)),
            alert_warn_window_s=float(data.get("alert_warn_window_s", cls.alert_warn_window_s)),
            quiet_hours=str(data.get("quiet_hours", cls.quiet_hours)),
            digest_enabled=bool(data.get("digest_enabled", cls.digest_enabled)),
            digest_hour=int(data.get("digest_hour", cls.digest_hour)),
            announce_critical=bool(data.get("announce_critical", cls.announce_critical)),
            calibration_bins=int(calibration.get("bins", 10)),
            calibration_min_samples=int(calibration.get("min_samples", 10)),
            # These two were absent from this call entirely -- not read
            # into a nested/differently-named key, simply never passed
            # to `cls(...)` at all, so the dataclass default always won
            # regardless of what simorgh.toml said. An observer proved
            # it live 2026-09-08: writing max_concurrent_reviews=6 left
            # the running semaphore at the default of 2.
            review_timeout_s=float(data.get("review_timeout_s", cls.review_timeout_s)),
            max_concurrent_reviews=int(data.get("max_concurrent_reviews", cls.max_concurrent_reviews)),
        )
