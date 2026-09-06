"""`percept.*` -- inputs entering the system (section 4.2)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, O, Str
from ..registry import define
from .. import topics as t

PerceptTextReceived = define(t.PERCEPT_TEXT_RECEIVED, [
    F("channel", Enum("cli", "api", "chat", "command")),
    F("text", Str),
    F("session_id", Str),
    O("user_id", Str),
    O("command", Str),
    O("steer", Bool),
], doc="channel=command + command for routed commands; steer=true marks a mid-task correction.")
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
