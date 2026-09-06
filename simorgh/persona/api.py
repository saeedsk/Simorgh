"""Public surface re-exports for `simorgh.persona` consumers/tests."""

from __future__ import annotations

from .emotion import MoodDelta, react, reaction_phrase
from .mood import EmotionalState, MoodEngine
from .sharing import ShareDecision, SharePolicy
from .user_model import Facet, UserModel
from .voice import Voice, VoiceComposer, mood_phrase

__all__ = [
    "EmotionalState", "MoodEngine", "MoodDelta", "react", "reaction_phrase",
    "Voice", "VoiceComposer", "mood_phrase", "Facet", "UserModel",
    "ShareDecision", "SharePolicy",
]
