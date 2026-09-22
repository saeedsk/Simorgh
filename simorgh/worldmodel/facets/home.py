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
#: An entity nobody has observed for two hours is reported as stale,
#: when nothing better is known about how often it changes.
STALE_AFTER_S = 2 * 60 * 60.0

#: How many of an entity's own change-intervals to remember. Enough
#: for a median to mean something, few enough that a device whose
#: rhythm changes catches up within a day.
INTERVALS_KEPT = 8

#: An observation is worth trusting for this many times the entity's
#: typical gap between changes (stage 6 item 3, "staleness = age /
#: learned typical change rate").
#:
#: A flat two hours treats a front door and a thermostat alike, and
#: they are not alike: a door sensor observed thirty minutes ago tells
#: you nothing, and a thermostat observed this morning is almost
#: certainly still right. One number cannot be correct for both.
STALE_AT_CHANGES = 3.0

#: ...within these bounds, whatever the rhythm says. Nothing is fresh
#: forever, and nothing that has just been seen is instantly stale.
STALE_FLOOR_S = 5 * 60.0
STALE_CEILING_S = 24 * 60 * 60.0
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
    #: When the state last actually CHANGED, and the recent gaps
    #: between changes. Carried across observations by `observe`.
    changed_at: float = 0.0
    intervals: list = field(default_factory=list)

    def age(self, now: float) -> float:
        return max(0.0, now - self.at)

    def typical_change_s(self) -> float | None:
        """How long this thing usually goes between changes, or None
        with too little history to say. The median, not the mean: one
        device left untouched over a weekend should not make a
        minute-by-minute sensor look slow."""
        if len(self.intervals) < 3:
            return None
        ordered = sorted(self.intervals)
        middle = len(ordered) // 2
        return (ordered[middle] if len(ordered) % 2
                else (ordered[middle - 1] + ordered[middle]) / 2.0)

    def stale_after_s(self) -> float:
        """How long an observation of THIS entity is worth trusting."""
        typical = self.typical_change_s()
        if typical is None:
            return STALE_AFTER_S
        return max(STALE_FLOOR_S, min(STALE_CEILING_S, typical * STALE_AT_CHANGES))

    def stale(self, now: float) -> bool:
        return self.age(now) > self.stale_after_s()

    def as_dict(self, now: float) -> dict:
        return {"key": self.key, "kind": self.kind, "state": self.state, "area": self.area,
                "age_s": round(self.age(now), 1), "stale": self.stale(now),
                "stale_after_s": round(self.stale_after_s(), 1),
                **({"detail": self.detail} if self.detail else {})}


def decayed(belief: float, seconds: float) -> float:
    """`belief` after `seconds` with no new evidence."""
    if belief <= 0.0 or seconds <= 0.0:
        return max(0.0, belief)
    return belief * (0.5 ** (seconds / HALF_LIFE_S))


#: The READS that are folded: what the house said it was doing when
#: Sim asked. Their evidence is `rows_kept`, the bounded copy of the
#: rows Execution keeps in the metadata blob for a tool that declares
#: `evidence_fields` (`execution.service.metadata_for_blob`).
READ_TOOLS = frozenset({"home_state", "media_now"})
#: The tools whose `action.result` is evidence about the house
#: (stage 6 item 3). A tool not named here is never folded, whatever
#: its metadata looks like.
FOLDED_TOOLS = frozenset({"home_call", "home_undo", "media_control", "media_play"}) | READ_TOOLS

#: Tools whose results are evidence about the household but are NOT
#: folded, and why. The entity table reaches every chat prompt through
#: `now_block` -- the children's included -- so folding a tool here is
#: a decision about who gets to hear what it read, not only about
#: whether it is true.
NOT_FOLDED_PENDING = {
    "cal_list": ("calendar text reaching every chat prompt, the children's included, is the "
                 "creator's privacy decision, pending (2026-09-22)"),
}

