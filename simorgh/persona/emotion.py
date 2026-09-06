"""The rule-based emotion floor -- a direct port of v1's
`src/agents/emotion/base.py`: small positive/negative/high-arousal
lexicons scored against the input text, no LLM, no dependency. This is
what makes Persona's mood reaction the guaranteed floor (01 section 4.5)
-- it works even with every provider down.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_POSITIVE_WORDS = {
    "great", "good", "love", "happy", "thanks", "thank", "awesome",
    "excited", "wonderful", "nice", "glad", "yay",
}
_NEGATIVE_WORDS = {
    "bad", "hate", "sad", "angry", "terrible", "annoyed", "frustrated",
    "worried", "sorry", "awful", "broken", "fail",
}
_HIGH_AROUSAL_WORDS = {"urgent", "now", "asap", "emergency", "wow", "amazing", "help"}

_REACTIONS = {
    ("positive", "high"): "That's exciting!",
    ("positive", "moderate"): "That sounds nice.",
    ("positive", "low"): "That's pleasant.",
    ("negative", "high"): "That's really upsetting!",
    ("negative", "moderate"): "That's concerning.",
    ("negative", "low"): "That's a bit sad.",
    ("neutral", "high"): "That's a lot to take in!",
    ("neutral", "moderate"): "I see.",
    ("neutral", "low"): "Okay.",
}


@dataclass(frozen=True)
class MoodDelta:
    valence: float
    arousal: float


def react(text: str, *, lexicon_weight: float = 0.15, exclamation_arousal: float = 0.10) -> MoodDelta:
    words = set(re.findall(r"[a-z']+", text.lower()))
    valence_delta = lexicon_weight * len(words & _POSITIVE_WORDS) - lexicon_weight * len(words & _NEGATIVE_WORDS)
    arousal_delta = lexicon_weight * len(words & _HIGH_AROUSAL_WORDS)
    if "!" in text:
        arousal_delta += exclamation_arousal
    return MoodDelta(valence=valence_delta, arousal=arousal_delta)


def reaction_phrase(valence_label: str, arousal_label: str) -> str:
    return _REACTIONS.get((valence_label, arousal_label), "I see.")
