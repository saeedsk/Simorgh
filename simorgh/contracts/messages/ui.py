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
TvState = define(t.TV_STATE, [F("mode", Enum("none", "frame", "full", "grid")), O("url", Str), O("title", Str),
                              O("urls", List(Str)), O("titles", List(Str))],
                 doc="frame: `url` plays inside the TV page's box; full: the cast device plays it itself; "
                     "grid: `urls` tiled across the whole page (the cameras); none: the terminal replica alone.")
TvSpeech = define(t.TV_SPEECH, [F("ref", Str), F("seconds", Float), O("seq", Int), O("request_id", Str),
                                 O("text", Str)],
                  doc="One piece of Sim's reply, as a WAV blob in the ledger, for the TV page to play in order.")
DashState = define(t.DASH_STATE, [O("view", Str), O("timeframe", Str), O("symbol", Str), O("rotate_s", Int), O("scale", Float)],
                   doc="Where the glass dashboard on the TV should look: a view name, the markets chart's timeframe "
                       "or symbol, a rotation period in seconds (0 stops). Any subset; the HTTP API merges it.")
UiHookReceived = define(t.UI_HOOK_RECEIVED, [F("name", Str), F("body", Str), O("content_type", Str),
                                             O("remote", Str)],
                        doc="An inbound webhook, body verbatim (capped by the API's body limit).")
