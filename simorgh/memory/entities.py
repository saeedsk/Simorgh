"""Entities (stage 15 item 1): who and what the facts are about.

A fact's subject and object are the strings somebody said. "Soo likes
tea" and a question about "Soodeh" share no word, so the literal fact
match in `facts.matching` cannot bring them together, and neither can a
similarity score over a three-word sentence. An entity is the thing both
strings name: `person:soodeh`, with "Soo" and "Soodeh" as aliases.

The shape follows `facts.py`. Entities live on their own stream,
`memory:entities`, as events -- `entity.created`, `entity.alias_added`,
`entity.merged`, `entity.summary` -- and `EntityIndex` is the fold of
that stream, as `FactIndex` is the fold of `memory:facts`. Nothing is
edited: a merge is an event naming the surviving id, and every id ever
issued keeps resolving, to the survivor, so a fact that recorded the old
id is still found.

Resolution (string -> id) is deliberately cheap and conservative, in this
order: an exact alias; the People registry; a normalised fuzzy match
(edit distance at most 1, and only for names of five or more characters,
where one slip is a typo rather than a different name); otherwise nothing,
and the writer creates a new entity. A wrong merge puts one person's facts
under another's name, which is worse than a missed one, so a pair that is
close but not certain is only noted (`EntityIndex.uncertain`) for the
sleep tick to ask about, never merged here.

Kinship words ("my wife", "his son") are never an entity, and neither is
a phrase built on one ("my wife's sister"). The speaker's own ("my wife",
"our son", a bare "son") resolve through the speaker's People record when
that record says who the word means; anybody else's ("his son", "your
wife") and everything else resolve to nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

#: One event per change, on `memory:entities`. `memory:` streams are
#: memory's by prefix (`contracts/streamnames.py`), so this needs no entry
#: of its own there.
ENTITY_STREAM = "memory:entities"
CREATED = "entity.created"
ALIAS_ADDED = "entity.alias_added"
MERGED = "entity.merged"
SUMMARY = "entity.summary"

TYPES: tuple[str, ...] = ("person", "place", "device", "organisation", "thing", "event")

#: Words that name a relation to the speaker, not a person. "my wife" is
#: Soodeh when the speaker is Saeed and somebody else when it is not, so
#: an entity named "wife" would merge every speaker's wife into one.
KINSHIP = frozenset(
    "wife husband partner son daughter child children kid kids mum mom mother dad father brother sister "
    "grandma grandmother grandpa grandfather granny aunt uncle cousin niece nephew baby twin twins "
    "boyfriend girlfriend spouse".split())
_KIN_OWNERS = ("my ", "our ", "his ", "her ", "their ", "your ")

_ARTICLES = ("the ", "a ", "an ")
_POSSESSIVE = re.compile(r"(?:'s|’s|s'|s’)$")
_SLUG = re.compile(r"[^a-z0-9؀-ۿ]+")


def normalise(text: str) -> str:
    """`The Boiler's` -> `boiler`: casefolded, articles and possessives off,
    one space between words, punctuation off the ends."""
    flat = " ".join((text or "").casefold().split()).strip(" .,;:!?\"'()[]")
    for article in _ARTICLES:
        if flat.startswith(article):
            flat = flat[len(article):]
            break
    words = [_POSSESSIVE.sub("", w) for w in flat.split()]
    return " ".join(w for w in words if w).strip(" .,;:!?\"'()[]")


def slug(text: str) -> str:
    return _SLUG.sub("-", normalise(text)).strip("-")


def kinship_word(text: str) -> str:
    """`my wife` -> `wife`; "" for anything that is not a kinship word."""
    flat = " ".join((text or "").casefold().split())
    for owner in _KIN_OWNERS:
        if flat.startswith(owner):
            flat = flat[len(owner):]
            break
    flat = _POSSESSIVE.sub("", flat.strip(" .,;:!?"))
    return flat if flat in KINSHIP else ""


def speakers_own(text: str) -> bool:
    """Whether a kinship word is the speaker's relation: "my son", "our
    son" or a bare "son". "his son" and "her son" are somebody else's, and
    "your wife" is the listener's; the speaker's record says nothing about
    whose, so those resolve to nothing rather than to the speaker's son."""
    flat = " ".join((text or "").casefold().split())
    return not any(flat.startswith(owner) for owner in _KIN_OWNERS if owner not in ("my ", "our "))


