"""The fact store (stage 5 item 3): what is true now, and what it replaced.

An episodic record is what was said; a fact is what holds. The difference
matters for exactly one case the family kept hitting: a correction. Told
"my birthday is March 4th" and later "no, the 6th", the old store had two
records, both true-looking, and recall handed back whichever scored higher
-- which was often the first, because it had been referred to more
(`docs/findings/...`, the birthday case). `flag_contradictions` tried to
patch that by halving both sides, and so buried the correction too.

Here a correction wins by structure. A fact is keyed by
`(person_scope, subject, predicate)`; storing a new one for a key marks the
old one superseded, with the time it stopped being true. Recall renders the
current value and can say what it replaced, and nothing is ever rewritten:
supersession is another event, like every other change in this system.

Provenance is not optional. Every fact carries `source_refs` -- the records
it was read from -- and extraction only records a triple whose supporting
words are quoted from the transcript (`consolidation.py`), because a fact
in durable memory is indistinguishable from a real one forever after.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

#: One event per change, on `memory:facts`.
FACT_STREAM = "memory:facts"
STORED = "fact.stored"
SUPERSEDED = "fact.superseded"

#: `person_scope` for something true of the household rather than of one
#: person. A fact scoped to a person is never recalled for another.
EVERYONE = "*"


@dataclass(frozen=True)
class Fact:
    """One thing that holds, until something replaces it."""

    id: str
    subject: str
    predicate: str
    object: str
    person_scope: str = EVERYONE
    valid_from: float = 0.0
    valid_to: float | None = None      # when it stopped being true
    superseded_by: str = ""            # the fact that replaced it
    confidence: float = 1.0
    source_refs: tuple[str, ...] = ()

    @property
    def key(self) -> tuple[str, str, str]:
        # Normalised, so "Saeed birthday"/"saeed  Birthday" is one key and a
        # correction actually replaces what it corrects.
        return (self.person_scope.strip().lower(), _flat(self.subject), _flat(self.predicate))

    @property
    def live(self) -> bool:
        return self.valid_to is None and not self.superseded_by

    def sentence(self) -> str:
        """The fact as a line for a prompt: the current value, and what it
        replaced when it replaced something."""
        who = "" if self.person_scope == EVERYONE else f"{self.person_scope}: "
        return f"{who}{self.subject} {self.predicate} {self.object}"

    def to_dict(self) -> dict:
        return {"id": self.id, "subject": self.subject, "predicate": self.predicate, "object": self.object,
                "person_scope": self.person_scope, "valid_from": self.valid_from, "valid_to": self.valid_to,
                "superseded_by": self.superseded_by, "confidence": self.confidence,
                "source_refs": list(self.source_refs)}


def from_dict(data: dict) -> Fact:
    return Fact(
        id=str(data.get("id") or ""), subject=str(data.get("subject") or ""),
        predicate=str(data.get("predicate") or ""), object=str(data.get("object") or ""),
        person_scope=str(data.get("person_scope") or EVERYONE), valid_from=float(data.get("valid_from") or 0.0),
        valid_to=(None if data.get("valid_to") in (None, "") else float(data["valid_to"])),
        superseded_by=str(data.get("superseded_by") or ""), confidence=float(data.get("confidence") or 1.0),
        source_refs=tuple(str(r) for r in (data.get("source_refs") or ())),
    )


@dataclass
class FactIndex:
    """Every fact read from the stream, by id and by key."""

    by_id: dict[str, Fact] = field(default_factory=dict)
    by_key: dict[tuple[str, str, str], str] = field(default_factory=dict)   # key -> the live fact's id
    cursor: int = 0

    def apply(self, event) -> None:
        payload = event.payload or {}
        if event.type == STORED:
            fact = from_dict(payload)
            if not fact.id:
                return
            self.by_id[fact.id] = fact
            if fact.live:
                self.by_key[fact.key] = fact.id
        elif event.type == SUPERSEDED:
            old = self.by_id.get(str(payload.get("id") or ""))
            if old is None:
                return
            ended = replace(old, valid_to=float(payload.get("valid_to") or 0.0),
                            superseded_by=str(payload.get("superseded_by") or ""))
            self.by_id[old.id] = ended
            if self.by_key.get(old.key) == old.id:
                del self.by_key[old.key]

    def live_facts(self, *, person: str = "") -> list[Fact]:
        """Every fact that holds, for `person` and for everyone."""
        wanted = {EVERYONE, person.strip().lower()} if person else {EVERYONE}
        return [self.by_id[i] for i in self.by_key.values()
                if self.by_id[i].person_scope.strip().lower() in wanted]

    def previous(self, fact: Fact) -> Fact | None:
        """What this fact replaced, if anything."""
        for other in self.by_id.values():
            if other.superseded_by == fact.id:
                return other
        return None


def matching(facts: list[Fact], query: str, *, limit: int = 5) -> list[Fact]:
    """The facts whose subject or object a query mentions, best first.

    Deliberately literal: a fact block is small and must be right, so it is
    built from words the person actually used rather than from a similarity
    score that can put somebody else's birthday in front of them.
    """
    from .recall import _STOPWORDS

    words = {w for w in _words(query) if len(w) > 2 and w not in _STOPWORDS}
    if not words:
        return []
    scored = []
    for fact in facts:
        subject = set(_words(fact.subject)) - _STOPWORDS
        object_words = set(_words(fact.object)) - _STOPWORDS
        hit = len(words & subject) * 2 + len(words & object_words) + len(words & set(_words(fact.predicate)))
        if words & subject or words & object_words:
            scored.append((hit, fact))
    scored.sort(key=lambda pair: (-pair[0], pair[1].subject))
    return [fact for _hit, fact in scored[:limit]]


def _flat(text: str) -> str:
    return " ".join((text or "").split()).lower()


def _words(text: str) -> list[str]:
    import re

    return re.findall(r"[a-z0-9؀-ۿ]+", (text or "").lower())


__all__ = ["EVERYONE", "FACT_STREAM", "Fact", "FactIndex", "STORED", "SUPERSEDED", "from_dict", "matching"]
