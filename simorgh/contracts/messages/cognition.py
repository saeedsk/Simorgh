"""`cognition.*` -- the reasoning engine's request/reply and compaction
surface (section 4.15). `floor: true` on a reply is a *value*, not an
error: no real provider answered (docs/blueprint/03 section 9)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

CognitionThink = define(t.COGNITION_THINK, [
    F("purpose", Enum("chat", "draft", "plan", "review", "research", "decompose", "reground", "consolidate")),
    F("messages", List(Obj(F("role", Str), F("content", Str)))),
    F("budget", Obj(F("max_tokens", Int), F("max_cost_usd", Float))),
    F("require_real_provider", Bool),
    O("session_id", Str),
    O("tools", List(Str)),
    O("expected", Enum("text", "tool_calls", "edit_blocks", "verdict")),
    O("allow_summarize", Bool),
    O("last_step", Bool),
])
CognitionThinkReply = define(t.COGNITION_THINK_REPLY, [
    F("text", Str),
    F("tool_calls", List(Obj(F("tool", Str), F("args", Obj())))),
    F("provider", Str),
    F("cost_usd", Float),
    F("tokens", Int),
    F("floor", Bool),
    F("non_answer", Bool),
    O("edit_blocks", List(Obj(F("search", Str), F("replace", Str)))),
    O("confidence", Float),
    O("agreement", Bool),
    O("compaction", Obj(F("layers_applied", List(Str)), F("tokens_before", Int), F("tokens_after", Int))),
])
CognitionCompactRequest = define(t.COGNITION_COMPACT_REQUEST, [F("session_id", Str), F("target_tokens", Int)])
CognitionCompactReply = define(t.COGNITION_COMPACT_REPLY, [
    F("layers_applied", List(Str)),
    F("tokens_before", Int),
    F("tokens_after", Int),
    O("summary_ref", Str),
])
_COMPACT_HOOK = [F("session_id", Str), F("layer", Str)]
CognitionCompactPre = define(t.COGNITION_COMPACT_PRE, _COMPACT_HOOK, doc="The PreCompact hook event.")
CognitionCompactDone = define(t.COGNITION_COMPACT_DONE, _COMPACT_HOOK)
CognitionProviderStatus = define(t.COGNITION_PROVIDER_STATUS, [
    F("provider", Str),
    F("available", Bool),
    F("budget", Obj()),
])
