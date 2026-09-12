"""The small sounds a listener makes so the speaker knows they were
heard: "aha", "okay", "let me check", "just a sec".

A person who asks something and hears nothing for four seconds does
not know whether they were heard. People in conversation close that
gap at once, before they have an answer -- an "mm-hm" for a remark, a
"let me think" for a question, a "sure, one sec" for a request -- and
only then go and think. So the session says one of these THE MOMENT
the person's turn ends, before the recogniser has even finished, and
the real answer follows when it is ready. The creator, 2026-09-11:
"sim should not remain silent for a long time to process and reply
back, instead it can immediately say aha, okay, let me check".

What is said is picked from a pool by the KIND of turn it seems to be
-- from the provisional transcript, when there is one -- and never
repeats what was said in the last few turns; the pool is large enough
that a run of turns sounds like a person, not a sound board. Nothing
here goes near the model: the words are fixed, chosen locally, and
cost nothing to say.
"""

from __future__ import annotations

import random
import re

from .lang import ENGLISH, FARSI

# The kinds of turn, as far as a half-heard transcript can tell.
HEARD = "heard"          # a remark, a statement, an answer to Sim's question
QUESTION = "question"    # the person wants to know something
REQUEST = "request"      # the person wants something done
GREETING = "greeting"    # hello, thanks, goodbye -- answered fast; only a beat is needed

POOLS: dict[str, dict[str, tuple[str, ...]]] = {
    # Reviewed with the creator 2026-09-11: nothing brisk ("Noted."),
    # nothing flattering ("Good question."), nothing that stutters
    # ("Okay, okay."), and nothing a synthesiser cannot say -- Kokoro
    # read "Mm-hm." as four letters; "Uh-huh." it can say.
    HEARD: {
        ENGLISH: ("Uh-huh.", "Aha.", "Okay.", "Right.", "Got it.", "I see.", "Yeah.", "Alright.", "Ah, okay.",
                  "Okay, I see.", "Right, okay.", "Yep."),
        FARSI: ("اوهوم.", "آها.", "باشه.", "خب.", "درسته.", "آره.", "فهمیدم.", "بله.", "آها، خب."),
    },
    QUESTION: {
        ENGLISH: ("Let me think.", "Hmm, let me see.", "Let me check.", "One sec.", "Just a sec.", "Hmm.",
                  "Let me look.", "Hang on.", "Let me have a look.", "Give me a second.", "Okay, let me check.",
                  "Ah, let me think."),
        FARSI: ("بذار ببینم.", "یه لحظه.", "یه ثانیه.", "الان می‌بینم.", "بذار فکر کنم.", "هوم.", "صبر کن ببینم.",
                "الان چک می‌کنم.", "خب، بذار ببینم."),
    },
    REQUEST: {
        ENGLISH: ("Okay.", "Sure.", "On it.", "Okay, let me do that.", "Alright, one sec.", "Sure, just a moment.",
                  "Okay, hang on.", "Will do.", "Right, on it.", "Okay, one second.", "Alright."),
        FARSI: ("چشم.", "حتماً.", "باشه.", "باشه، الان.", "الان انجام می‌دم.", "باشه، یه لحظه.", "باشه، ببینم.",
                "خب، الان.", "حتماً، یه ثانیه."),
    },
}

# Said when the answer is still not back a while after the first sound.
STILL: dict[str, tuple[str, ...]] = {
    ENGLISH: ("Still on it.", "Almost there.", "One more second.", "Bear with me.", "Still checking."),
    FARSI: ("هنوز دارم می‌بینم.", "یه لحظه دیگه.", "تقریباً تمومه.", "دارم چک می‌کنم."),
}

# Sim's names, as a person says them and as whisper writes them.
# "Shin" is how whisper wrote the creator's "Sim" on 2026-09-11.
_NAMED = re.compile(r"\b(?:sim|simorgh|simurgh|seemorgh|cyim|sym|shin|seem|sims)\b|سیم|سیمرغ", re.I)

_QUESTION = re.compile(
    r"\?\s*$|^\s*(?:what|why|how|where|when|who|which|whose|is|are|was|were|do|does|did|can|could|would|"
    r"will|should|have|has|had|am|any|tell me|explain|چی|چرا|چطور|کجا|کی|کدوم|آیا|چیه|چند)\b", re.I)
