"""Who the people are (stage 6 item 4).

The same person reaches Sim four ways -- a voice in the kitchen, a
Telegram handle, a WhatsApp number, the console -- and until now each edge
had its own idea of them: the speaker book knew voices, `household.py`
knew names and ages, the channels kept allow-lists of handles, and
`persona/user_model.py` scraped "call me X" out of sentences. Four
answers to one question, which is why what Ira told Sim in the kitchen
could not be found under her name on Telegram.

A `Person` is that one answer: the identities that are them, the role
that says what they may ask for, and the namespace their memories live
in. It is deliberately a small, boring record -- roles are a short enum,
not a policy language, and the permission matrix is `guardian/tiers.py`'s
ceiling per role rather than a per-tool grid nobody can hold in their
head.

A face Sim cannot place stays `unknown` and gets nothing: no family
facts, no household roster, no tier above reading. That is the default,
not a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

#: The roles, most trusted first. `guardian/tiers.py::CEILING` says what
#: each may reach; nothing here grants anything by itself.
ROLES: tuple[str, ...] = ("owner", "adult", "child", "guest", "unknown")

#: How an identity is written: `voice:<speaker book name>`,
#: `telegram:<handle>`, `whatsapp:<wa_id>`, `cli:owner`, `ha:<person>`.
KINDS: tuple[str, ...] = ("voice", "telegram", "whatsapp", "cli", "ha", "email")


@dataclass(frozen=True)
class Person:
    """One person, however they reach Sim."""

    person_id: str
    name: str
    role: str = "unknown"
    identities: tuple[str, ...] = ()        # "telegram:saeed", "voice:Saeed", ...
    preferences: dict = field(default_factory=dict)

    @property
    def namespace(self) -> str:
        """Where their memories live: one namespace across every channel."""
        return f"person:{self.name}"

    def with_identity(self, identity: str) -> "Person":
        identity = normalise_identity(identity)
        if not identity or identity in self.identities:
            return self
        return replace(self, identities=(*self.identities, identity))

    def without_identity(self, identity: str) -> "Person":
        identity = normalise_identity(identity)
        return replace(self, identities=tuple(i for i in self.identities if i != identity))

    def to_dict(self) -> dict:
        return {"person_id": self.person_id, "name": self.name, "role": self.role,
                "identities": list(self.identities), "preferences": dict(self.preferences)}


def from_dict(data: dict) -> Person:
    return Person(
        person_id=str(data.get("person_id") or ""), name=str(data.get("name") or ""),
        role=str(data.get("role") or "unknown"),
        identities=tuple(normalise_identity(i) for i in (data.get("identities") or ())),
        preferences=dict(data.get("preferences") or {}),
    )


def normalise_identity(identity: str) -> str:
    """`Telegram:@Saeed` -> `telegram:saeed`. One spelling per identity,
    because a second spelling is a second person as far as a lookup is
    concerned."""
    kind, _, rest = (identity or "").strip().partition(":")
    kind = kind.strip().lower()
    if not rest or kind not in KINDS:
        return ""
    from .channels import normalise_sender

    return f"{kind}:{normalise_sender(rest) if kind in ('telegram', 'whatsapp', 'email') else rest.strip().lower()}"


def household_people() -> tuple[Person, ...]:
    """The household as People, so a fresh install knows its family.

    Their voice identity is their name -- which is what the speaker book
    keys on -- and the creator is the owner. Everything else is learnt:
    a Telegram handle is linked when somebody links it, not guessed.
    """
    from .household import CHILD_AGE, HOUSEHOLD

    out = []
    for member in HOUSEHOLD:
        if member.relation == "Sim's creator":
            role = "owner"
        elif member.age is not None and member.age < CHILD_AGE:
            role = "child"
        else:
            role = "adult"
        out.append(Person(person_id=member.name.lower(), name=member.name, role=role,
                          identities=(f"voice:{member.name.lower()}",)))
    return tuple(out)


__all__ = ["KINDS", "Person", "ROLES", "from_dict", "household_people", "normalise_identity"]
