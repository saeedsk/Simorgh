"""The few things a person says TO the voice itself, not to Sim:
"stop", "be quiet", "voice off". Handled on the spot, never sent to
the model -- the creator said "voice off" to a Sim that kept talking
(2026-09-11), because the words went off to be answered like any other.

Only a whole short utterance counts. "Stop" inside a sentence is a
word; "Stop." alone, or "Sim, stop talking", is an instruction.
"""

from __future__ import annotations

import re

RESTART = "restart"  # come back up on the source on disk (the creator, by voice, 2026-09-15)
HUSH = "hush"    # say nothing at all until somebody asks for Sim back
STOP = "stop"    # be quiet now; keep listening
OFF = "off"      # stop, and stop listening too
MUTE = "mute"    # stop listening; a typed `voice unmute` brings it back

_LEAD = re.compile(r"^\s*(?:hey\s+|ok(?:ay)?\s+|please\s+)?(?:sim|simorgh|shin|سیم|سیمرغ)?\s*[,.!]?\s*", re.I)
_TRAIL = re.compile(r"\s*(?:please|now|sim|simorgh|شین|سیم|لطفا)?\s*[.!?،]*\s*$", re.I)

_PHRASES: dict[str, tuple[str, ...]] = {
    OFF: ("voice off", "turn off the voice", "turn the voice off", "turn off your voice", "switch off the voice",
          "go to sleep", "sleep", "صدا قطع", "صدا رو قطع کن", "صدات رو قطع کن", "بخواب"),
    MUTE: ("mute", "mute yourself", "stop listening", "mute your mic", "mute the mic", "mute your microphone",
           "mute the microphone", "mute your ears", "stop listening to us", "don't listen", "ears off",
           "گوش نده", "بی‌صدا"),
    RESTART: ("restart", "restart yourself", "restart now", "reboot", "reboot yourself",
              "restart please", "ری‌استارت", "ریستارت", "دوباره راه بیفت"),
    STOP: ("stop", "stop talking", "stop it", "enough", "shush",
           "that's enough", "okay stop", "ok stop", "stop please", "بس کن", "بسه",
           "دیگه بسه", "کافیه"),
    # Not the same as STOP, which cuts the sentence in flight and then
    # carries on as before. The creator, 2026-09-22: "I want to add a
    # mode to sim to shut up and be quiet when household is asking it
    # ... and sim should remain silent unless a family member asks sim
    # with direct addressing". A house wants a thing in the corner that
    # can be told to leave them alone and MEANS it.
    HUSH: ("be quiet", "quiet", "silence", "shut up", "shut it", "hush", "hush now", "be silent",
           "stay quiet", "keep quiet", "be quiet please", "silence please", "no talking",
           "ساکت", "ساکت باش", "ساکت شو", "سکوت", "خفه شو", "حرف نزن", "صحبت نکن"),
}
_LOOKUP = {phrase: kind for kind, phrases in _PHRASES.items() for phrase in phrases}
_MAX_WORDS = 5


def spoken_command(text: str) -> str | None:
    """`STOP`, `OFF`, `MUTE`, `RESTART`, or None when `text` is ordinary talk."""
    words = (text or "").strip()
    if not words or len(words.split()) > _MAX_WORDS:
        return None
    core = _TRAIL.sub("", _LEAD.sub("", words)).strip().lower()
    core = re.sub(r"[\s,]+", " ", core)
    return _LOOKUP.get(core)


#: A turn that OPENS with one of these, said while Sim is talking, is a
#: person cutting in -- whatever else they go on to say. The level gate is
#: the fast path; this is the one that cannot be fooled by a loud room
#: ("stop stop I'm saying stop multiple times", the creator, 2026-09-15).
_STOP_LEAD = re.compile(
    r"^\s*(?:hey\s+|ok(?:ay)?\s+|please\s+)?(?:sim|simorgh|seem|seam|shin)?\s*[,.!]*\s*"
    r"(?:stop|wait|hold on|hold it|quiet|be quiet|hush|shush|enough|shut up|no no|"
    r"بس کن|بسه|صبر کن|ساکت)\b", re.I)


def opens_with_stop(text: str) -> bool:
    """Whether `text` begins by telling Sim to stop."""
    return bool(_STOP_LEAD.match(text or ""))


#: "be quiet for ten minutes" -- the same instruction with an end to it.
#: Minutes by default: nobody means ten seconds, and "an hour" is said
#: as an hour.
_FOR_HOW_LONG = re.compile(
    r"\bfor\s+(?:the\s+)?(?:next\s+)?(?P<n>\d+|a|an|one|two|three|five|ten|fifteen|twenty|thirty|half\s+an)\s*"
    r"(?P<unit>seconds?|secs?|minutes?|mins?|hours?|hrs?)\b"
    r"|\b(?P<fa_n>\d+)\s*(?P<fa_unit>ثانیه|دقیقه|ساعت)\b", re.I)
_WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "five": 5,
                 "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "half an": 0.5}


def hush_seconds(text: str) -> float:
    """How long "be quiet" was asked for, or 0.0 for "until I say so".

    0.0 is the common answer and the right default: a person who says
    "be quiet" and nothing more means until they say otherwise, and a
    silence that ends on its own is not the one they asked for.
    """
    match = _FOR_HOW_LONG.search(text or "")
    if not match:
        return 0.0
    raw = match.group("n") or match.group("fa_n") or ""
    unit = (match.group("unit") or match.group("fa_unit") or "minutes").lower()
    try:
        count = float(raw) if raw.replace(".", "").isdigit() else float(_WORD_NUMBERS.get(raw.lower(), 0))
    except ValueError:
        return 0.0
    if count <= 0:
        return 0.0
    per = 1.0 if unit.startswith(("second", "sec", "ثانیه")) else (
        3600.0 if unit.startswith(("hour", "hr", "ساعت")) else 60.0)
    return count * per


#: Asking for Sim back. It must NAME Sim: the whole point of the hush is
#: that the room can talk without being answered, so only a sentence
#: aimed at Sim ends it ("hey sim you talk now", the creator).
_TALK_AGAIN = re.compile(
    r"(?:\b(?:hey|ok(?:ay)?|hi)\s+)?\b(?:sim|simorgh|seem|seam|زیم|سیم|سیمرغ)\b[^.?!]{0,40}?"
    r"\b(?:you\s+)?(?:can\s+|may\s+|please\s+)?"
    r"(?:talk|speak|come back|unmute|say something|answer|resume|wake up|back)\b"
    r"|\b(?:سیم|زیم)\b[^.?!]{0,30}?\b(?:حرف بزن|صحبت کن|برگرد|بیدار شو)\b", re.I)


def wants_to_talk_again(text: str) -> bool:
    """Whether `text` asks a hushed Sim to speak again."""
    return bool(_TALK_AGAIN.search(text or ""))


__all__ = ["HUSH", "MUTE", "OFF", "RESTART", "STOP", "hush_seconds", "opens_with_stop",
           "spoken_command", "wants_to_talk_again"]
