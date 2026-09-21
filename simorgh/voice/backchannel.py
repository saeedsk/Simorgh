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
EMPATHY = "empathy"      # the person said something that hurts; the sound is warm, not brisk

POOLS: dict[str, dict[str, tuple[str, ...]]] = {
    # Reviewed with the creator 2026-09-11: nothing brisk ("Noted."),
    # nothing flattering ("Good question."), nothing that stutters
    # ("Okay, okay."), and nothing a synthesiser cannot say -- Kokoro
    # read "Mm-hm." as four letters; "Uh-huh." it can say.
    HEARD: {
        # One word, the shortest Kokoro says cleanly: the creator, 2026-09-13,
        # "for short sounds you should choose something that is short".
        ENGLISH: ("Right.", "Got it.", "Yes.", "Yep.", "Okay.", "I see.", "Sure thing."),
        FARSI: ("اوهوم.", "آها.", "باشه.", "خب.", "درسته.", "آره.", "فهمیدم.", "بله.", "آها، خب."),
    },
    QUESTION: {
        ENGLISH: ("Let me see.", "Let me check.", "One sec.", "Hmm.", "Hang on.", "Let me look."),
        FARSI: ("بذار ببینم.", "یه لحظه.", "یه ثانیه.", "الان می‌بینم.", "بذار فکر کنم.", "هوم.", "صبر کن ببینم.",
                "الان چک می‌کنم.", "خب، بذار ببینم."),
    },
    REQUEST: {
        ENGLISH: ("Sure.", "On it.", "Will do.", "Right.", "One sec."),
        FARSI: ("چشم.", "حتماً.", "باشه.", "باشه، الان.", "الان انجام می‌دم.", "باشه، یه لحظه.", "باشه، ببینم.",
                "خب، الان.", "حتماً، یه ثانیه."),
    },
    EMPATHY: {
        ENGLISH: ("I know.", "I hear you.", "That's hard.", "Oh no.", "I'm sorry.", "That sounds rough.",
                  "I get it.", "That's a lot."),
        FARSI: ("می‌فهمم.", "سخته.", "آره…", "متاسفم.", "می‌دونم.", "درکت می‌کنم."),
    },
}

# Under a person mid-story, half loud (voice/delivery.py "hum"): plain
# words only. "Uh-huh" was here and the creator did not like the sound
# of it (2026-09-12); "Mm-hm" Kokoro cannot say, and "Yeah" it says as
# "yaw ho".
HUM: dict[str, tuple[str, ...]] = {
    ENGLISH: ("Right.", "Okay.", "I see.", "Yep."),
    FARSI: ("آره.", "خب.", "آها.", "درسته."),
}

# Said when the answer is still not back a while after the first sound.
STILL: dict[str, tuple[str, ...]] = {
    ENGLISH: ("Still on it.", "Almost there.", "One more second.", "Bear with me.", "Still checking."),
    FARSI: ("هنوز دارم می‌بینم.", "یه لحظه دیگه.", "تقریباً تمومه.", "دارم چک می‌کنم."),
}

# Said when a tool that is known to be slow has just started (stage 3
# item 5). Different from STILL on purpose: this one says what is
# happening, because the person has already heard an acknowledgement and
# a second "still on it" tells them nothing new.
LOOKING: dict[str, tuple[str, ...]] = {
    ENGLISH: ("Let me look.", "Looking that up.", "Checking now.", "Give me a moment for this one."),
    FARSI: ("بذار ببینم.", "دارم نگاه می‌کنم.", "الان چک می‌کنم."),
}

# Sim's names, as a person says them and as whisper writes them.
# "Shin" is how whisper wrote the creator's "Sim" on 2026-09-11.
# `sam`, `sima`, `seam` and `simma` are 2026-09-20, live: the creator
# said "Hello, Sam. Can you hear me?", "Sima, I'm talking to you",
# "What's up, Seam?" and got silence five turns running, because an
# unplaced voice must name Sim (`session._unplaced`) and whisper had
# written the name four ways that were not on this list. The list is
# what whisper WRITES, not what is spelt: it already carries "seem",
# an ordinary English word, because being deaf to your own name costs
# more than the occasional false positive -- a person says "that seems
# right" and Sim looks up, which is what a person in the room would do.
_NAMED = re.compile(
    r"\b(?:sim|simm|simma|sima|seema|simorgh|simurgh|seemorgh|cyim|sym|syme|shin|seem|seam|sam|sams|sims|asim)\b"
    r"|سیم|سیمرغ", re.I)

_QUESTION = re.compile(
    r"\?\s*$|^\s*(?:what|why|how|where|when|who|which|whose|is|are|was|were|do|does|did|can|could|would|"
    r"will|should|have|has|had|am|any|tell me|explain|چی|چرا|چطور|کجا|کی|کدوم|آیا|چیه|چند)\b", re.I)
