"""`world:home` (stage 6 item 3): what the house is doing, and who is in it.

Sim already sees the evidence -- a camera event, the TV's state, a voice
placed in a room, the result of every home tool -- and until now each
consumer read whichever stream it happened to know about. This folds them
into one small table and answers two questions a household assistant is
asked constantly: what is on, and who is here.

Two rules shape it.

**Evidence decays.** A camera that saw somebody at the door two hours ago
is not evidence that they are there now. Presence is a belief per (person,
area) that halves every `HALF_LIFE_S` and is reported as a distribution
with `unknown` in it, so "nobody has been seen anywhere" is a visible
answer rather than an empty one that reads like "the house is empty".

**Staleness is honest.** An entity is reported with the age of its last
observation, and anything older than `STALE_AFTER_S` is named as stale
rather than rendered as the current state -- the difference between "the
TV is off" and "the TV was off two days ago, I have not looked since".

The situation facts (quiet hours, someone asleep, nobody home, TV playing,
a child alone) are pure functions of that table, so they can be tested
without a house and never disagree with what they were derived from.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: A presence belief halves every twenty minutes without new evidence.
HALF_LIFE_S = 20 * 60.0
#: An entity nobody has observed for two hours is reported as stale.
STALE_AFTER_S = 2 * 60 * 60.0
#: Below this, a belief is not worth reporting as presence at all.
PRESENT_AT = 0.25
#: Quiet hours, local time: the house is asleep between these.
QUIET_FROM, QUIET_TO = 22, 7


@dataclass
class Entity:
    """One thing in the house, as last observed."""

    key: str                    # "tv.family_room", "camera.pool", "light.kitchen"
    kind: str                   # tv | camera | light | media | person | other
    state: str = ""
    area: str = ""
    at: float = 0.0
    detail: dict = field(default_factory=dict)

    def age(self, now: float) -> float:
        return max(0.0, now - self.at)

    def stale(self, now: float) -> bool:
        return self.age(now) > STALE_AFTER_S

    def as_dict(self, now: float) -> dict:
        return {"key": self.key, "kind": self.kind, "state": self.state, "area": self.area,
                "age_s": round(self.age(now), 1), "stale": self.stale(now), **({"detail": self.detail} if self.detail else {})}


def decayed(belief: float, seconds: float) -> float:
    """`belief` after `seconds` with no new evidence."""
    if belief <= 0.0 or seconds <= 0.0:
        return max(0.0, belief)
    return belief * (0.5 ** (seconds / HALF_LIFE_S))


class HomeFacet:
    """The entity table, the presence beliefs, and the situation facts."""

    name = "home"

    def __init__(self, *, clock=None) -> None:
        self._clock = clock or time.time
        self.entities: dict[str, Entity] = {}
        # (person, area) -> (belief, when it was last updated)
        self._presence: dict[tuple[str, str], tuple[float, float]] = {}

    def _now(self) -> float:
        return float(self._clock() if callable(self._clock) else self._clock.now())

    # -- evidence in ---------------------------------------------------------------
    def observe(self, key: str, *, kind: str, state: str, area: str = "", detail: dict | None = None,
                at: float | None = None) -> Entity:
        entity = Entity(key=key, kind=kind, state=state, area=area or self._area_of(key),
                        at=at if at is not None else self._now(), detail=dict(detail or {}))
        self.entities[key] = entity
        return entity

    def saw_person(self, person: str, *, area: str, strength: float = 1.0, at: float | None = None) -> None:
        """Evidence that `person` is in `area`: a placed voice, a camera
        that recognised them, a phone on the network. `strength` is how
        much the evidence is worth (a named voice more than a guess)."""
        if not person:
            return
        now = at if at is not None else self._now()
        current, since = self._presence.get((person, area), (0.0, now))
        belief = min(1.0, decayed(current, now - since) + max(0.0, min(1.0, strength)))
        self._presence[(person, area)] = (belief, now)

    # -- questions out --------------------------------------------------------------
    def presence(self, *, now: float | None = None) -> dict:
        """`{person: {area: belief}}`, decayed, plus `unknown` for a person
        no evidence places anywhere right now."""
        now = self._now() if now is None else now
        out: dict[str, dict[str, float]] = {}
        for (person, area), (belief, since) in self._presence.items():
            value = decayed(belief, now - since)
            if value >= PRESENT_AT:
                out.setdefault(person, {})[area] = round(value, 3)
        for person in {p for p, _a in self._presence}:
            if person not in out:
                out[person] = {"unknown": 1.0}
        return out

    def where(self, person: str, *, now: float | None = None) -> tuple[str, float]:
        """`(area, belief)` for the likeliest place, or `("unknown", 0.0)`."""
        areas = self.presence(now=now).get(person, {})
        if not areas or "unknown" in areas:
            return "unknown", 0.0
        area = max(areas, key=areas.get)
        return area, areas[area]

    def situation(self, *, now: float | None = None) -> dict:
        """The facts a decision actually turns on. Each is derived, and
        `unknown` where the evidence does not support an answer."""
        now = self._now() if now is None else now
        from simorgh.contracts.household import is_child

        here = self.presence(now=now)
        placed = {p: a for p, a in here.items() if "unknown" not in a}
        hour = time.localtime(now).tm_hour
        tv_on = any(e.kind == "tv" and e.state in ("playing", "on") and not e.stale(now)
                    for e in self.entities.values())
        adults = [p for p in placed if not is_child(p)]
        children = [p for p in placed if is_child(p)]
        return {
            "quiet_hours": hour >= QUIET_FROM or hour < QUIET_TO,
            "tv_playing": tv_on,
            # "Nobody home" is only ever said from evidence: with nothing
            # seen either way it is unknown, because an empty table looks
            # exactly like a house whose sensors are all asleep.
            "nobody_home": (not placed) if self._presence else None,
            "someone_asleep": (hour >= QUIET_FROM or hour < QUIET_TO) and bool(placed),
            "child_alone": bool(children) and not adults,
            "people": {p: max(a, key=a.get) for p, a in placed.items()},
        }

    def now_block(self, *, now: float | None = None, limit: int = 8) -> str:
        """The house as a few lines for a prompt (~200 tokens at most).

        Only what is fresh: a stale entity is named as unknown rather than
        rendered as fact, which is the difference between Sim saying "the
        TV is off" and "I have not looked at the TV since Tuesday".
        """
        now = self._now() if now is None else now
        lines: list[str] = []
        fresh = [e for e in self.entities.values() if not e.stale(now)]
        for entity in sorted(fresh, key=lambda e: e.at, reverse=True)[:limit]:
            where = f" in the {entity.area}" if entity.area else ""
            lines.append(f"- {entity.key}{where}: {entity.state} ({int(entity.age(now) // 60)} min ago)")
        stale = [e.key for e in self.entities.values() if e.stale(now)]
        if stale:
            lines.append(f"- not looked at lately, so unknown: {', '.join(sorted(stale)[:6])}")
        for person, areas in self.presence(now=now).items():
            if "unknown" in areas:
                lines.append(f"- {person}: not seen anywhere lately")
            else:
                area = max(areas, key=areas.get)
                lines.append(f"- {person}: probably in the {area} ({areas[area]:.0%})")
        situation = self.situation(now=now)
        flags = [name for name in ("quiet_hours", "tv_playing", "child_alone") if situation.get(name)]
        if flags:
            lines.append("- " + ", ".join(flags).replace("_", " "))
        return "\n".join(lines)

    async def get(self, args: dict) -> dict:
        """The `world.env.query` shape (`what: "home"`)."""
        now = self._now()
        person = str(args.get("person") or "")
        if person:
            area, belief = self.where(person, now=now)
            return {"person": person, "area": area, "belief": belief}
        return {
            "entities": [e.as_dict(now) for e in sorted(self.entities.values(), key=lambda e: e.key)],
            "presence": self.presence(now=now),
            "situation": self.situation(now=now),
        }

    @staticmethod
    def _area_of(key: str) -> str:
        """The area from an entity key like `light.kitchen`."""
        _kind, _, rest = (key or "").partition(".")
        return rest.replace("_", " ") if rest else ""


__all__ = ["Entity", "HALF_LIFE_S", "HomeFacet", "PRESENT_AT", "QUIET_FROM", "QUIET_TO", "STALE_AFTER_S", "decayed"]
