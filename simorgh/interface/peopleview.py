"""How `people` reads on the terminal (stage 10 item 4).

Consent is the thing this screen exists to make visible. Sim keeps a
wellbeing read on an adult only if that adult said yes, and brings up
what somebody cares about only if they said yes to that -- and both
are invisible from every other screen. A household should be able to
type one word and see exactly what Sim believes it is allowed to do
with each person, including the answer "nothing".

So a person with no permissions is not skipped or left blank: the
line says `said yes to: nothing`, because an empty space reads as an
oversight and the whole point is that nothing is the default.
"""

from __future__ import annotations

from . import render as render_mod

#: What each permission actually lets Sim do, in a person's words.
_MEANS = {
    "wellbeing_checkins": "may notice when they seem quieter than usual, and ask once",
    "interest_shares": "may bring up something about what they care about",
}


def everybody(payload: dict) -> str:
    people = payload.get("people") or []
    if not people:
        return "nobody yet -- `people link <name> <identity>` ties a handle or a voice to a person"
    rows = [_row(person) for person in people]
    return render_mod.panel(
        "People", [render_mod.PanelSection("", rows)], count=str(len(people)),
        footer="· `people <name>` for one · `people grant <name> <permission>` asks them first",
        enabled=render_mod.color_enabled(), unicode=render_mod.unicode_mode() != "off")


def one(payload: dict) -> str:
    person = payload.get("person")
    if not person:
        return "Sim does not know anybody by that name -- `people` lists who it does"
    lines = [f"{person.get('name', '?')}  ({person.get('role', 'unknown')})"]
    granted = list(person.get("permissions") or ())
    lines.append("  said yes to: " + (", ".join(granted) if granted else "nothing"))
    for permission in granted:
        meaning = _MEANS.get(permission)
        if meaning:
            lines.append(f"    {permission}: Sim {meaning}")
    interests = list(person.get("interests") or ())
    lines.append("  cares about: " + (", ".join(interests) if interests else "nothing recorded"))
    identities = list(person.get("identities") or ())
    lines.append("  known as: " + (", ".join(identities) if identities else "no handle linked"))
    return "\n".join(lines)


def _row(person: dict):
    granted = list(person.get("permissions") or ())
    interests = list(person.get("interests") or ())
    said_yes = ", ".join(granted) if granted else "nothing"
    return render_mod.PanelRow(
        str(person.get("name") or "?"),
        (str(person.get("role") or "unknown"), f"said yes to: {said_yes}"),
        ("cares about: " + ", ".join(interests)) if interests else "",
        "good" if granted else "idle")


__all__ = ["everybody", "one"]
