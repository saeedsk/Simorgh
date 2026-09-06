"""`ui.*` -- Interface's human-facing surface (section 4.15)."""

from __future__ import annotations

from ..fields import F, Float, List, O, Str
from ..registry import define
from .. import topics as t

UiNotice = define(t.UI_NOTICE, [F("level", Str), F("text", Str), F("source", Str)])
UiPrompt = define(t.UI_PROMPT, [
    F("prompt_id", Str),
    F("question", Str),
    F("options", List(Str)),
    F("timeout_s", Float),
    O("default", Str),
])
UiPromptAnswered = define(t.UI_PROMPT_ANSWERED, [F("prompt_id", Str), F("answer", Str)])
UiRendered = define(t.UI_RENDERED, [F("channel", Str), F("text", Str)])
