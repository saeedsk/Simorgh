"""`percept.*` -- inputs entering the system (section 4.2)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, O, Str
from ..registry import define
from .. import topics as t

PerceptTextReceived = define(t.PERCEPT_TEXT_RECEIVED, [
    F("channel", Enum("cli", "api", "chat", "command", "voice")),
    F("text", Str),
    F("session_id", Str),
    O("user_id", Str),
    O("command", Str),
    O("steer", Bool),
    # A spoken turn (docs/plans/voice-design.md section 4.1): where it
    # was heard, who said it, and how sure the recogniser was.
    O("device", Str),
    O("speaker", Str),
    O("confidence", Float),
], doc="channel=command + command for routed commands; steer=true marks a mid-task correction; "
       "channel=voice carries device/speaker/confidence from the voice pipeline.")
PerceptFileChanged = define(t.PERCEPT_FILE_CHANGED, [
    F("path", Str),
    F("change", Enum("created", "modified", "deleted")),
    O("sha256", Str),
])
PerceptWebFetched = define(t.PERCEPT_WEB_FETCHED, [
    F("url", Str),
    F("status", Int),
    F("content_ref", Str),
    F("sha256", Str),
    F("fetched_at", Float),
])
PerceptTimeScheduled = define(t.PERCEPT_TIME_SCHEDULED, [
    F("schedule_id", Str),
    F("label", Str),
])
