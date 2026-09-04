"""State machine tracking the persona's continuous emotional vectors and cognitive load."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class Valence(Enum):
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"


class ArousalLevel(Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


@dataclass(frozen=True)
class EmotionalState:
    """An immutable snapshot of the persona's affective and cognitive state.

    valence: pleasantness of the current state, in [-1.0, 1.0]
    arousal: activation/energy of the current state, in [-1.0, 1.0]
    cognitive_load: fraction of working capacity consumed, in [0.0, 1.0]
    timestamp: time.monotonic() value when this snapshot was captured
    """

    valence: float = 0.0
    arousal: float = 0.0
    cognitive_load: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)

    @property
    def valence_label(self) -> Valence:
        if self.valence > 0.15:
            return Valence.POSITIVE
        if self.valence < -0.15:
            return Valence.NEGATIVE
        return Valence.NEUTRAL

    @property
    def arousal_label(self) -> ArousalLevel:
        if self.arousal > 0.5:
            return ArousalLevel.HIGH
        if self.arousal > 0.15:
            return ArousalLevel.MODERATE
        return ArousalLevel.LOW


class PersonaState:
    """Thread-safe state machine for the persona's core affect and cognitive load.

    Sub-agents read the live state via `current`, and propose changes via
    `set_state` / `apply_delta`. Every dimension is clamped to its valid
    range on write, and each transition is kept in a bounded history so
    callers can inspect recent emotional drift. This class only owns the
    state itself; cross-agent publish/subscribe lives in the shared memory
    bus (src/memory/shared_bus.py), which wraps a PersonaState instance.
    """

    VALENCE_RANGE = (-1.0, 1.0)
    AROUSAL_RANGE = (-1.0, 1.0)
    COGNITIVE_LOAD_RANGE = (0.0, 1.0)

    def __init__(
        self,
        initial_state: EmotionalState | None = None,
        history_limit: int = 200,
    ) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be at least 1")
        self._lock = threading.RLock()
        self._state = initial_state or EmotionalState()
        self._history_limit = history_limit
        self._history: list[EmotionalState] = [self._state]

    @property
    def current(self) -> EmotionalState:
        """Return the live state snapshot. EmotionalState is immutable, so
        this is always safe to share across threads/sub-agents.
        """
        with self._lock:
            return self._state

    def set_state(
        self,
        *,
        valence: float | None = None,
        arousal: float | None = None,
        cognitive_load: float | None = None,
    ) -> EmotionalState:
        """Set absolute values for one or more dimensions of state.
        Dimensions left as None keep their current value. Returns the new state.
        """
        with self._lock:
            current = self._state
            new_state = EmotionalState(
                valence=_clamp(
                    current.valence if valence is None else valence,
                    *self.VALENCE_RANGE,
                ),
                arousal=_clamp(
                    current.arousal if arousal is None else arousal,
                    *self.AROUSAL_RANGE,
                ),
                cognitive_load=_clamp(
                    current.cognitive_load
                    if cognitive_load is None
                    else cognitive_load,
                    *self.COGNITIVE_LOAD_RANGE,
                ),
            )
            return self._commit(new_state)

    def apply_delta(
        self,
        *,
        valence: float = 0.0,
        arousal: float = 0.0,
        cognitive_load: float = 0.0,
    ) -> EmotionalState:
        """Nudge the current state by the given deltas, clamped to valid ranges."""
        with self._lock:
            current = self._state
            return self.set_state(
                valence=current.valence + valence,
                arousal=current.arousal + arousal,
                cognitive_load=current.cognitive_load + cognitive_load,
            )

    def decay_toward_baseline(
        self,
        rate: float = 0.1,
        baseline: EmotionalState | None = None,
    ) -> EmotionalState:
        """Relax valence/arousal a fraction `rate` of the way toward `baseline`
        (defaults to neutral). Models emotional regulation over time instead
        of moods persisting indefinitely. Cognitive load is left untouched.
        """
        base = baseline or EmotionalState()
        rate = _clamp(rate, 0.0, 1.0)
        with self._lock:
            current = self._state
            return self.set_state(
                valence=current.valence + (base.valence - current.valence) * rate,
                arousal=current.arousal + (base.arousal - current.arousal) * rate,
            )

    def history(self) -> list[EmotionalState]:
        """Return a copy of the recent state history, oldest first."""
        with self._lock:
            return list(self._history)

    def _commit(self, new_state: EmotionalState) -> EmotionalState:
        self._state = new_state
        self._history.append(new_state)
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit :]
        return new_state
