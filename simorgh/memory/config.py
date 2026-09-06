"""Memory configuration (docs/blueprint/subsystems/05-memory.md section
3.5). Every field has a working default -- `[memory]` may be absent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .api import DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS


@dataclass(frozen=True)
class Config:
    half_life_seconds: float = DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS
    working_max_turns: int = 20
    working_max_chars: int = 8_000
    default_k: int = 5
    recency_weight: float = 0.1  # scoring: similarity*confidence + recency_weight*recency_bonus

    @classmethod
    def from_mapping(cls, raw: Mapping) -> "Config":
        if not raw:
            return cls()
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


__all__ = ["Config"]
