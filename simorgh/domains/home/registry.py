""""kitchen lights" -> `light.kitchen_main`.

A person does not know entity ids and should never have to. Neither
should the model: it hears "turn the kitchen light off" and has to
produce something HA will accept.

The rule that shapes all of this: **ambiguity is refused, never
guessed**. If "kitchen" matches four entities across three domains,
picking one is a coin flip that turns the wrong thing on, and the
person's next sentence is "no, the other one". Refusing with the
candidates costs one round trip and is right every time.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from simorgh.contracts.home.api import Entity


class Ambiguous(ValueError):
    """More than one entity matched. Carries the candidates so the
    refusal can list them."""

    def __init__(self, query: str, candidates: list[str]) -> None:
        self.query, self.candidates = query, candidates
        listed = ", ".join(candidates[:8])
        more = f" (and {len(candidates) - 8} more)" if len(candidates) > 8 else ""
        super().__init__(f"{query!r} matches {len(candidates)} entities: {listed}{more}")


class NotFound(ValueError):
    def __init__(self, query: str, nearest: list[str]) -> None:
        self.query, self.nearest = query, nearest
        hint = f"; nearest: {', '.join(nearest)}" if nearest else ""
        super().__init__(f"nothing in the house matches {query!r}{hint}")


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if w]


#: Words that carry no information about which device is meant.
#: Without these, "the thermostat" fails to match anything, because
#: "the" is required to appear in the entity's name.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "a", "an", "my", "our", "your", "in", "on", "at", "of", "to", "please", "all",
})

#: Words a person says that mean a domain.
_DOMAIN_WORDS: dict[str, str] = {
    "light": "light", "lights": "light", "lamp": "light", "lamps": "light",
    "switch": "switch", "plug": "switch", "socket": "switch",
    "thermostat": "climate", "heating": "climate", "climate": "climate",
    "lock": "lock", "door": "lock",
    "speaker": "media_player", "tv": "media_player", "echo": "media_player",
    "music": "media_player", "player": "media_player",
    "sensor": "sensor", "camera": "camera", "cover": "cover", "blind": "cover",
    "blinds": "cover", "curtain": "cover", "fan": "fan", "alarm": "alarm_control_panel",
}


@dataclass
class Registry:
    """The entity list, and the matching over it.

    Rebuilt from `client.states()` per call rather than cached: a house
    changes, a cache that is a few minutes stale resolves an alias to a
    device that has been unplugged, and the cost of a fresh read is one
    HTTP request against a machine on the LAN.
    """

    entities: list[Entity]
    aliases: dict[str, tuple[str, ...]] = None

    def __post_init__(self) -> None:
        self.aliases = {k.lower(): tuple(v) for k, v in (self.aliases or {}).items()}

    @classmethod
    async def load(cls, client, *, aliases: dict | None = None) -> "Registry":
        return cls(entities=await client.states(), aliases=aliases or {})

    def by_id(self, entity_id: str) -> Entity | None:
        return next((e for e in self.entities if e.entity_id == entity_id), None)

    def domains(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entity in self.entities:
            counts[entity.domain] = counts.get(entity.domain, 0) + 1
        return counts

    def resolve(self, target: str, *, domain: str = "") -> list[str]:
        """Entity ids for `target`. Raises `Ambiguous` or `NotFound`.

        The order tried is exact id, then alias, then a scored name
        match -- each one narrower than the next, so a person who knows
        the id always gets the id.
        """
        target = (target or "").strip()
        if not target:
            raise NotFound(target, [])

        if self.by_id(target) is not None:
            return [target]

        alias = self.aliases.get(target.lower())
        if alias:
            missing = [e for e in alias if self.by_id(e) is None]
            if missing:
                raise NotFound(target, [f"{e} (in the alias, but not in the house)" for e in missing])
            return list(alias)

        words = _words(target)
        wanted_domain = domain or next(
            (_DOMAIN_WORDS[w] for w in words if w in _DOMAIN_WORDS), "")
        # The domain word is consumed: "kitchen lights" should match on
        # "kitchen", not insist that the name contains "lights" too.
        subject = [w for w in words if w not in _DOMAIN_WORDS and w not in _STOPWORDS]

        scored: list[tuple[float, str]] = []
        for entity in self.entities:
            if wanted_domain and entity.domain != wanted_domain:
                continue
            haystack = _words(f"{entity.object_id} {entity.name} {entity.area}")
            if not haystack:
                continue
            if subject and all(word in haystack for word in subject):
                scored.append((1.0, entity.entity_id))
                continue
            if not subject and wanted_domain:
                scored.append((0.5, entity.entity_id))
                continue
            ratio = difflib.SequenceMatcher(
                None, " ".join(subject), " ".join(haystack)).ratio()
            if ratio >= 0.72:
                scored.append((ratio, entity.entity_id))

        if not scored:
            return self._not_found(target)

        best = max(score for score, _ in scored)
        matches = [entity_id for score, entity_id in scored if score >= best - 1e-9]

        # A domain word is also a name hint. "tv" means the television,
        # not every media player in the house -- so when the word that
        # chose the domain also appears in some candidate's name, those
        # candidates win. Only when it narrows things: a word that
        # matches nothing must not empty the result.
        if len(matches) > 1:
            hints = [w for w in words if w in _DOMAIN_WORDS]
            for hint in hints:
                narrowed = [entity_id for entity_id in matches
                            if hint in _words(f"{entity_id} "
                                              f"{(self.by_id(entity_id).name if self.by_id(entity_id) else '')}")]
                if narrowed and len(narrowed) < len(matches):
                    matches = narrowed

        # A whole group is a legitimate answer: "kitchen lights" meaning
        # every light in the kitchen. What is not legitimate is one
        # answer picked from several DIFFERENT things.
        #
        # Note what is NOT checked here: how many. Thirty lights is a
        # large group, not an ambiguous one, and whether that is too
        # many to act on at once is a policy question the caller
        # answers from its own configured limit. Two limits in two
        # places meant the hardcoded one silently shadowed the
        # configured one.
        if len(matches) > 1 and len({m.split(".", 1)[0] for m in matches}) > 1:
            raise Ambiguous(target, sorted(matches))
        return sorted(matches)

    def _not_found(self, target: str):
        names = [e.entity_id for e in self.entities]
        nearest = difflib.get_close_matches(target, names, n=3, cutoff=0.3)
        if not nearest:
            words = _words(target)
            nearest = [e.entity_id for e in self.entities
                       if any(w in e.entity_id or w in e.name.lower() for w in words)][:3]
        raise NotFound(target, nearest)

    def search(self, query: str, *, limit: int = 25) -> list[Entity]:
        """Everything that looks relevant. Unlike `resolve`, never
        raises -- this is for browsing, not for acting on."""
        words = _words(query)
        if not words:
            return self.entities[:limit]
        out = []
        for entity in self.entities:
            haystack = f"{entity.entity_id} {entity.name} {entity.area}".lower()
            if all(word in haystack for word in words):
                out.append(entity)
        if not out:
            names = {e.entity_id: e for e in self.entities}
            for name in difflib.get_close_matches(query, list(names), n=limit, cutoff=0.4):
                out.append(names[name])
        return out[:limit]


__all__ = ["Ambiguous", "NotFound", "Registry"]
