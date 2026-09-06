"""`tool.*` -- Execution's tool registry telemetry (section 4.7)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Int, Str
from ..registry import define
from .. import topics as t
from .action import REVERSIBILITY

ToolRegistered = define(t.TOOL_REGISTERED, [
    F("name", Str),
    F("version", Str),
    F("description", Str),
    F("read_only", Bool),
    F("reversibility", REVERSIBILITY),
    F("schema_ref", Str),
    F("provider", Enum("builtin", "skill", "mcp")),
])
ToolUnavailable = define(t.TOOL_UNAVAILABLE, [F("name", Str), F("reason", Str)])
ToolInvoked = define(t.TOOL_INVOKED, [
    F("name", Str),
    F("action_id", Str),
    F("duration_ms", Int),
    F("ok", Bool),
])
