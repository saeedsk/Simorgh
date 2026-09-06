"""Memory's internal value types (docs/blueprint/subsystems/05-memory.md
section 3.4)."""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS = 30 * 24 * 60 * 60  # 30 days, ported from v1


@dataclass(frozen=True)
class MemoryItem:
    ref: str
    kind: str
    content: str
    tags: tuple[str, ...]
    confidence: float
    ts: float
    source_ref: str = ""

    def score_confidence(self, *, now: float, half_life_seconds: float, penalty: float = 1.0) -> float:
        """Exponential decay from creation, times any contradiction
        penalty folded in from later `contradiction.flagged` events (05
        section 5) -- ported from v1 `MemoryStore.score_confidence`,
        simplified to decay-from-creation only (no reconfirmation
        tracking this build session; see README "What's not built yet")."""
        if half_life_seconds <= 0:
            return self.confidence * penalty
        elapsed = max(0.0, now - self.ts)
        return self.confidence * penalty * (0.5 ** (elapsed / half_life_seconds))


@dataclass(frozen=True)
class Turn:
    request_text: str
    response_text: str
    ts: float


__all__ = ["DEFAULT_CONFIDENCE_HALF_LIFE_SECONDS", "MemoryItem", "Turn"]
