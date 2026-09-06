"""`mood_phrase` (v1 port, `src/agents/logic/base.py`) and a minimal
`VoiceComposer` -- a condensed identity block plus the natural-language
mood phrase, for Cognition's future prompt assembly (`persona.voice`).
"""

from __future__ import annotations

from dataclasses import dataclass

from .mood import EmotionalState

_MOOD_PHRASES = {
    ("positive", "high"): "excited, energized",
    ("positive", "moderate"): "upbeat, engaged",
    ("positive", "low"): "content, at ease",
    ("negative", "high"): "distressed, on edge",
    ("negative", "moderate"): "a bit down",
    ("negative", "low"): "quietly unsettled",
    ("neutral", "high"): "alert, focused",
    ("neutral", "moderate"): "attentive",
    ("neutral", "low"): "calm, nothing much going on",
}


def mood_phrase(mood: EmotionalState) -> str:
    return _MOOD_PHRASES.get((mood.valence_label, mood.arousal_label), f"{mood.valence_label}, {mood.arousal_label} energy")


@dataclass(frozen=True)
class Voice:
    style_block: str
    mood_phrase: str
    register: str = "neutral"


class VoiceComposer:
    def __init__(self, identity_summary: str) -> None:
        self._identity_summary = identity_summary

    def compose(self, state: EmotionalState, *, register: str = "neutral", max_chars: int = 600) -> Voice:
        phrase = mood_phrase(state)
        block = f"{self._identity_summary} Right now you're feeling {phrase}."
        return Voice(style_block=block[:max_chars], mood_phrase=phrase, register=register)
