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
    # {provider_name: {"calls": int, "max_calls": int | None, "exhausted": bool}}
    # -- Cognition's own per-provider rolling-window budget, taken from the
    # `providers` gauge it publishes on `system.metrics` (milestone 112).
    budget: dict = field(default_factory=dict)
    workers_busy: int = 0
    workers_total: int = 0
    bus_published: int = 0
    bus_delivered: int = 0
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
        self._have_persona = False

    def on_persona_state(self, payload: dict) -> None:
        self._mood = payload.get("valence", 0.0)
        self._energy = payload.get("arousal", 0.0)
        self._load = payload.get("cognitive_load", 0.0)
        self._have_persona = True

    def on_system_metrics(self, payload: dict) -> None:
        # Live-caught: this used to also stash every subsystem's whole raw
        # payload under a `budget` key, and `render.vitals` printed that
        # dict verbatim -- a screenful of `{'orchestration': {'counters':
        # ...}}` in a panel meant to read like a person's vitals. Only the
        # flattened counters/gauges are kept; `snapshot()` picks the few
        # that mean something to a human and shapes them.
        subsystem = payload.get("subsystem", "")
        for key, value in (payload.get("counters") or {}).items():
            self._counters[f"{subsystem}.{key}"] = value
        for key, value in (payload.get("gauges") or {}).items():
            self._gauges[f"{subsystem}.{key}"] = value

    def on_guardian_posture(self, payload: dict) -> None:
        # The contract's field is `mode` (contracts/messages/guardian.py:
        # GuardianPostureChanged); Guardian is authoritative. Live-caught
        # (post-cutover review): this read `posture`, a key Guardian never
        # sends, so the panel showed `posture: unknown` all day regardless
        # of real tighten/loosen events. `posture` kept as a fallback for
        # any older producer.
        posture = payload.get("mode") or payload.get("posture")
        if posture:
            self._posture = posture

    def _budget(self) -> dict:
        providers = self._gauges.get("cognition.providers")
        if not isinstance(providers, list):
            return {}
        out: dict = {}
        for p in providers:
            if isinstance(p, dict) and p.get("name"):
                out[str(p["name"])] = {
                    "calls": int(p.get("calls", 0) or 0),
                    "max_calls": p.get("max_calls"),
                    "exhausted": bool(p.get("exhausted", False)),
                }
        return out

    def snapshot(self) -> VitalsSnapshot:
        phrase = _MOOD_PHRASES.get((_valence_label(self._mood), _arousal_label(self._energy)), "")
        return VitalsSnapshot(
            mood=self._mood, energy=self._energy, load=self._load,
            memory_records=self._counters.get("memory.stored", 0),
            skills=self._counters.get("learning.skills_acquired", 0),
            interests=self._counters.get("curiosity.interests", 0),
            backlog=self._counters.get("planning.backlog", 0),
            posture=self._posture, budget=self._budget(),
            workers_busy=int(self._gauges.get("orchestration.workers.busy", 0) or 0),
            workers_total=int(self._gauges.get("orchestration.workers.total", 0) or 0),
            bus_published=int(self._counters.get("bus.published", 0) or 0),
            bus_delivered=int(self._counters.get("bus.delivered", 0) or 0),
            mood_phrase=phrase, stale=not self._have_persona,
        )