_REQUEST = re.compile(
    r"^\s*(?:please\s+)?(?:can|could|would|will)\s+you\b|^\s*(?:please\s+)?"
    r"(?:make|create|add|write|run|open|start|stop|set|send|show|find|check|fix|build|turn|play|remind|"
    r"book|search|look|change|update|delete|remove|install|restart|commit|push|deploy|test|try|go|get|"
    r"put|move|rename|save|read|list|call|tell)\b|\bلطفا\b|^\s*(?:می‌?تونی|میشه|بکن|بذار|بزن|بساز|درست کن|"
    r"عوض کن|بفرست|باز کن|ببند|اجرا کن)\b", re.I)
# Feelings, not states of the system: "the pool is exhausted" and "the
# link is dead" are engineering, so those words are not here.
_HURT = re.compile(
    r"\b(?:sorry|sad|tired|frustrat\w*|died|passed away|stressed|worried|scared|alone|lonely|upset|angry|"
    r"overwhelmed|depress\w*|anxious|cry\w*|awful|terrible|horrible|hard day|rough day|give up|can'?t take|"
    r"miss (?:him|her|them|you|my))\b|ناراحت|خسته|متاسف|غمگین|دلم گرفته|مریض|نگران|تنها|عصبانی|گریه", re.I)
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
    if _HURT.search(words):
        return EMPATHY
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
    # "Got it -- KATSEYE..." left "-- KATSEYE" for the voice (live 2026-09-13):
    # the dash or comma that joined the lead to the rest goes with it.
    rest = reply[match.end():].lstrip(" \t,;:-\u2013\u2014")
    if not rest:
        return reply
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


#: Words people use INSTEAD of a name, for somebody who is not Sim.
#: Only ever read as a vocative -- set off by a comma, at one end of
#: the sentence -- so "add honey to the list" is a shopping list and
#: "try a bit harder next time, honey" is a parent talking to a child.
_ENDEARMENTS = r"honey|sweetheart|sweetie|darling|dear|love|babe|baby|buddy|mate|kiddo|pal"
_VOCATIVE_TAIL = re.compile(rf",\s*(?:my\s+)?({_ENDEARMENTS})\s*[.!?…]*\s*$", re.I)
_VOCATIVE_LEAD = re.compile(rf"^\s*(?:hey\s+|oi\s+)?({_ENDEARMENTS})\s*,", re.I)


def to_someone_else(text: str, *, names: tuple[str, ...] = ()) -> str:
    """The person this was addressed to, if it was not Sim: `"honey"`,
    `"Ira"`, or `""`.

    A sentence that names who it is for has told you who it is for,
    and the shape of it -- a question, a request -- says nothing
    against that. This is the rule the model kept getting wrong: with
    a real model behind it, "Can you try a bit harder next time,
    honey." was answered "Sorry, Devin -- tell me what I got wrong
    and I'll fix it", which is Sim taking a parent's word to their
    child personally (the creator's log, 2026-09-20; reproduced by
    the household simulator against the paid provider the same day).
    The scaffold has told the model not to do this for weeks.

    Deliberately narrow: a vocative only, at one end of the sentence,
    set off by a comma; and never when Sim is named too, because
    "Sim, ask her nicely, honey" is for Sim.
    """
    text = (text or "").strip()
    if not text or _NAMED.search(text):
        return ""
    for pattern in (_VOCATIVE_TAIL, _VOCATIVE_LEAD):
        found = pattern.search(text)
        if found:
            return found.group(1).lower()
    for name in names:
        if not name:
            continue
        who = re.escape(name)
        if re.search(rf",\s*{who}\s*[.!?…]*\s*$", text, re.I) or re.search(rf"^\s*{who}\s*,", text, re.I):
            return name
    return ""


#: Ordinary words a household name can be one letter away from.
#: Rewriting one of these would be worse than the misspelling.
_REAL_WORDS = frozenset({
    "are", "air", "era", "ira", "iris", "irish", "aran", "aria", "arab", "iran", "sudden",
    "so", "sod", "soda", "are", "our", "ours", "aaron", "karen", "ivan", "irma", "aida",
})


def _one_letter_apart(heard: str, name: str) -> bool:
    """Whether `heard` is `name` with one letter added, dropped or
    swapped -- and at three letters, added or dropped only.

    The length rule is the whole safety of this. A substitution in a
    three-letter name turns Ida into Ira and Ron into Ram: at that
    length every name is one letter from every other, and respelling
    one person as another is worse than any misspelling. An INSERTION
    is different -- it is what a recogniser does to a short name it
    does not know, and "Aira" is not somebody else.
    """
    if heard == name:
        return True
    if abs(len(heard) - len(name)) > 1:
        return False
    if len(heard) == len(name):
        return len(name) >= 4 and sum(a != b for a, b in zip(heard, name)) == 1
    longer, shorter = (heard, name) if len(heard) > len(name) else (name, heard)
    for i in range(len(longer)):
        if longer[:i] + longer[i + 1:] == shorter:
            return True
    return False


