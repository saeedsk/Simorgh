"""Emotion sub-agent: reacts to the input's affective content and updates
the persona's mood on the shared bus accordingly.
"""

from __future__ import annotations

import re

from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.persona_state import ArousalLevel, EmotionalState, Valence
from src.orchestrator.router import AgentRequest, AgentResponse, SubAgent

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
    (Valence.POSITIVE, ArousalLevel.HIGH): "That's exciting!",
    (Valence.POSITIVE, ArousalLevel.MODERATE): "That sounds nice.",
    (Valence.POSITIVE, ArousalLevel.LOW): "That's pleasant.",
    (Valence.NEGATIVE, ArousalLevel.HIGH): "That's really upsetting!",
    (Valence.NEGATIVE, ArousalLevel.MODERATE): "That's concerning.",
    (Valence.NEGATIVE, ArousalLevel.LOW): "That's a bit sad.",
    (Valence.NEUTRAL, ArousalLevel.HIGH): "That's a lot to take in!",
    (Valence.NEUTRAL, ArousalLevel.MODERATE): "I see.",
    (Valence.NEUTRAL, ArousalLevel.LOW): "Okay.",
}


class EmotionAgent(SubAgent):
    """Scores the input's words against small positive/negative/high-arousal
    lexicons, nudges the shared mood accordingly, and returns a short
    reaction phrase for the resulting state.
    """

    name = "emotion"

    def handle(self, request: AgentRequest, bus: SharedMemoryBus) -> AgentResponse:
        words = set(re.findall(r"[a-z']+", request.text.lower()))

        valence_delta = 0.15 * len(words & _POSITIVE_WORDS) - 0.15 * len(
            words & _NEGATIVE_WORDS
        )
        arousal_delta = 0.15 * len(words & _HIGH_AROUSAL_WORDS)
        if "!" in request.text:
            arousal_delta += 0.1

        new_state = bus.publish_delta(
            self.name, valence=valence_delta, arousal=arousal_delta
        )

        return AgentResponse(
            agent=self.name,
            output=self._describe(new_state),
            metadata={"valence": new_state.valence, "arousal": new_state.arousal},
        )

    @staticmethod
    def _describe(state: EmotionalState) -> str:
        return _REACTIONS[(state.valence_label, state.arousal_label)]
