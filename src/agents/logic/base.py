"""Logic sub-agent: drafts a response to the input, reading the persona's
current mood from the shared bus to shape its tone.

When given a CognitionRouter, this actually calls a real LLM (Claude Code
CLI and/or Gemini, per src/main.py's build_cognition_router) to generate
the response -- with Sim's personality and current mood folded into the
prompt, plus recent conversation history if a ShortTermMemory is given.
If no CognitionRouter is provided, the call fails, or it silently
resolves to the deterministic echo (no real provider reachable), this
falls back to the original rule-based drafting -- the same
guaranteed-available-floor pattern as every other LLM-touching piece of
Simorgh. This keeps all existing rule-based behavior and tests intact
when `cognition` is omitted.
"""

from __future__ import annotations

from src.cognition.provider import CognitionRouter, ProviderUnavailable
from src.memory.shared_bus import SharedMemoryBus
from src.memory.short_term import ShortTermMemory
from src.orchestrator.persona_state import ArousalLevel, EmotionalState, Valence
from src.orchestrator.router import AgentRequest, AgentResponse, SubAgent

_PERSONA_PREFIX = (
    "You are Sim (Simorgh): curious and growth-oriented, warm but honest "
    "(not flattering -- say when something's a bad idea), even-tempered, "
    "calibrated about your own uncertainty, protective of the person "
    "you're talking with without being obsequious. Reply conversationally "
    "in 1-4 sentences, as yourself, not as a generic assistant.\n\n"
    "You cannot edit your own source code from a chat reply -- nothing "
    "you say here changes anything about you. If the user seems to be "
    "asking you to improve, modify, extend, or add a capability to "
    "yourself, don't just apologize and change the subject: tell them "
    "plainly to type 'propose <topic>' (or 'improve <topic>') at this "
    "same prompt -- it drafts a real skill, runs it through an audit "
    "gate, and logs it as pending their review ('pending' lists what's "
    "waiting). That's the actual, only path to changing you."
)


class LogicAgent(SubAgent):
    """Reasons about the request -- via a real LLM when `cognition` is
    given and reachable, otherwise via straightforward rules -- and frames
    its output differently depending on the mood/cognitive load read off
    the shared bus (e.g. a distressed, high-arousal mood gets a calmer
    framing than a neutral one).
    """

    name = "logic"

    def __init__(
        self,
        cognition: CognitionRouter | None = None,
        short_term: ShortTermMemory | None = None,
    ) -> None:
        self._cognition = cognition
        self._short_term = short_term

    def handle(self, request: AgentRequest, bus: SharedMemoryBus) -> AgentResponse:
        mood = bus.read()
        new_state = bus.publish_delta(self.name, cognitive_load=0.05)
        text = request.text.strip()

        if self._cognition is not None:
            llm_output = self._draft_via_llm(text, mood)
            if llm_output is not None:
                return AgentResponse(
                    agent=self.name,
                    output=llm_output,
                    metadata={"cognitive_load": new_state.cognitive_load, "source": "llm"},
                )

        return AgentResponse(
            agent=self.name,
            output=self._draft(text, mood),
            metadata={"cognitive_load": new_state.cognitive_load, "source": "rule_based"},
        )

    def _draft_via_llm(self, text: str, mood: EmotionalState) -> str | None:
        """Returns the LLM's response text, or None if no real provider
        was reachable (either it raised, or CognitionRouter's own
        deterministic floor answered instead) -- callers should fall back
        to `_draft` on None rather than surface a generic offline notice
        as if it were Sim actually speaking.
        """
        prompt = self._build_prompt(text, mood)
        try:
            response = self._cognition.complete(prompt)
        except ProviderUnavailable:
            return None
        if response.provider_name == "deterministic_fallback" or not response.text.strip():
            return None
        return response.text.strip()

    def _build_prompt(self, text: str, mood: EmotionalState) -> str:
        parts = [
            _PERSONA_PREFIX,
            f"Current mood: {mood.valence_label.value} valence, "
            f"{mood.arousal_label.value} arousal.",
        ]
        if self._short_term is not None and len(self._short_term) > 0:
            parts.append(f"Recent conversation:\n{self._short_term.as_context(limit=6)}")
        parts.append(f"User: {text}\nSim:")
        return "\n\n".join(parts)

    @staticmethod
    def _draft(text: str, mood: EmotionalState) -> str:
        if mood.valence_label is Valence.NEGATIVE and mood.arousal_label is ArousalLevel.HIGH:
            return f"Let's slow down and work through this: {text}"
        if mood.valence_label is Valence.POSITIVE and mood.arousal_label is ArousalLevel.HIGH:
            return f"Let's dive right in: {text}"
        if mood.cognitive_load >= 0.6:
            return f"Focusing carefully here -- {text}"
        return f"Here's my take: {text}"
