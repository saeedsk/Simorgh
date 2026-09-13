"""Meeting someone by voice: the conversation Sim has when a voice it does
not know keeps speaking, or when a person says "Sim, learn Aran's voice".

The creator, 2026-09-13: "can Sim automatically have a setup mode which
can conversationally enroll a new family member's voice, instead of the
owner typing CLI commands". So:

    unknown voice, twice in a few minutes
        Sim answers what was asked, then: "I don't know your voice yet.
        What is your name?"
    "I'm Aran" / "my name is Aran" / "Aran"
        "Nice to meet you, Aran. How are you related to the family? Or
        say skip."
    "I'm Saeed's son" / "skip"
        the utterances heard so far are the first takes; one more is
        asked for until there are three
    third take
        "Thank you, Aran. I will know your voice now."

`Introduction` is the state machine, pure and testable; the session
feeds it each turn's text and voice vector and speaks what it returns.
It never enrols without a name the person gave, and a take the book
refuses (it sounds like someone already enrolled) is said back, not
swallowed.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

TAKES = 3
#: how many turns an unknown voice speaks before Sim asks who it is
ASK_AFTER_TURNS = 2
#: how long an unknown voice is remembered between those turns
UNKNOWN_WINDOW_S = 600.0

_NAME_PATTERNS = (
    re.compile(r"\b(?:my name is|my name's|i am|i'm|im|this is|it's|its|call me|they call me|name is)\s+([A-Za-z][A-Za-z'\-]{1,30})", re.I),
    re.compile(r"^\s*(?:it is|it's)?\s*([A-Za-z][A-Za-z'\-]{1,30})\s*[.!]?\s*$", re.I),
)
_NOT_NAMES = {"skip", "no", "yes", "nobody", "none", "stop", "quiet", "sim", "simorgh", "okay", "ok", "hello", "hi",
              "what", "why", "who", "sorry", "nothing", "never", "mind", "nevermind", "cancel", "not", "just", "here",
              "so", "going", "also", "a", "an", "the", "very", "really", "fine", "good", "done", "back", "home", "sure",
              "afraid", "tired", "busy", "hungry", "his", "her", "their", "my", "your", "this", "that", "it"}
_SKIP = re.compile(r"^\s*(?:skip|no|none|nothing|never ?mind|pass|not now|later|rather not)\b", re.I)
_RELATION_LEAD = re.compile(r"^\s*(?:i am|i'm|im|it's|its|this is|his|her|their|the)\s+", re.I)
_LEARN = re.compile(r"\b(?:learn|remember|meet|enrol+|register|save)\s+(?:the\s+voice\s+of\s+)?([A-Za-z][A-Za-z\-]{1,30})(?:'s|s'|s)?\s*(?:voice)?\b", re.I)
_LEARN_TAIL = re.compile(r"\b(?:learn|remember|enrol+|register|save)\s+(?:my|this)\s+voice\b", re.I)


def name_in(text: str) -> str:
    """The name a person gave, capitalised, or ""."""
    text = (text or "").strip()
    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            name = match.group(1).strip("'-")
            if name.lower() in _NOT_NAMES or len(name) < 2:
                continue
            return name[:1].upper() + name[1:]
    return ""


def relation_in(text: str) -> str:
    """"" for skip, else the relation as the person said it, trimmed of
    "I'm" and the like: "Saeed's son", "the mother", "a friend"."""
    text = (text or "").strip().rstrip(".!")
    if not text or _SKIP.match(text) or text.endswith("?") or len(text.split()) > 6:
        return ""   # "Okay, do you want to learn my voice?" is not a relation (the creator's book, 2026-09-13)
    return _RELATION_LEAD.sub("", text).strip()[:60]


def learn_request(text: str, *, speaker: str = "") -> str:
    """"Sim, learn Aran's voice" -> "Aran"; "learn my voice" -> the
    speaker's name if known, else "?" (ask); "" when it is not that."""
    text = (text or "").strip()
    if _LEARN_TAIL.search(text):
        return speaker or "?"
    match = _LEARN.search(text)
    if match and match.group(1).lower() not in _NOT_NAMES and match.group(1).lower() not in ("my", "this", "your", "the"):
        return match.group(1)[:1].upper() + match.group(1)[1:]
    return ""


