"""`[learning]` config: the three knobs the outcome record and the
strategy ranking read. The six PatchPipeline keys (`max_draft_attempts`,
`max_pipeline_wall_seconds`, `action_timeout_seconds`,
`verify_timeout_seconds`, `hot_swap_slots`, `max_concurrent_pipelines`)
were removed on 2026-09-19; the pipeline itself retired on 2026-09-18.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Config:
    explore_bonus: float = 0.15
    min_samples_for_trust: int = 5
    blocked_sample_weight: float = 0.5

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Config":
        data = dict(data or {})
        allowed = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in allowed})
