"""`EmotionalState` + `MoodEngine` -- a port of v1's
`src/orchestrator/persona_state.py` onto an injected `Clock` (instead of
`time.monotonic()`) and a `Ledger` stream (`persona:state`) instead of an
in-process-only object, so mood survives a restart and multiple
processes can converge on the same state. Persona is the single writer.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class EmotionalState:
    valence: float = 0.0
    arousal: float = 0.0
    cognitive_load: float = 0.0
    ts: float = 0.0

    @property
    def valence_label(self) -> Literal["negative", "neutral", "positive"]:
        if self.valence > 0.15:
            return "positive"
        if self.valence < -0.15:
            return "negative"
        return "neutral"

    @property
    def arousal_label(self) -> Literal["low", "moderate", "high"]:
        if self.arousal > 0.5:
            return "high"
        if self.arousal > 0.15:
            return "moderate"
        return "low"

    def to_dict(self) -> dict:
        return {"valence": self.valence, "arousal": self.arousal, "cognitive_load": self.cognitive_load,
                "ts": self.ts, "labels": {"valence": self.valence_label, "arousal": self.arousal_label}}


class MoodEngine:
    """In-memory state machine, identical clamping/history behavior to
    v1's `PersonaState`, plus `decay_toward_baseline` taking elapsed
    seconds and a half-life (exponential decay, matching the spec's
    `decay_half_life_s` config rather than v1's flat per-call `rate`)."""

    VALENCE_RANGE = (-1.0, 1.0)
    AROUSAL_RANGE = (-1.0, 1.0)
    LOAD_RANGE = (0.0, 1.0)

    def __init__(self, *, clock=None, history_limit: int = 200, baseline: EmotionalState | None = None) -> None:
        self._clock = clock or time.time
        self._baseline = baseline or EmotionalState()
        self._history_limit = history_limit
        self._state = EmotionalState(ts=self._now())
        self._history: list[EmotionalState] = [self._state]

    def _now(self) -> float:
        return self._clock.now() if hasattr(self._clock, "now") else self._clock()

    def current(self) -> EmotionalState:
        return self._state

    def set_state(self, *, valence=None, arousal=None, cognitive_load=None, source: str = "") -> tuple[EmotionalState, EmotionalState]:
        previous = self._state
        new_state = EmotionalState(
            valence=_clamp(previous.valence if valence is None else valence, *self.VALENCE_RANGE),
            arousal=_clamp(previous.arousal if arousal is None else arousal, *self.AROUSAL_RANGE),
            cognitive_load=_clamp(previous.cognitive_load if cognitive_load is None else cognitive_load, *self.LOAD_RANGE),
            ts=self._now(),
        )
        return previous, self._commit(new_state)

    def apply_delta(self, *, valence: float = 0.0, arousal: float = 0.0, cognitive_load: float = 0.0, source: str = "") -> tuple[EmotionalState, EmotionalState]:
        current = self._state
        return self.set_state(
            valence=current.valence + valence, arousal=current.arousal + arousal,
            cognitive_load=current.cognitive_load + cognitive_load, source=source,
        )

    def decay_toward_baseline(self, elapsed_s: float, *, half_life_s: float = 900.0) -> tuple[EmotionalState, EmotionalState]:
        if elapsed_s <= 0 or half_life_s <= 0:
            return self._state, self._state
        # exponential decay: fraction remaining after elapsed_s = 0.5 ** (elapsed_s / half_life_s)
        fraction_decayed = 1.0 - 0.5 ** (elapsed_s / half_life_s)
        current = self._state
        return self.set_state(
            valence=current.valence + (self._baseline.valence - current.valence) * fraction_decayed,
            arousal=current.arousal + (self._baseline.arousal - current.arousal) * fraction_decayed,
            source="decay",
        )

    def history(self, n: int = 200) -> list[EmotionalState]:
        return list(self._history[-n:])

    def restore(self, state: EmotionalState) -> None:
        """Restore from a Ledger-replayed state on boot -- not a normal
        transition, so it's not itself appended to history beyond a
        single seed entry."""
        self._state = state
        self._history = [state]

    def _commit(self, new_state: EmotionalState) -> EmotionalState:
        self._state = new_state
        self._history.append(new_state)
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit:]
        return new_state
