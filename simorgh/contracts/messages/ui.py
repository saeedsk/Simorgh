"""`ui.*` -- Interface's human-facing surface (section 4.15)."""

from __future__ import annotations

from ..fields import Enum, F, Float, Int, List, O, Str
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
TvState = define(t.TV_STATE, [F("mode", Enum("none", "frame", "full")), O("url", Str), O("title", Str)],
                 doc="frame: `url` plays inside the TV page's box; full: the cast device plays it itself; "
                     "none: the terminal replica alone.")
TvSpeech = define(t.TV_SPEECH, [F("ref", Str), F("seconds", Float), O("seq", Int), O("request_id", Str),
                                 O("text", Str)],
                  doc="One piece of Sim's reply, as a WAV blob in the ledger, for the TV page to play in order.")
