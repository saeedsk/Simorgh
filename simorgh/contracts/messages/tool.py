"""`tool.*` -- Execution's tool registry telemetry (section 4.7)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Int, List, O, Obj, Str
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
    F("provider", Enum("builtin", "skill", "mcp", "external")),
    # The tool's argument schema, as the model will be shown it (stage 2
    # item 1). `schema_ref` was always "", so nothing downstream could
    # know a tool's arguments; optional so older ledger records still read.
    O("input_schema", Obj()),
])
ToolUnavailable = define(t.TOOL_UNAVAILABLE, [F("name", Str), F("reason", Str)])
# One capability probe's finding (kernel/capabilities.py): whether the
# binary/package/service a tool stands on is working right now.
ToolProbed = define(t.TOOL_PROBED, [
    F("name", Str),
    F("ok", Bool),
    F("detail", Str),
    F("cost", Str),
    O("tools", List(Str)),
])
ToolStarted = define(t.TOOL_STARTED, [
    F("name", Str),
    F("action_id", Str),
    # What this tool has recently cost, in milliseconds, so a consumer
    # does not have to keep its own timing table: -1 when nothing is
    # known about it yet, which is not the same as "fast".
    F("recent_p95_ms", Int),
    O("session_id", Str),
    O("channel", Str),
])
ToolInvoked = define(t.TOOL_INVOKED, [
    F("name", Str),
    F("action_id", Str),
    F("duration_ms", Int),
    F("ok", Bool),
])
