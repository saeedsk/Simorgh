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
    STOP: ("stop", "stop talking", "stop it", "be quiet", "quiet", "shut up", "enough", "hush", "shush",
           "that's enough", "okay stop", "ok stop", "stop please", "بس کن", "بسه", "ساکت", "ساکت شو", "خفه شو",
           "دیگه بسه", "کافیه"),
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


__all__ = ["MUTE", "OFF", "RESTART", "STOP", "opens_with_stop", "spoken_command"]