#: What a `media_control` op leaves a player doing, for the ops where
#: that is not in doubt. The media tools report which players CHANGED
#: but not what they changed to (unlike `home_call`'s `after`), so the
#: state is the op's, and only for a player the house says moved. `on`
#: and `stop` are left out on purpose: Home Assistant lands them on
#: `on`, `idle`, `standby` or `off` depending on the device, and a
#: guessed state is worse than none. Volume, mute and skip change an
#: attribute, not the state.
MEDIA_OP_STATE = {"play": "playing", "resume": "playing", "pause": "paused", "off": "off"}


def folded_observations(tool: str, metadata: dict) -> list[tuple[str, str, str, dict]]:
    """`(entity_id, kind, state, detail)` for what a successful tool
    call says the house is now doing -- only entities the house
    reported as CHANGED, because Home Assistant answers 200 for a call
    on an unplugged bulb and "the call succeeded" is not "the house did
    something". A READ (`READ_TOOLS`) is the other kind of evidence:
    every row the house reported, as it was when Sim asked. Pure: the
    caller has already checked `ok`.
    """
    metadata = metadata if isinstance(metadata, dict) else {}
    changed = [e for e in (metadata.get("changed") or []) if isinstance(e, str) and e]
    out: list[tuple[str, str, str, dict]] = []
    if tool in ("home_call", "home_undo"):
        after = metadata.get("after") or {}
        if not isinstance(after, dict):
            return []
        for entity_id in changed:
            state = str(after.get(entity_id) or "")
            if state:
                # `home_undo` names no service (it may use a different
                # one per entity), so its detail says `undo` instead.
                service = str(metadata.get("service") or ("undo" if tool == "home_undo" else ""))
                out.append((entity_id, entity_id.split(".", 1)[0], state,
                            {"by": "sim", "service": service}))
    elif tool == "media_control":
        op = str(metadata.get("op") or "")
        state = MEDIA_OP_STATE.get(op, "")
        if state:
            out.extend((entity_id, entity_id.split(".", 1)[0], state,
                        {"by": "sim", "op": op, "state_from": "op"}) for entity_id in changed)
    elif tool == "media_play":
        title = str(metadata.get("what") or "")[:120]
        out.extend((entity_id, entity_id.split(".", 1)[0], "playing",
                    {"by": "sim", "op": "play", "state_from": "op", "title": title})
                   for entity_id in changed)
    elif tool in READ_TOOLS:
        out.extend(_read_observations(tool, metadata.get("rows_kept")))
    return out


