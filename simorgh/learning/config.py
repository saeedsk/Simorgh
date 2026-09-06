"""`[learning]` config (docs/blueprint/subsystems/11-learning.md section
3.5) -- a subset scoped to what this build actually implements (see
README's build log for what is deferred)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Config:
    max_draft_attempts: int = 3
    max_pipeline_wall_seconds: float = 900.0
    action_timeout_seconds: float = 60.0
    verify_timeout_seconds: float = 300.0
    hot_swap_slots: tuple[str, ...] = ("logic", "emotion", "skills")
    explore_bonus: float = 0.15
    min_samples_for_trust: int = 5
    blocked_sample_weight: float = 0.5
    max_concurrent_pipelines: int = 2

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Config":
        data = dict(data or {})
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})
