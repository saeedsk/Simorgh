"""Logic sub-agent: drafts a response to the input, reading the persona's
current mood from the shared bus to shape its tone.
"""

from __future__ import annotations

from src.memory.shared_bus import SharedMemoryBus
from src.orchestrator.persona_state import ArousalLevel, EmotionalState, Valence
from src.orchestrator.router import AgentRequest, AgentResponse, SubAgent


class LogicAgent(SubAgent):
    """Reasons about the request in a straightforward, rule-based way, but
    frames its output differently depending on the mood/cognitive load it
    reads off the shared bus -- e.g. a distressed, high-arousal mood gets a
    calmer framing than a neutral one.
    """

    name = "logic"

    def handle(self, request: AgentRequest, bus: SharedMemoryBus) -> AgentResponse:
        mood = bus.read()
        new_state = bus.publish_delta(self.name, cognitive_load=0.05)

        return AgentResponse(
            agent=self.name,
            output=self._draft(request.text.strip(), mood),
            metadata={"cognitive_load": new_state.cognitive_load},
        )

    @staticmethod
    def _draft(text: str, mood: EmotionalState) -> str:
        if mood.valence_label is Valence.NEGATIVE and mood.arousal_label is ArousalLevel.HIGH:
            return f"Let's slow down and work through this: {text}"
        if mood.valence_label is Valence.POSITIVE and mood.arousal_label is ArousalLevel.HIGH:
            return f"Let's dive right in: {text}"
        if mood.cognitive_load >= 0.6:
            return f"Focusing carefully here -- {text}"
        return f"Here's my take: {text}"