def spell_household_names(text: str, names: tuple[str, ...] = ()) -> str:
    """Give a household name back its own spelling.

    Whisper writes short unusual names the way they sound: the
    creator's daughter Ira came back as "Aira", and he corrected Sim
    out loud -- "Ira and not Aira" (2026-09-20). One misspelling then
    costs three things at once: the vocative rule stops recognising
    her name, the memory stores a person who does not exist, and the
    screen shows the wrong name to the person who chose it.

    Narrow on purpose, because rewriting what somebody actually said
    is the rudest thing in this file. A word is respelled only when
    it is one letter from a name of somebody who lives here (and at
    three letters, one letter ADDED or DROPPED -- never swapped, or
    Ida becomes Ira), and the heard word is not an ordinary English
    word -- so "Aaron" stays Aaron, "iris" the flower is left to
    context, and "era" is never a person.
    """
    names = tuple(n for n in names if n and len(n) >= 3)
    if not text or not names:
        return text

    def swap(match: "re.Match[str]") -> str:
        word = match.group(0)
        low = word.lower()
        if low in _REAL_WORDS:
            return word
        for name in names:
            if low == name.lower():
                return word
            if _one_letter_apart(low, name.lower()):
                return name if word[:1].isupper() or word.isupper() else name.lower()
        return word

    return re.sub(r"\b[A-Za-z]{3,}\b", swap, text)


#: Asking for something only Sim does.
#:
#: The gap this closes, live on 2026-09-20: the creator's daughter
#: sang in the kitchen, and a moment later he said "tell me a story
#: from the Arabian Nights book". `_bystander` sits out anything that
#: is not a question and does not name Sim when another known voice
#: has just spoken -- so his request was filed as talk between the two
#: of them and got nothing. Typed, the same words worked.
#:
#: Widening "is this for me" is how this project has hurt itself
#: before ("try a bit harder next time, honey" got answered), so this
#: is not "any imperative". It is a request for something SIM does:
#: set a timer, turn a light on, remind me, play something, read me
#: something, tell me a story. A parent says none of those to a child
#: in the middle of a conversation with one -- and the vocative rule
#: still wins, so "read Aran a story" stays out of it.
_FOR_SIM = re.compile(
    r"\b(?:set|start|stop|cancel)\s+(?:a|an|the)?\s*(?:timer|alarm|reminder|stopwatch)\b"
    r"|\bremind\s+(?:me|us)\b"
    r"|\b(?:turn|switch|dim|put)\s+(?:on|off|up|down)?\s*(?:the\s+)?[\w\s]{0,20}"
    r"\b(?:light|lights|lamp|heating|kettle|fan|tv|music)\b"
    r"|\b(?:play|pause|skip)\s+(?:some\s+|the\s+)?(?:music|song|playlist|radio|next)\b"
    r"|\b(?:tell|read|recite)\s+(?:me|us)\b"
    r"|\bwhat(?:'s| is)\s+(?:on\s+)?(?:my|the)\s+(?:calendar|diary|schedule|agenda)\b"
    r"|\badd\s+[\w\s]{1,30}\bto\s+the\s+(?:list|shopping|calendar)\b", re.I)


def asks_for_something_sim_does(text: str, *, names: tuple[str, ...] = ()) -> bool:
    """Whether these words ask for something only Sim does.

    Never when the sentence names somebody else: "read Aran a story"
    is a parent organising a household, not a request to Sim.
    """
    text = (text or "").strip()
    if not text or to_someone_else(text, names=names):
        return False
    return bool(_FOR_SIM.search(text))


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

    def hum(self, language: str = ENGLISH) -> str:
        options = HUM.get(language) or HUM[ENGLISH]
        fresh = [o for o in options if o not in self._recent] or list(options)
        choice = self._random.choice(fresh)
        self._remember(choice)
        return choice

    def looking(self, language: str = ENGLISH) -> str:
        """A short line that says a slow tool is running (stage 3 item 5)."""
        options = LOOKING.get(language) or LOOKING[ENGLISH]
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


__all__ = ["Backchannel", "EMPATHY", "GREETING", "HEARD", "HUM", "LOOKING", "POOLS", "QUESTION", "QUIET", "REQUEST", "STILL", "addressed",
           "asks_for_something_sim_does", "classify", "is_quiet", "spell_household_names", "strip_lead", "to_someone_else"]