@dataclass
class Step:
    """What the session should do after feeding a turn to the introduction."""

    say: str = ""              # spoken by Sim, as an aside
    enrolled: str = ""         # a take was accepted for this name
    done: bool = False         # the introduction is over (success or given up)
    consumed: bool = True      # the turn was part of the introduction, not a question for Sim


@dataclass
class Introduction:
    """One person being met. `vectors` are the takes gathered so far."""

    stage: str = "ask_name"    # ask_name | ask_relation | take
    name: str = ""
    relation: str = ""
    vectors: list = field(default_factory=list)
    accepted: int = 0
    misses: int = 0

    def feed(self, text: str, vector, book) -> Step:
        text = (text or "").strip()
        if self.stage == "ask_name":
            name = name_in(text)
            if not name:
                self.misses += 1
                if self.misses >= 2:
                    return Step(say="No problem, we can do this another time.", done=True)
                return Step(say="I did not catch the name. Say: my name is, and then your name.")
            self.name = name
            if vector is not None:
                self.vectors.append(vector)
            self.stage = "ask_relation"
            return Step(say=f"Nice to meet you, {name}. How are you related to the family? Or say skip.")
        if self.stage == "ask_relation":
            self.relation = relation_in(text)
            if vector is not None:
                self.vectors.append(vector)
            self.stage = "take"
            return self._enrol_gathered(book)
        # stage take
        if vector is None:
            return Step(say="I did not get enough voice from that. Say a full sentence, please.")
        self.vectors.append(vector)
        return self._enrol_gathered(book)

    refused: int = 0

    def _enrol_gathered(self, book) -> Step:
        note = ""
        while self.vectors and self.accepted < TAKES:
            vector = self.vectors.pop(0)
            try:
                _person, note = book.enroll(self.name, vector, relation=self.relation, insist=self.refused >= 1)
            except Exception as exc:  # noqa: BLE001
                note = f"refused: {exc}"
            if note:
                break
            self.accepted += 1
        if note:
            # Once: say who it sounded like and ask again. Twice: they said
            # who they are; take their word (2026-09-13).
            self.refused += 1
            who = note.split("sounds like ", 1)[1].split(" (")[0] if "sounds like " in note else "someone else"
            return Step(say=f"That sounded like {who}. Once more, {self.name}?", enrolled=self.name)
        if self.accepted >= TAKES:
            return Step(say=f"Thank you, {self.name}. I will know your voice now.", enrolled=self.name, done=True)
        left = TAKES - self.accepted
        return Step(say=(f"Say one more sentence so I remember your voice." if left == 1
                         else f"Say another sentence for me. {left} more."), enrolled=self.name)


class UnknownVoices:
    """Unknown voices heard lately, clustered by cosine, so Sim asks a
    person who keeps talking -- not a voice heard once through a door."""

    def __init__(self, *, threshold: float, window_s: float = UNKNOWN_WINDOW_S, clock=time.time) -> None:
        self._threshold = threshold
        self._window = window_s
        self._clock = clock
        self._heard: list[tuple[list[float], float]] = []

    def note(self, vector) -> int:
        """Remember this unknown voice; return how many recent turns
        sound like it (this one included)."""
        from .speakers import cosine

        now = self._clock()
        self._heard = [(v, t) for v, t in self._heard if now - t <= self._window][-40:]
        count = 1 + sum(1 for v, _t in self._heard if cosine(v, vector) >= self._threshold)
        self._heard.append(([float(x) for x in vector], now))
        return count

    def clear(self) -> None:
        self._heard = []


__all__ = ["ASK_AFTER_TURNS", "Introduction", "Step", "TAKES", "UnknownVoices", "learn_request", "name_in", "relation_in"]
