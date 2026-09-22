"""The People store (stage 6 item 4): one record per person, on disk.

World Model already holds what Sim knows about the world; who the people
are belongs beside it. The store is a small JSON file rather than a
stream, because it is state a human edits and reads -- "who does Sim
think I am" has to be answerable by opening a file -- and because it is
tiny and changes rarely.

Resolution is the point of it: `resolve("telegram:saeed")` and
`resolve("voice:Saeed")` are the same person, so what they say in the
kitchen is found under their name on Telegram. An identity nobody has
linked resolves to `None`, which every caller must read as `unknown`
rather than as a new person.

Stage 10 adds the two things a companion needs to know and may not
guess: what a person said yes to (`grant`/`revoke`) and what they care
about (`add_interest`/`remove_interest`). Both arrive only through a
confirmed `world.people.update`; the store never infers either.

Preferences (stage 6 item 4, 2026-09-22) are the one thing a sentence
MAY write, because they are only ever read by the model: "call me
Ira-bear" and "I prefer tea" arrive from Persona as
`persona.user_model.updated` naming who said them, and land in THAT
person's `preferences` (`remember_preference`). They used to land in one
global `user_profile` for the whole household, so what Ira asked to be
called was how Sim addressed everybody. A statement nobody can be named
for is written nowhere. A permission is never written this way -- it is
what code gates on, and it arrives only through a confirmed
`world.people.update{grant}`.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from simorgh.contracts.people import Person, from_dict, household_people, normalise_identity


#: The machine's own keyboard: a turn there that names nobody is the
#: owner's. The same convention as `guardian/tiers.py::role_of` and
#: `persona/user_model.py::CONSOLE_CHANNELS` (World Model may import
#: neither, so the tuple is repeated; moving it to `contracts/channels.py`
#: is the follow-up that makes it one answer).
CONSOLE_CHANNELS: tuple[str, ...] = ("", "cli")

#: What the model is told only above this confidence (Persona's merge:
#: one clear statement is 0.7, a contradicted one halves).
MIN_PREFERENCE_CONFIDENCE = 0.5
#: The facets a sentence may set. Anything else in a `persona.user_model
#: .updated` is refused, so a new extractor cannot quietly start writing
#: a key some code later mistakes for a setting.
PREFERENCE_FACETS: tuple[str, ...] = ("preferred_name", "preference")
_PREFERENCE_MAX_CHARS = 200


class PeopleFacet:
    name = "people"

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._people: dict[str, Person] = {}
        self._loaded = False

    # -- the store -------------------------------------------------------------------
    def load(self) -> None:
        """Read the file, or seed the household on a fresh install."""
        if self._loaded:
            return
        self._loaded = True
        data = None
        if self._path is not None and self._path.is_file():
            try:
                data = json.loads(self._path.read_text())
            except (OSError, ValueError):
                data = None       # an unreadable file is not a reason to forget the family
        if data:
            self._people = {p["person_id"]: from_dict(p) for p in data.get("people", []) if p.get("person_id")}
        else:
            self._people = {p.person_id: p for p in household_people()}
            self.save()

    def save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"people": [p.to_dict() for p in self._people.values()]}, indent=1))
        except OSError:
            pass      # a store that cannot be written still works for this process

    # -- questions ---------------------------------------------------------------------
    def all(self) -> list[Person]:
        self.load()
        return sorted(self._people.values(), key=lambda p: p.name)

    def resolve(self, identity: str) -> Person | None:
        """The person behind one identity, or None -- never a new person."""
        self.load()
        wanted = normalise_identity(identity)
        if not wanted:
            return None
        for person in self._people.values():
            if wanted in person.identities:
                return person
        return None

    def by_name(self, name: str) -> Person | None:
        self.load()
        low = (name or "").strip().lower()
        return next((p for p in self._people.values() if p.name.lower() == low), None)

    def role_of(self, identity: str) -> str:
        person = self.resolve(identity)
        return person.role if person is not None else "unknown"

    # -- changes -----------------------------------------------------------------------
    def link(self, name: str, identity: str, *, role: str = "") -> Person:
        """Say that an identity is somebody. Creates the person when the
        name is new, which is how a guest becomes known."""
        self.load()
        person = self.by_name(name)
        if person is None:
            person = Person(person_id=(name or "").strip().lower(), name=(name or "").strip(),
                            role=role or "guest")
        person = person.with_identity(identity)
        if role:
            person = replace(person, role=role)
        self._people[person.person_id] = person
        self.save()
        return person

    def unlink(self, identity: str) -> Person | None:
        self.load()
        person = self.resolve(identity)
        if person is None:
            return None
        person = person.without_identity(identity)
        self._people[person.person_id] = person
        self.save()
        return person

    def set_role(self, name: str, role: str) -> Person | None:
        self.load()
        person = self.by_name(name)
        if person is None:
            return None
        person = replace(person, role=role)
        self._people[person.person_id] = person
        self.save()
        return person

    # -- what they said yes to, and what they care about (stage 10) --------------------
    def _change(self, name: str, fn) -> Person | None:
        """Apply `fn(person) -> person` to the named person and write it
        down; `None` for a name nobody has. `fn` may raise `ValueError`
        (an unknown permission), which the service turns into a refusal."""
        self.load()
        person = self.by_name(name)
        if person is None:
            return None
        person = fn(person)
        self._people[person.person_id] = person
        self.save()
        return person

    def grant(self, name: str, permission: str) -> Person | None:
        """A person said yes. Only ever called from a confirmed
        `world.people.update` or the onboarding step -- never from a
        sentence in a turn."""
        return self._change(name, lambda p: p.with_permission(permission))

    def revoke(self, name: str, permission: str) -> Person | None:
        return self._change(name, lambda p: p.without_permission(permission))

    def add_interest(self, name: str, topic: str) -> Person | None:
        return self._change(name, lambda p: p.with_interest(topic))

    def remove_interest(self, name: str, topic: str) -> Person | None:
        return self._change(name, lambda p: p.without_interest(topic))

    def consented(self, name: str, permission: str) -> bool:
        """Whether the named person granted `permission`. The role gate is
        `contracts.people.may_check_in` / `may_share_interest`; this is
        only the grant half, for callers that already know the role."""
        person = self.by_name(name)
        return person is not None and person.grants(permission)

    # -- what they told Sim about themselves (stage 6 item 4) --------------------------
    def owner(self) -> Person | None:
        """The console's person: whoever is linked `cli:owner`, else the
        one record whose role is owner. None when the store has neither."""
        self.load()
        linked = self.resolve("cli:owner")
        if linked is not None:
            return linked
        return next((p for p in self.all() if p.role == "owner"), None)

    def speaker(self, person: str, channel: str | None) -> Person | None:
        """Who said it: a named person the store knows, or the owner for
        a console turn that names nobody. None for everybody else -- a
        name the store has no record of, an unplaced voice, a local
        surface that names nobody, or a message that does not say which
        channel it came from (`channel is None`), which is how a payload
        written before 2026-09-22 looks."""
        name = (person or "").strip()
        if name:
            return self.by_name(name)
        if channel is None or channel.strip() not in CONSOLE_CHANNELS:
            return None
        return self.owner()

    def remember_preference(self, person: Person, facet: str, value, confidence: float,
                            *, ts: float = 0.0) -> Person | None:
        """File one extracted facet under `person`'s preferences. Refuses
        (None) a facet that is not a preference or an empty value; never
        touches permissions, role or identities."""
        if facet not in PREFERENCE_FACETS:
            return None
        text = " ".join(str(value if value is not None else "").split())[:_PREFERENCE_MAX_CHARS]
        if not text:
            return None
        entry = {"value": text, "confidence": round(float(confidence or 0.0), 4), "updated_at": ts}
        return self._change(person.name, lambda p: replace(p, preferences={**p.preferences, facet: entry}))

    def profile(self, person: Person | None) -> dict:
        """The `user_profile` answer for one person: their preference
        facets and a ready line for a prompt ("" when there is nothing
        above the confidence floor, or nobody)."""
        if person is None:
            return {"person": None, "facets": {}, "text": ""}
        facets = {k: dict(v) for k, v in person.preferences.items()
                  if k in PREFERENCE_FACETS and isinstance(v, dict)}
        known = [f"{k}: {v.get('value')}" for k, v in sorted(facets.items())
                 if float(v.get("confidence") or 0.0) >= MIN_PREFERENCE_CONFIDENCE and v.get("value")]
        text = (f"What {person.name} (who is speaking) has told you about themselves: " + "; ".join(known)
                if known else "")
        return {"person": person.name, "facets": facets, "text": text}

    async def get(self, args: dict) -> dict:
        """`world.env.query{what: "people"}`: by identity, by name, or all."""
        identity = str(args.get("identity") or "")
        if identity:
            person = self.resolve(identity)
            return {"person": person.to_dict() if person else None, "role": self.role_of(identity)}
        name = str(args.get("name") or "")
        if name:
            person = self.by_name(name)
            return {"person": person.to_dict() if person else None,
                    "role": person.role if person is not None else "unknown"}
        return {"people": [p.to_dict() for p in self.all()]}


class UserProfileView:
    """`world.env.query{what: "user_profile", args: {person, channel}}`:
    ONE person's preferences, read from the People store.

    The name is kept so the query surface did not change; what it
    answers did. It used to be one global profile; now it is the
    speaker's, resolved exactly as a write is (`PeopleFacet.speaker`):
    `person` is a household name, or "" with `channel` "cli" for the
    owner's console. Asked without saying who, it answers nobody --
    there is no household-wide "user" any more.
    """

    name = "user_profile"

    def __init__(self, people: PeopleFacet) -> None:
        self._people = people

    def invalidate(self) -> None:
        pass

    async def get(self, args: dict) -> dict:
        channel = args.get("channel")
        who = self._people.speaker(str(args.get("person") or ""), None if channel is None else str(channel))
        return self._people.profile(who)


__all__ = ["CONSOLE_CHANNELS", "MIN_PREFERENCE_CONFIDENCE", "PREFERENCE_FACETS", "PeopleFacet", "UserProfileView"]
