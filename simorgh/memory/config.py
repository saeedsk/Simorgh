"""Memory configuration (docs/blueprint/subsystems/05-memory.md section
3.5). Every field has a working default -- `[memory]` may be absent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .api import DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS


@dataclass(frozen=True)
class Config:
    half_life_seconds: float = DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS
    # `WorkingMemory`'s bounds (`store.py`) -- consumed at construction,
    # but there is no real producer yet: nothing publishes
    # `memory.store{kind:"working"}` outside tests, so these bounds
    # currently have no traffic to bound. See `store.py`'s
    # `WorkingMemory` docstring for why that gap is left open rather
    # than force-wired.
    working_max_turns: int = 20
    working_max_chars: int = 8_000
    # Unreachable by design (2026-09-08 observer audit): `service.py`'s
    # `_on_retrieve` falls back to this only when a `memory.retrieve`
    # payload omits `k`, but the wire contract
    # (`contracts/messages/memory.py`) declares `k` a *required* field,
    # so `Message.new(...)` raises before the fallback could ever run.
    # Both real publishers -- `execution/service.py`'s skill-description
    # lookup (k=3, tuned to that narrow lookup) and
    # `orchestration/context.py`'s context build (k=8, paired with its
    # own `items[:8]` slice and char budget) -- pass `k` explicitly and
    # have a specific reason for their own value, so there is no
    # "should omit k" caller to fix here. Setting this in simorgh.toml
    # changes nothing; `kernel/configcheck.py`'s `KNOWN_DEAD_FIELDS`
    # calls that out explicitly since the ordinary dead-section probe
    # cannot (the field parses into a real, different value -- it is
    # just never read).
    default_k: int = 5
    recency_weight: float = 0.1  # scoring: similarity*confidence + recency_weight*recency_bonus

    @classmethod
    def from_mapping(cls, raw: Mapping) -> "Config":
        if not raw:
            return cls()
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


__all__ = ["Config"]