def _read_observations(tool: str, rows) -> list[tuple[str, str, str, dict]]:
    """A read's rows as observations: the state the house reported,
    seen now, `source = "read"`. A read is not a change Sim made, so
    `by` is absent; a row without an entity id or a state says
    nothing and is skipped."""
    out: list[tuple[str, str, str, dict]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        entity_id, state = str(row.get("entity_id") or ""), str(row.get("state") or "")
        if "." not in entity_id or not state:
            continue
        detail: dict = {"source": "read", "tool": tool}
        if row.get("title"):
            detail["title"] = str(row["title"])[:120]
        if isinstance(row.get("volume"), (int, float)) and not isinstance(row.get("volume"), bool):
            detail["volume"] = row["volume"]
        out.append((entity_id, entity_id.split(".", 1)[0], state, detail))
    return out


class HomeFacet:
    """The entity table, the presence beliefs, and the situation facts."""

    name = "home"

    def __init__(self, *, clock=None) -> None:
        self._clock = clock or time.time
        self.entities: dict[str, Entity] = {}
        # (person, area) -> (belief, when it was last updated, was the
        # evidence a *verified* identification). Verification is kept
        # separately from belief because they answer different
        # questions: how sure Sim is that somebody is here, and whether
        # the thing that said so could tell one voice from another.
        # Guardian needs both before a voice may unlock a door
        # (stage 6 item 5).
        self._presence: dict[tuple[str, str], tuple[float, float, bool]] = {}
        #: The situation as it was when `changes()` last looked.
        self._last_situation: dict[str, bool] = {}

    def _now(self) -> float:
        return float(self._clock() if callable(self._clock) else self._clock.now())

    # -- evidence in ---------------------------------------------------------------
    def observe(self, key: str, *, kind: str, state: str, area: str = "", detail: dict | None = None,
                at: float | None = None) -> Entity:
        when = at if at is not None else self._now()
        before = self.entities.get(key)
        changed_at, intervals = when, []
        if before is not None:
            intervals = list(before.intervals)
            changed_at = before.changed_at or before.at
            if before.state != state and changed_at and when > changed_at:
                # A CHANGE, not an observation: how often a thing is
                # looked at says nothing about how often it moves, and
                # it is the moving that decides when an old reading
                # stops being worth anything.
                intervals.append(when - changed_at)
                del intervals[:-INTERVALS_KEPT]
                changed_at = when
        entity = Entity(key=key, kind=kind, state=state, area=area or self._area_of(key),
                        at=when, detail=dict(detail or {}),
                        changed_at=changed_at, intervals=intervals)
        self.entities[key] = entity
        return entity

    def saw_person(self, person: str, *, area: str, strength: float = 1.0, at: float | None = None,
                   verified: bool = False) -> None:
        """Evidence that `person` is in `area`: a placed voice, a camera
        that recognised them, a phone on the network. `strength` is how
        much the evidence is worth (a named voice more than a guess).

        `verified` is a different claim: that whatever saw them could
        actually tell them from somebody else -- a speaker match above
        the bar, a face, a phone that is theirs -- rather than a lean.
        It is the latest evidence's answer, not a high-water mark: a
        person last heard as a guess is a guess, however sure the
        identification was an hour ago.
        """
        if not person:
            return
        now = at if at is not None else self._now()
        current, since, _was = self._presence.get((person, area), (0.0, now, False))
        belief = min(1.0, decayed(current, now - since) + max(0.0, min(1.0, strength)))
        self._presence[(person, area)] = (belief, now, bool(verified))

    # -- questions out --------------------------------------------------------------
    def presence(self, *, now: float | None = None) -> dict:
        """`{person: {area: belief}}`, decayed, plus `unknown` for a person
        no evidence places anywhere right now."""
        now = self._now() if now is None else now
        out: dict[str, dict[str, float]] = {}
        for (person, area), (belief, since, _verified) in self._presence.items():
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

    def verified(self, person: str, *, now: float | None = None) -> bool:
        """Whether the evidence placing `person` where they most likely
        are came from something that could tell them apart (stage 6
        item 5). False when they are nowhere in particular."""
        area, _belief = self.where(person, now=now)
        if area == "unknown":
            return False
        return bool(self._presence.get((person, area), (0.0, 0.0, False))[2])

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

    def changes(self, *, now: float | None = None) -> list[tuple[str, bool]]:
        """The situation facts that have flipped since this was last
        asked: `(fact, value)`. Only changes -- a fact that has not moved
        is not news, and a tick that repeats itself is noise."""
        current = {k: v for k, v in self.situation(now=now).items() if isinstance(v, bool)}
        moved = [(k, v) for k, v in current.items() if self._last_situation.get(k) != v]
        self._last_situation = current
        return moved

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
            return {"person": person, "area": area, "belief": belief,
                    "verified": self.verified(person, now=now)}
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


__all__ = ["Entity", "FOLDED_TOOLS", "HALF_LIFE_S", "HomeFacet", "MEDIA_OP_STATE", "NOT_FOLDED_PENDING", "PRESENT_AT",
           "QUIET_FROM", "QUIET_TO", "READ_TOOLS", "STALE_AFTER_S", "decayed", "folded_observations"]
