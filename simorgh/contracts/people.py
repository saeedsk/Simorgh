"""Who the people are (stage 6 item 4), and what they said yes to (stage 10).

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

Stage 10 adds two fields for Sim as a companion. `permissions` is what
the person said yes to, once, at onboarding -- being checked in on when
they seem quieter than usual, having something they care about brought
up unprompted. It is an explicit field and not a `preferences` key
because a permission is a thing Initiative and the wellbeing facet
*gate* on, and a preference is a thing the model *reads*; the two must
not be confusable. Nothing here grants one: the grant is a `people` tool
action at tier 3, confirmed by a person, or the onboarding step. A
sentence in a turn never is. `interests` is what they care about, as a
few short topics, so a thing worth sharing can find its person.

A face Sim cannot place stays `unknown` and gets nothing: no family
facts, no household roster, no tier above reading, and -- whatever a
record says -- no check-in. That is the default, not a fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

#: The roles, most trusted first. `guardian/tiers.py::CEILING` says what
#: each may reach; nothing here grants anything by itself.
ROLES: tuple[str, ...] = ("owner", "adult", "child", "guest", "unknown")

#: How an identity is written: `voice:<speaker book name>`,
#: `telegram:<handle>`, `whatsapp:<wa_id>`, `cli:owner`, `ha:<person>`.
KINDS: tuple[str, ...] = ("voice", "telegram", "whatsapp", "cli", "ha", "email")

#: What a person may have said yes to (stage 10). A fresh install grants
#: none of these to anybody.
#:   wellbeing_checkins  Sim may keep a baseline of how they usually talk
#:                       to it and ask how they are when they seem quieter
#:                       than their usual, at a cheap moment.
#:   interest_shares     Sim may bring up something about what they care
#:                       about, unprompted, at a cheap moment.
PERMISSIONS: tuple[str, ...] = ("wellbeing_checkins", "interest_shares")

#: Who may be checked in on at all, whatever their record says: adults.
#: A child who seems low is a parent's call, and whether Sim should even
#: tell a parent is the creator's decision (stage 10, open question 2);
#: a guest or an unplaced voice was never asked and cannot be. This is
#: the gate both the wellbeing facet and Initiative apply, kept here so
#: there is one answer rather than two that can drift apart.
CHECK_IN_ROLES: tuple[str, ...] = ("owner", "adult")
#: Who may have something they care about brought up: the family. A
#: child's permission is granted by a parent through the same tool.
INTEREST_SHARE_ROLES: tuple[str, ...] = ("owner", "adult", "child")

#: An interest is a short topic, not a paragraph.
INTEREST_MAX_CHARS = 60


@dataclass(frozen=True)
class Person:
    """One person, however they reach Sim."""

    person_id: str
    name: str
    role: str = "unknown"
    identities: tuple[str, ...] = ()        # "telegram:saeed", "voice:Saeed", ...
    preferences: dict = field(default_factory=dict)
    permissions: tuple[str, ...] = ()       # of PERMISSIONS; granted by a person, never inferred
    interests: tuple[str, ...] = ()         # short topics, normalised

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

    # -- what they said yes to -----------------------------------------------------
    def grants(self, permission: str) -> bool:
        return permission in self.permissions

    def with_permission(self, permission: str) -> "Person":
        """Raises `ValueError` for a name that is not a permission, so a
        misspelt grant is refused rather than silently granting nothing."""
        permission = (permission or "").strip().lower()
        if permission not in PERMISSIONS:
            raise ValueError(f"{permission!r} is not a permission; one of {', '.join(PERMISSIONS)}")
        if permission in self.permissions:
            return self
        return replace(self, permissions=(*self.permissions, permission))

    def without_permission(self, permission: str) -> "Person":
        permission = (permission or "").strip().lower()
        return replace(self, permissions=tuple(p for p in self.permissions if p != permission))

    # -- what they care about --------------------------------------------------------
    def with_interest(self, topic: str) -> "Person":
        topic = normalise_interest(topic)
        if not topic or topic in self.interests:
            return self
        return replace(self, interests=(*self.interests, topic))

    def without_interest(self, topic: str) -> "Person":
        topic = normalise_interest(topic)
        return replace(self, interests=tuple(t for t in self.interests if t != topic))

    def to_dict(self) -> dict:
        return {"person_id": self.person_id, "name": self.name, "role": self.role,
                "identities": list(self.identities), "preferences": dict(self.preferences),
                "permissions": list(self.permissions), "interests": list(self.interests)}


def from_dict(data: dict) -> Person:
    """A record from disk. A file written before stage 10 has no
    `permissions` or `interests`: both read as empty, which is the
    conservative answer -- nothing was granted."""
    return Person(
        person_id=str(data.get("person_id") or ""), name=str(data.get("name") or ""),
        role=str(data.get("role") or "unknown"),
        identities=tuple(normalise_identity(i) for i in (data.get("identities") or ())),
        preferences=dict(data.get("preferences") or {}),
        permissions=tuple(p for p in (str(x).strip().lower() for x in (data.get("permissions") or ()))
                          if p in PERMISSIONS),
        interests=tuple(dict.fromkeys(t for t in (normalise_interest(x) for x in (data.get("interests") or ()))
                                      if t)),
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


def normalise_interest(topic: str) -> str:
    """`  Lego Robotics ` -> `lego robotics`: one spelling, one line,
    bounded, so "lego" and "Lego" are one interest and a paragraph is
    not one at all."""
    flat = " ".join((topic or "").replace("\n", " ").split()).strip().lower()
    return flat[:INTEREST_MAX_CHARS].rstrip()


# -- the gates -------------------------------------------------------------------------
def may_check_in(person: Person | None) -> tuple[bool, str]:
    """Whether Sim may keep a wellbeing baseline for this person and ask
    how they are: `(ok, why)`. The `why` is for `initiative.suppressed`,
    so a refusal is honest about which gate it was.

    Both gates must pass: the role (adults only -- a child is a parent's
    call, a guest or an unknown voice was never asked) and the grant.
    `None` is a person nobody linked, which is `unknown`.
    """
    if person is None:
        return False, "nobody Sim knows"
    if person.role not in CHECK_IN_ROLES:
        return False, f"{person.name or 'they'} is {person.role}; a check-in is for an adult who said yes"
    if not person.grants("wellbeing_checkins"):
        return False, f"{person.name} has not said yes to check-ins"
    return True, ""


def may_share_interest(person: Person | None) -> tuple[bool, str]:
    """Whether Sim may bring up something this person cares about,
    unprompted: `(ok, why)`. Family only, and only with the grant."""
    if person is None:
        return False, "nobody Sim knows"
    if person.role not in INTEREST_SHARE_ROLES:
        return False, f"{person.name or 'they'} is {person.role}; an unprompted share is for the family"
    if not person.grants("interest_shares"):
        return False, f"{person.name} has not said yes to shares"
    return True, ""


def household_people() -> tuple[Person, ...]:
    """The household as People, so a fresh install knows its family.

    Their voice identity is their name -- which is what the speaker book
    keys on -- and the creator is the owner. Everything else is learnt:
    a Telegram handle is linked when somebody links it, not guessed, and
    no permission is granted until somebody grants it.
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


__all__ = ["CHECK_IN_ROLES", "INTEREST_MAX_CHARS", "INTEREST_SHARE_ROLES", "KINDS", "PERMISSIONS", "Person",
           "ROLES", "from_dict", "household_people", "may_check_in", "may_share_interest", "normalise_identity",
           "normalise_interest"]
