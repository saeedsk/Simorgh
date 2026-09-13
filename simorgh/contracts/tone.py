"""The feeling a spoken reply is delivered with, named by the model in one
tag at the head of its answer -- `[warm] It's three o'clock.` -- and
never spoken. Shared by the voice subsystem (which turns it into speed,
loudness and pauses), by memory (which stores the words without it) and
by anything that prints the reply.

The creator, 2026-09-13: "I prefer to add emotion to Sim's voice." The
engines this runs on (Kokoro, Piper) have no emotion control of their
own, so the feeling is carried by delivery -- how fast, how loud, how
long the pauses -- and, when an expressive engine is present, by it.
"""

from __future__ import annotations

import re

#: tone -> (what it means; the delivery table in voice/delivery.py keys on these)
TONES: dict[str, str] = {
    "neutral": "plain and even",
    "warm": "gentle, close, unhurried -- for a hurt, a worry, good news shared quietly",
    "bright": "lively, quick, smiling -- for good news, a joke landing, enthusiasm",
    "calm": "slow and steady -- for reassurance, for a child at bedtime, for instructions",
    "serious": "measured, deliberate -- for a warning, a correction, something that matters",
    "playful": "light, quick, a little teasing -- for banter",
    "sorry": "soft and slow -- for an apology, a refusal, bad news",
}
_ALIASES = {"happy": "bright", "excited": "bright", "cheerful": "bright", "gentle": "warm", "kind": "warm",
            "soft": "warm", "sad": "sorry", "apologetic": "sorry", "grave": "serious", "stern": "serious",
            "urgent": "serious", "relaxed": "calm", "soothing": "calm", "fun": "playful", "teasing": "playful",
            "joking": "playful", "plain": "neutral", "flat": "neutral"}
_TAG = re.compile(r"^\s*[\[(<]\s*(?:tone\s*[:=]\s*)?([A-Za-z]{3,12})\s*[\])>]\s*[:\-–—]?\s*", re.I)


def split_tone(text: str) -> tuple[str, str]:
    """`("warm", "It's three o'clock.")` for `"[warm] It's three o'clock."`;
    `("", text)` when there is no tag or the word is not a tone."""
    match = _TAG.match(text or "")
    if not match:
        return "", text or ""
    word = match.group(1).lower()
    tone = word if word in TONES else _ALIASES.get(word, "")
    if not tone:
        return "", text or ""
    return tone, (text or "")[match.end():]


def strip_tone(text: str) -> str:
    return split_tone(text)[1]


__all__ = ["TONES", "split_tone", "strip_tone"]