def relational(text: str) -> bool:
    """Whether `text` names somebody through a relation to whoever is
    speaking or being spoken of: "my wife's sister", "his son's teacher".
    Not a kinship word itself, but just as speaker-relative, so it is never
    an entity either -- "my wife's sister" is a different person for every
    speaker."""
    words = [_POSSESSIVE.sub("", w.strip(" .,;:!?\"'()")) for w in (text or "").casefold().split()]
    return any(words[i] + " " in _KIN_OWNERS and words[i + 1] in KINSHIP for i in range(len(words) - 1))


def edit_distance_at_most_one(a: str, b: str) -> bool:
    """Levenshtein distance <= 1, without building the matrix."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = j = 0
    slipped = False
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            i += 1
            j += 1
            continue
        if slipped:
            return False
        slipped = True
        if len(a) == len(b):
            i += 1
        j += 1
    return True


#: A fuzzy match is only trusted for names this long: "Ira" and "Iris"
#: are one edit apart and two different children.
FUZZY_MIN_CHARS = 5


@dataclass(frozen=True)
class Entity:
    """One person, place or thing that facts are about."""

    id: str
    type: str
    name: str
    aliases: tuple[str, ...] = ()
    summary: str = ""
    #: The scope of the fact that first named it. Informational: names are
    #: not what `person_scope` protects -- facts are, and a hop only ever
    #: follows facts the asking person may see (`recall.hop_facts`).
    person_scope: str = "*"
    source_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "name": self.name, "aliases": list(self.aliases),
                "person_scope": self.person_scope, "source_refs": list(self.source_refs)}


@dataclass
class EntityIndex:
    """Every entity read from `memory:entities`, with its aliases."""

    by_id: dict[str, Entity] = field(default_factory=dict)
    alias: dict[str, str] = field(default_factory=dict)        # normalised alias -> id
    merged_into: dict[str, str] = field(default_factory=dict)  # old id -> the id it was merged into
    #: id -> (the fact ids the last summary was written from, its scope).
    summarised: dict[str, tuple[frozenset, str]] = field(default_factory=dict)
    #: Pairs `(text, id)` a fuzzy match found close but not certain: one
    #: edit away from more than one entity. In process only; the sleep tick
    #: asks about them, and a yes is a merge event.
    uncertain: set = field(default_factory=set)
    cursor: int = 0

    # -- the fold ---------------------------------------------------------------------
    def apply(self, event) -> None:
        payload = event.payload or {}
        entity_id = str(payload.get("id") or "")
        if not entity_id:
            return
        if event.type == CREATED:
            entity = Entity(
                id=entity_id, type=str(payload.get("type") or "thing"), name=str(payload.get("name") or ""),
                aliases=tuple(str(a) for a in payload.get("aliases") or ()),
                person_scope=str(payload.get("person_scope") or "*"),
                source_refs=tuple(str(r) for r in payload.get("source_refs") or ()))
            self.by_id[entity_id] = entity
            for alias in (entity.name, *entity.aliases):
                self._learn(alias, entity_id)
        elif event.type == ALIAS_ADDED:
            entity = self.by_id.get(entity_id)
            alias = str(payload.get("alias") or "")
            if entity is None or not alias:
                return
            if alias not in entity.aliases:
                self.by_id[entity_id] = replace(entity, aliases=(*entity.aliases, alias))
            self._learn(alias, entity_id)
        elif event.type == MERGED:
            into = str(payload.get("into") or "")
            if not into or into == entity_id or self.canonical(into) == entity_id:
                return   # a merge into itself, or a cycle: ignored rather than looping
            self.merged_into[entity_id] = into
            survivor = self.by_id.get(self.canonical(into))
            gone = self.by_id.get(entity_id)
            if survivor is not None and gone is not None:
                extra = tuple(a for a in (gone.name, *gone.aliases) if a not in survivor.aliases)
                self.by_id[survivor.id] = replace(survivor, aliases=(*survivor.aliases, *extra))
            for alias, owner in list(self.alias.items()):
                if owner == entity_id:
                    self.alias[alias] = self.canonical(into)
        elif event.type == SUMMARY:
            entity = self.by_id.get(entity_id)
            if entity is None:
                return
            self.by_id[entity_id] = replace(entity, summary=str(payload.get("summary") or ""))
            self.summarised[entity_id] = (frozenset(str(f) for f in payload.get("fact_ids") or ()),
                                          str(payload.get("person_scope") or "*"))

    def _learn(self, alias: str, entity_id: str) -> None:
        key = normalise(alias)
        # First come keeps it: an alias that already names somebody is not
        # quietly moved to somebody else. A merge is how two become one.
        if key and key not in self.alias:
            self.alias[key] = entity_id

    # -- reading ------------------------------------------------------------------------
    def canonical(self, entity_id: str) -> str:
        """The surviving id for any id ever issued (merges followed)."""
        seen = set()
        while entity_id in self.merged_into and entity_id not in seen:
            seen.add(entity_id)
            entity_id = self.merged_into[entity_id]
        return entity_id

    def get(self, entity_id: str) -> Entity | None:
        return self.by_id.get(self.canonical(entity_id))

    def resolve(self, text: str, *, speaker: str = "", people=()) -> str | None:
        """`text` -> an entity id, or None (see the module docstring for
        the order). Never writes; an id from the People registry may not
        exist on the stream yet, and the writer creates it."""
        how, entity_id = self.resolve_how(text, speaker=speaker, people=people)
        return entity_id

    def resolve_how(self, text: str, *, speaker: str = "", people=()) -> tuple[str, str | None]:
        """`(rule, id)`: which rule answered -- `alias`, `people`, `kin`,
        `fuzzy` -- or `("", None)`."""
        key = normalise(text)
        if not key:
            return "", None
        # 1. exact alias
        if key in self.alias:
            return "alias", self.canonical(self.alias[key])
        # 2. the People registry (and, for a kinship word, the speaker's record)
        kin = kinship_word(text)
        if kin or relational(text):
            name = relation_of(people, speaker, kin) if kin and speakers_own(text) else ""
            if not name:
                return "kin", None
            return "kin", self.resolve(name, people=people) or person_id(name)
        person = person_named(people, key)
        if person is not None:
            return "people", self.canonical(person_id(person.name))
        # 3. normalised fuzzy match
        if len(key) >= FUZZY_MIN_CHARS:
            near = {self.canonical(owner) for alias, owner in self.alias.items()
                    if len(alias) >= FUZZY_MIN_CHARS and edit_distance_at_most_one(key, alias)}
            if len(near) == 1:
                return "fuzzy", near.pop()
            for owner in near:
                self.uncertain.add((key, owner))
        return "", None


def person_id(name: str) -> str:
    return f"person:{slug(name)}"


def person_named(people, key: str):
    """The Person whose name, or whose voice identity, is `key`."""
    for person in people or ():
        name = str(getattr(person, "name", "") or "")
        if normalise(name) == key:
            return person
        for identity in getattr(person, "identities", ()) or ():
            kind, _, rest = str(identity).partition(":")
            if kind == "voice" and normalise(rest) == key:
                return person
    return None


def relation_of(people, speaker: str, word: str) -> str:
    """Who `word` ("wife") is for `speaker`, from their People record's
    `relations` mapping (`contracts.people.Person.relations`, set through
    `world.people.update{set_relation}`); "" when the record does not say.
    `getattr`, because a caller may hand in any record with a `name`."""
    me = person_named(people, normalise(speaker)) if speaker else None
    relations = getattr(me, "relations", None) or {}
    for key, name in dict(relations).items():
        if normalise(str(key)) == word:
            return str(name)
    return ""


def name_like(text: str) -> bool:
    """Whether an object string names something rather than being a value:
    "Reza" and "the boiler" are things; "0912 345 6789", "March 6th" and a
    sentence are not, and an entity for each would make every value a node."""
    flat = " ".join((text or "").split())
    return bool(flat) and len(flat) <= 40 and len(flat.split()) <= 4 and not any(c.isdigit() for c in flat)


def guess_type(text: str) -> str:
    """A cheap first guess. A capitalised name is a person until something
    says otherwise; everything else is a thing. The type is a label for a
    reader, never a key: resolution does not look at it."""
    words = (text or "").strip().split()
    if words and all(w[:1].isupper() for w in words) and len(words) <= 3:
        return "person"
    return "thing"


__all__ = ["ALIAS_ADDED", "CREATED", "ENTITY_STREAM", "Entity", "EntityIndex", "FUZZY_MIN_CHARS", "KINSHIP", "MERGED",
           "SUMMARY", "TYPES", "edit_distance_at_most_one", "guess_type", "kinship_word", "name_like", "normalise",
           "person_id", "person_named", "relation_of", "relational", "slug", "speakers_own"]
