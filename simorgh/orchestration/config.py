"""`simorgh.toml [orchestration]` (16 section 3.5). Only `workers` is
actually read by `Service` this session; the remaining keys are declared
so the config surface matches the spec and later work has somewhere to
read them from without another contracts-shaped decision.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    workers: int = 1
    lease_seconds: int = 600
    heartbeat_s: int = 30
    max_depth: int = 3
    max_children_concurrent: int = 4
    think_timeout_s: float = 120.0
    needs_human_timeout_s: float = 600.0
    metrics_interval_s: float = 3.0  # 0 disables the periodic `system.metrics` publish

    @classmethod
    def from_mapping(cls, data: dict) -> "Config":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
