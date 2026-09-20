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
"""

from __future__ import annotations

import json
from pathlib import Path

from simorgh.contracts.people import Person, from_dict, household_people, normalise_identity


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
            person = person.__class__(**{**person.to_dict(), "identities": person.identities, "role": role})
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
        from dataclasses import replace

        person = replace(person, role=role)
        self._people[person.person_id] = person
        self.save()
        return person

    async def get(self, args: dict) -> dict:
        """`world.env.query{what: "people"}`."""
        identity = str(args.get("identity") or "")
        if identity:
            person = self.resolve(identity)
            return {"person": person.to_dict() if person else None, "role": self.role_of(identity)}
        return {"people": [p.to_dict() for p in self.all()]}


__all__ = ["PeopleFacet"]
