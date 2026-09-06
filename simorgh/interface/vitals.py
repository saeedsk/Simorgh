"""A real local projection (spec section 4: "an in-memory cache updated
from events"), fed only by genuine `persona.state.changed` /
`system.metrics` / `system.health` traffic on the bus -- never
fabricated. `stale=True` until the first `persona.state.changed` lands,
so `vitals` can say honestly "no data yet" instead of printing zeros
that look like real readings.

The mood-phrase labeling here intentionally duplicates a sliver of
`simorgh.persona.voice`'s logic (same reasoning as `persona.service`'s
own `_load_identity_summary`: subsystems talk only through the bus, not
by importing each other's internals).
"""

from __future__ import annotations

from dataclasses import dataclass, field

_MOOD_PHRASES = {
    ("positive", "high"): "excited, energized",
    ("positive", "moderate"): "upbeat, engaged",
    ("positive", "low"): "content, at ease",
    ("negative", "high"): "distressed, on edge",
    ("negative", "moderate"): "a bit down",
    ("negative", "low"): "quietly unsettled",
    ("neutral", "high"): "alert, focused",
    ("neutral", "moderate"): "attentive",
    ("neutral", "low"): "calm, nothing much going on",
}


def _valence_label(v: float) -> str:
    if v > 0.15:
        return "positive"
    if v < -0.15:
        return "negative"
    return "neutral"


def _arousal_label(a: float) -> str:
    if a > 0.5:
        return "high"
    if a > 0.15:
        return "moderate"
    return "low"


@dataclass(frozen=True)
class VitalsSnapshot:
    mood: float = 0.0
    energy: float = 0.0
    load: float = 0.0
    memory_records: int = 0
    skills: int = 0
    interests: int = 0
    backlog: int = 0
    posture: str = "unknown"
    budget: dict = field(default_factory=dict)
    mood_phrase: str = ""
    stale: bool = True


class VitalsCache:
    def __init__(self) -> None:
        self._mood = 0.0
        self._energy = 0.0
        self._load = 0.0
        self._counters: dict[str, int] = {}
        self._gauges: dict = {}
        self._posture = "unknown"
        self._budget: dict = {}
        self._have_persona = False

    def on_persona_state(self, payload: dict) -> None:
        self._mood = payload.get("valence", 0.0)
        self._energy = payload.get("arousal", 0.0)
        self._load = payload.get("cognitive_load", 0.0)
        self._have_persona = True

    def on_system_metrics(self, payload: dict) -> None:
        subsystem = payload.get("subsystem", "")
        for key, value in (payload.get("counters") or {}).items():
            self._counters[f"{subsystem}.{key}"] = value
        for key, value in (payload.get("gauges") or {}).items():
            self._gauges[f"{subsystem}.{key}"] = value
        self._budget[subsystem] = {"counters": payload.get("counters", {}), "gauges": payload.get("gauges", {})}

    def on_guardian_posture(self, payload: dict) -> None:
        posture = payload.get("posture")
        if posture:
            self._posture = posture

    def snapshot(self) -> VitalsSnapshot:
        phrase = _MOOD_PHRASES.get((_valence_label(self._mood), _arousal_label(self._energy)), "")
        return VitalsSnapshot(
            mood=self._mood, energy=self._energy, load=self._load,
            memory_records=self._counters.get("memory.stored", 0),
            skills=self._counters.get("learning.skills_acquired", 0),
            interests=self._counters.get("curiosity.interests", 0),
            backlog=self._counters.get("planning.backlog", 0),
            posture=self._posture, budget=dict(self._budget),
            mood_phrase=phrase, stale=not self._have_persona,
        )