_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:can|could|would|will)\s+you\b|^\s*(?:please\s+)?"
    r"(?:make|create|add|write|run|open|start|stop|set|send|show|find|check|fix|build|turn|play|remind|"
    r"book|search|look|change|update|delete|remove|install|restart|commit|push|deploy|test|try|go|get|"
    r"put|move|rename|save|read|list|call|tell)\b|\bلطفا\b|^\s*(?:می‌?تونی|میشه|بکن|بذار|بزن|بساز|درست کن|"
    r"عوض کن|بفرست|باز کن|ببند|اجرا کن)\b", re.I)
_GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|good (?:morning|afternoon|evening|night)|thanks|thank you|cheers|bye|goodbye|"
    r"see you|good night|سلام|مرسی|ممنون|خداحافظ|شب بخیر|صبح بخیر)\b[\s!.,]*$", re.I)

# What a reply must not open with once one of these has been said aloud:
# "Okay." followed by "Okay, here it is" is a stutter.
_LEAD = re.compile(r"^\s*(?:okay|ok|yeah|yes|yep|right|hmm|ah|oh|sure|well|alright|got it|aha|mm-hm|"
                   r"باشه|آره|درسته|هوم|آها|بله|خب|چشم|حتماً)\b[,.!:;،]?\s*", re.I)


def classify(text: str) -> str:
    """The kind of turn `text` looks like. `text` may be a provisional
    transcript, or empty -- then it is a remark, and the sound is the
    neutral kind that fits anything."""
    words = (text or "").strip()
    if not words:
        return HEARD
    if _GREETING.match(words):
        return GREETING
    # A question that is also a request ("can you check the pool?") is
    # a request: what the person wants is the doing.
    if _REQUEST.search(words) and not re.match(r"^\s*(?:is|are|was|were|do|does|did)\b", words, re.I):
        return REQUEST
    if _QUESTION.search(words):
        return QUESTION
    return HEARD


def strip_lead(reply: str) -> str:
    """`reply` without an opening "Okay," / "Sure," -- for after one of
    these has already been said aloud. Keeps the rest as it was, and
    leaves a reply that is nothing but the lead alone."""
    match = _LEAD.match(reply or "")
    if match is None or match.end() >= len(reply.rstrip()):
        return reply
    rest = reply[match.end():]
    return rest[0].upper() + rest[1:] if rest[:1].islower() else rest


def addressed(partial: str, *, since_sim_spoke_s: float, exchange_window_s: float) -> bool:
    """Whether these words are presumably for Sim -- the only time a
    sound of having heard is right. Sim is not the only one in the
    room, and a listener who says "aha" to a conversation between two
    other people is not listening, they are intruding (the creator,
    2026-09-11: "sim should only chime in when the conversation or
    situation needs sim's response, otherwise it is wise for sim to
    sit quiet and alert"). So: the person said Sim's name, or Sim spoke
    a moment ago and this is the next thing said -- an exchange under
    way. Anything else is answered only if the model, which sees the
    words, decides they were for it (`is_quiet`)."""
    if _NAMED.search(partial or ""):
        return True
    return 0.0 <= since_sim_spoke_s <= exchange_window_s


#: What the model answers when the words were not for it.
QUIET = "QUIET"
_QUIET = re.compile(r"^\W*quiet\W*$", re.I)


def is_quiet(reply: str) -> bool:
    """The model heard words that were not for it and said so: nothing
    is spoken. `QUIET` alone, however wrapped or punctuated."""
    return bool(_QUIET.match((reply or "").strip()))


class Backchannel:
    """Picks the sound for a turn. Remembers the last few so a run of
    turns never repeats itself; `seed` makes a test's run predictable."""

    RECENT = 4

    def __init__(self, *, seed: int | None = None) -> None:
        self._random = random.Random(seed)
        self._recent: list[str] = []
        self.spoken = 0

    def pick(self, kind: str, language: str = ENGLISH) -> str:
        pool = POOLS.get(kind) or POOLS[HEARD]
        options = pool.get(language) or pool[ENGLISH]
        fresh = [o for o in options if o not in self._recent] or list(options)
        choice = self._random.choice(fresh)
        self._remember(choice)
        return choice

    def still(self, language: str = ENGLISH) -> str:
        options = STILL.get(language) or STILL[ENGLISH]
        fresh = [o for o in options if o not in self._recent] or list(options)
        choice = self._random.choice(fresh)
        self._remember(choice)
        return choice

    def _remember(self, choice: str) -> None:
        self.spoken += 1
        self._recent.append(choice)
        del self._recent[: -self.RECENT]


__all__ = ["Backchannel", "GREETING", "HEARD", "POOLS", "QUESTION", "QUIET", "REQUEST", "STILL", "addressed",
           "classify", "is_quiet", "strip_lead"]
