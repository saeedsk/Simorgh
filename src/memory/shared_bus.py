"""Shared memory bus for publish/subscribe access to cross-agent state.

Sub-agents don't pass large context windows back and forth; instead they
publish updates to shared state here, and any interested agent can read the
latest value instantly or subscribe to be notified the moment it changes.
The first (and currently only) piece of shared state is the persona's mood
and cognitive load, backed by PersonaState.
"""

from __future__ import annotations

import threading
from typing import Callable

from src.orchestrator.persona_state import EmotionalState, PersonaState

MoodListener = Callable[[EmotionalState, EmotionalState, str], None]


class SharedMemoryBus:
    """Publish/subscribe layer over the persona's shared emotional state.

    - Any agent calls `read()` to instantly get the current mood/cognitive
      load, e.g. the "logic" agent reading mood to adjust its tone.
    - Any agent calls `publish_delta` / `publish_state` to change it, e.g.
      the "emotion" agent updating mood after processing input.
    - Any agent calls `subscribe` to be notified synchronously, with the
      previous state, the new state, and the name of the publishing agent,
      the instant a change is committed.
    """

    def __init__(self, persona_state: PersonaState | None = None) -> None:
        self._persona_state = persona_state or PersonaState()
        self._lock = threading.RLock()
        self._listeners: list[MoodListener] = []

    @property
    def persona_state(self) -> PersonaState:
        return self._persona_state

    def read(self) -> EmotionalState:
        """Instantly read the current mood/cognitive-load state."""
        return self._persona_state.current

    def publish_state(
        self,
        source: str,
        *,
        valence: float | None = None,
        arousal: float | None = None,
        cognitive_load: float | None = None,
    ) -> EmotionalState:
        """Set absolute values for one or more dimensions and notify subscribers."""
        with self._lock:
            previous = self._persona_state.current
            new_state = self._persona_state.set_state(
                valence=valence, arousal=arousal, cognitive_load=cognitive_load
            )
            self._notify(previous, new_state, source)
            return new_state

    def publish_delta(
        self,
        source: str,
        *,
        valence: float = 0.0,
        arousal: float = 0.0,
        cognitive_load: float = 0.0,
    ) -> EmotionalState:
        """Nudge the state by the given deltas and notify subscribers."""
        with self._lock:
            previous = self._persona_state.current
            new_state = self._persona_state.apply_delta(
                valence=valence, arousal=arousal, cognitive_load=cognitive_load
            )
            self._notify(previous, new_state, source)
            return new_state

    def subscribe(self, listener: MoodListener) -> Callable[[], None]:
        """Register `listener(previous, new, source)` to run on every
        committed mood change. Returns an unsubscribe function.
        """
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def _notify(
        self, previous: EmotionalState, new_state: EmotionalState, source: str
    ) -> None:
        for listener in list(self._listeners):
            listener(previous, new_state, source)
