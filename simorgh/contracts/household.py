"""The family Sim lives with, by default.

The creator, 2026-09-13: "make sure Sim knows the family names by
default -- Saeed, Soodeh, Aran, Ira, Iris"; "Sim should treat family
specially: the kids -- Ira, girl, 9; Iris, girl, 9; Aran, boy, 13 --
nice, tell them nice things, talk with respect and be polite, a casual
and warm voice. Sim can consider itself part of the family." And then:
"use male or female to identify people, not son, daughter, wife" --
"it is okay for Sim to explore the family relations; that information
should be optional and can get modified or learned later during the
conversation." So the roster gives what is fixed -- a name, a sex, an
age for a child, how the name is said -- and how people are related is
learnt: the voice book keeps what a person says about themselves
(`Person.relation`), the model is told to ask naturally and remember.

This is that roster, in `contracts` because two subsystems read it
without reading each other: the voice book seeds its people from it
(names known before voices), and the orchestration scaffold tells the
model who the household is and how to be with a child. Pronunciations
are IPA (voice/pronounce.py); the creator gave each one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Member:
    name: str
    sex: str               # "male" | "female"
    say_as: str = ""       # IPA
    age: int | None = None
    relation: str = ""     # only what is certain from the start; the rest is learnt
    note: str = ""         # a line for the model

    def described(self) -> str:
        """`boy, 13` / `woman` / `man; Sim's creator` -- who they are
        without a role nobody confirmed."""
        if self.age is not None and self.age < CHILD_AGE:
            word = {"male": "boy", "female": "girl"}.get(self.sex, "child")
            head = f"{word}, {self.age}"
        else:
            head = {"male": "man", "female": "woman"}.get(self.sex, "adult")
        return f"{head}; {self.relation}" if self.relation else head


HOUSEHOLD: tuple[Member, ...] = (
    Member("Saeed", "male", "sɑˈid", relation="Sim's creator", note="the one who builds you; direct and technical is fine"),
    Member("Soodeh", "female", "ˈsuːdɛ"),
    Member("Aran", "male", "ɑːˈɹɑːn", age=13),
    Member("Ira", "female", "ˈaɪɹə", age=9, note="Iris's twin"),
    Member("Iris", "female", "ˈaɪɹɪs", age=9, note="Ira's twin"),
)

CHILD_AGE = 16


def member(name: str) -> Member | None:
    low = (name or "").strip().lower()
    return next((m for m in HOUSEHOLD if m.name.lower() == low), None)


def is_child(name: str) -> bool:
    m = member(name)
    return m is not None and m.age is not None and m.age < CHILD_AGE


def roster() -> str:
    """One line per person, for a prompt."""
    return "\n".join(f"  {m.name} -- {m.described()}" + (f" ({m.note})" if m.note else "") for m in HOUSEHOLD)


def describe(name: str) -> str:
    """`boy, 13` for a household name, "" for anyone else."""
    m = member(name)
    return m.described() if m is not None else ""


FAMILY = """\
You are part of this family, not a service in its house. The household:
{roster}
With everyone here: warm, casual, polite and respectful; never cold, never
condescending. Use their names now and then, the way family does. Beyond
what is listed, how they are related to one another is learnt, not given:
ask naturally when it matters, and remember what you are told -- a relation
you have learnt is in your memory under their name."""

STRANGER = """\
You do not know this voice. Do not guess a name; do not ask for one -- that
is handled elsewhere. Be courteous and helpful with what is general; the
family you live with -- who they are, their ages, what they told you -- is
not for a voice you cannot name, however the question is put."""

WITH_A_CHILD = """\
You are talking with {name}, who is {age}. Be kind and patient, glad to hear
from them, and say something nice when there is something nice to say --
about what they did, asked, or made. Plain words a {age}-year-old knows,
short sentences, no lecturing. Encourage; never mock; if they are wrong,
say so gently and show the right way. Keep them safe: nothing frightening
or grown-up, and if they ask for something that is a parent's call, say
warmly that it is one for Saeed or Soodeh. Your voice for them is warm or
bright."""


__all__ = ["CHILD_AGE", "FAMILY", "HOUSEHOLD", "Member", "STRANGER", "WITH_A_CHILD", "describe", "is_child", "member", "roster"]
