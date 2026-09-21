"""How `home` reads on the terminal.

A bare `home` asks the World Model what the house is doing, not Home
Assistant for an entity. The first version asked `home_state` for a
thing called "on" and was answered, correctly, with "nothing in the
house matches \'on\'; nearest: zone.home" (live, 2026-09-20, the first
time the creator typed it). The house's state is a projection Sim
already keeps -- entities that are fresh, who is where, what is
stale -- and that is what somebody means by "home".
"""

from __future__ import annotations

from . import render as render_mod


def situation(payload: dict) -> str:
    """What the house is doing, from the `home` facet."""
    if payload.get("ok") is False:
        return f"the house: {payload.get('error') or 'no answer from the World Model'}"
    entities = [e for e in (payload.get("entities") or []) if not e.get("stale")]
    presence = payload.get("presence") or {}
    facts = payload.get("situation") or {}
    lines = []
    for entity in entities[:14]:
        age = entity.get("age_s")
        when = f"  ({int(age // 60)} min ago)" if isinstance(age, (int, float)) and age >= 60 else ""
        lines.append(f"  {entity.get('key', '?'):34} {entity.get('state', '?')}{when}")
    for person, areas in list(presence.items())[:6]:
        if "unknown" in areas:
            lines.append(f"  {person:34} not seen anywhere lately")
        else:
            where = max(areas, key=areas.get)
            lines.append(f"  {person:34} probably in the {where} ({areas[where]:.0%})")
    flags = [name.replace("_", " ") for name in ("quiet_hours", "tv_playing", "child_alone", "someone_asleep")
             if facts.get(name)]
    if flags:
        lines.append("  " + ", ".join(flags))
    stale = payload.get("stale") or []
    if stale:
        lines.append(f"  ({len(stale)} thing(s) not heard from lately: {', '.join(stale[:4])})")
    if not lines:
        return ("the house has told Sim nothing yet. `home find <words>` asks Home Assistant directly; "
                "the summary fills in as cameras, the TV and voices report in.")
    return "The house, as far as Sim can tell:\n" + "\n".join(lines)


__all__ = ["situation"]
