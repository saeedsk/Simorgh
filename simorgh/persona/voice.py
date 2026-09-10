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
        """The mood sentence always survives `max_chars`.

        This used to be `block[:max_chars]` over the joined string, so
        the identity summary was spent first and the mood phrase -- the
        one thing Persona contributes to the prompt that nothing else
        does -- was whatever happened to fall off the end. Measured
        before the fix: `voice.max_chars = 20` produced
        `'You are Simorgh, a c'`, and a 50,000-character `## Identity`
        paragraph produced 600 characters of that paragraph with no
        mood in it at all -- silently, with the phrase still sitting in
        the reply's `mood_phrase` field that `cognition/assembler.py`
        does not read. Observer bulk5-01, 2026-09-10.
        """
        phrase = mood_phrase(state)
        mood_sentence = f"Right now you're feeling {phrase}."
        room = max_chars - len(mood_sentence) - 1  # -1 for the joining space
        identity = self._identity_summary if room >= len(self._identity_summary) else self._identity_summary[:max(0, room)]
        block = f"{identity} {mood_sentence}".strip() if identity else mood_sentence
        return Voice(style_block=block[:max_chars], mood_phrase=phrase, register=register)
