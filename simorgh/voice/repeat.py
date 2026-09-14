"""Is this the same question again?

Live 2026-09-13: Sim took fifteen seconds over a question (a web
search); the creator, hearing nothing, said it again; the second turn
cancelled the first, the first's answer arrived and was dropped as
stale, the second's answer was "that came through garbled", and the
creator spoke a third time -- so that was dropped too. A person who
repeats a question is waiting for the first answer, not asking for a
second one.
"""

from __future__ import annotations

import difflib
import re

_STRIP = re.compile(r"[^\w\s]", re.UNICODE)
_LEAD = re.compile(r"^(?:(?:hey|ok|okay|so|um|uh|sim|simorgh|sam|sims?)[\s,]+)+", re.I)
#: "are you there?", "did you hear me?", "hello?": a nudge, not a new question
_NUDGE = re.compile(
    r"^(?:(?:hey|ok|okay|so|um|uh|sim|simorgh|sam)[\s,]+)*"
    r"(?:hello|hi|are you there|you there|are you listening|did you hear me|can you hear me|do you hear me|"
    r"you didn'?t answer|answer me|well\??|any answer|still there|i'?m waiting|i asked you (?:something|a question))"
    r"[\s?!.,]*$", re.I)

RATIO = 0.62
#: share of the shorter question's content words found in the longer one
WORD_SHARE = 0.6
MIN_CONTENT_WORDS = 4
_STOP = frozenset("the a an and or but so of to in on at for with by from is are was were be been do did does "
                  "you your me my i it its this that these those what which who how why when where can could would "
                  "should will please just about into than then there here".split())


def _norm(text: str) -> str:
    text = _LEAD.sub("", (text or "").strip().lower())
    return " ".join(_STRIP.sub(" ", text).split())


def _content(text: str) -> list[str]:
    return [w for w in text.split() if w not in _STOP and (len(w) > 2 or w.isdigit())]


def _same_word(a: str, b: str) -> bool:
    """drop / dropped, day / days: the same word to a listener."""
    if a == b:
        return True
    return len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4]


def _word_share(a: str, b: str) -> float:
    wa, wb = _content(a), _content(b)
    if min(len(wa), len(wb)) < MIN_CONTENT_WORDS:
        return 0.0
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    hits = sum(1 for w in short if any(_same_word(w, other) for other in long_))
    return hits / len(short)


def is_nudge(text: str) -> bool:
    """The words mean "I am waiting", nothing more."""
    return bool(_NUDGE.match((text or "").strip()))


def is_repeat(text: str, earlier: str) -> bool:
    """`text` asks what `earlier` asked: the same words, most of the
    same words, or one inside the other. Short fragments never count --
    "yes" twice is two answers."""
    a, b = _norm(text), _norm(earlier)
    if len(a) < 8 or len(b) < 8:
        return False
    if a == b or (len(a) >= 12 and a in b) or (len(b) >= 12 and b in a):
        return True
    if difflib.SequenceMatcher(None, a, b).ratio() >= RATIO:
        return True
    return _word_share(a, b) >= WORD_SHARE


__all__ = ["MIN_CONTENT_WORDS", "RATIO", "WORD_SHARE", "is_nudge", "is_repeat"]
