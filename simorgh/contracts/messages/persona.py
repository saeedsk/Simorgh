"""`persona.*` -- identity, emotional state, voice, user model (section 4.14)."""

from __future__ import annotations

from ..fields import Any_, Enum, F, Float, O, Obj, Str
from ..registry import define
from .. import topics as t

_STATE = (F("valence", Float), F("arousal", Float), F("cognitive_load", Float))

PersonaStateChanged = define(t.PERSONA_STATE_CHANGED, [
    *_STATE,
    F("source", Str),
    F("previous", Obj(*_STATE)),
])
PersonaVoice = define(t.PERSONA_VOICE, [F("context", Enum("chat", "notice", "report"))])
PersonaVoiceReply = define(t.PERSONA_VOICE_REPLY, [F("style_block", Str), F("mood_phrase", Str)])
PersonaUserModelUpdated = define(t.PERSONA_USER_MODEL_UPDATED, [
    F("facet", Str),
    F("value", Any_),
    F("confidence", Float),
    # Whose sentence it was (stage 6 item 4): a household name, or "" for
    # the owner's console; `channel` says which, so World Model applies
    # the console rule (`channels.is_console`) rather than trusting "".
    # A payload with neither predates attribution and is filed nowhere.
    O("person", Str),
    O("channel", Str),
])
