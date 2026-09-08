"""`[planning]` config (spec section 3.5)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    lease_seconds: float = 600.0
    max_task_attempts: int = 3
    max_blocked_retries: int = 9
    blocked_retry_delay_seconds: float = 300.0
    # A task that only ran out of steps comes back this soon, with a
    # fresh budget and a memory of the attempt (see service.py's
    # `_retry_delay`). Its tool results are still fresh; waiting the
    # full blocked delay just made a long task slower.
    continuation_delay_seconds: float = 10.0
    dedupe_similarity_threshold: float = 0.45
    project_step_count: int = 4
    # Path prefixes a decomposed patch step may target. `simorgh/` is
    # the live tree; `src/` is v1, retired but not deleted, and kept
    # here only so a step naming it is not silently dropped.
    source_roots: tuple[str, ...] = ("simorgh/", "src/")
    max_plan_revisions: int = 2
    auto_approve_max_risk: str = "medium"
    human_approval_timeout_seconds: float = 3600.0
    regrounding_age_seconds: float = 21600.0
    reground_after_sibling_failure: bool = True
    stalled_after_seconds: float = 1800.0
    priority_weights: dict = field(default_factory=lambda: {"human": 3, "reflection": 2, "curiosity": 1})
    leader: bool = True
    # A decomposition or re-grounding is a real model call. This was an
    # unconfigurable 8.0s in `bridge.py`, and every replan measured at
    # exactly 8.0s -> None -> no steps (watched trial, 2026-09-07).
    # Matches the Worker's `think_timeout_s`.
    think_timeout_s: float = 120.0

    @classmethod
    def from_mapping(cls, data: dict | None) -> "Config":
        data = dict(data or {})
        lease = os.environ.get("SIMORGH_PLANNING_LEASE_SECONDS")
        if lease is not None:
            data["lease_seconds"] = float(lease)
        fields = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**fields)


__all__ = ["Config"]
