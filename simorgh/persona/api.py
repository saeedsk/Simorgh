"""Public surface re-exports for `simorgh.persona` consumers/tests.

Imports are lazy: touching a name here resolves it on demand via module-level
``__getattr__``, so importing `simorgh.persona.api` no longer eagerly pulls in
emotion/mood/user_model/voice (and their transitive dependencies). Missing or
mistyped names raise an AttributeError naming the valid ``__all__`` entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .emotion import MoodDelta, react, reaction_phrase
    from .mood import EmotionalState, MoodEngine
    from .user_model import CONSOLE_CHANNELS, OWNER, Facet, UserModel, attribute
    from .voice import Voice, VoiceComposer, mood_phrase

__all__ = [
    "EmotionalState", "MoodEngine", "MoodDelta", "react", "reaction_phrase",
    "Voice", "VoiceComposer", "mood_phrase", "Facet", "UserModel",
    "CONSOLE_CHANNELS", "OWNER", "attribute",
]

_LAZY_IMPORTS = {
    "EmotionalState": ".mood",
    "MoodEngine": ".mood",
    "MoodDelta": ".emotion",
    "react": ".emotion",
    "reaction_phrase": ".emotion",
    "Voice": ".voice",
    "VoiceComposer": ".voice",
    "mood_phrase": ".voice",
    "Facet": ".user_model",
    "UserModel": ".user_model",
    "CONSOLE_CHANNELS": ".user_model",
    "OWNER": ".user_model",
    "attribute": ".user_model",
}


def __getattr__(name: str):
    module = _LAZY_IMPORTS.get(name)
    if module is None:
        valid = ", ".join(sorted(__all__))
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}; "
            f"valid exports are: {valid}"
        )
    from importlib import import_module

    value = getattr(import_module(module, __name__), name)
    globals()[name] = value  # cache so later lookups skip the import
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
