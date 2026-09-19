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
    # Stream the reply as `session.delta` to this id while it is written
    # (stage 3 item 2); the reply itself still comes back whole.
    O("stream", Bool), O("stream_to", Str),
    O("task_rules", Str),  # protected prompt block: how this profile finishes its work
    O("expected", Enum("text", "tool_calls", "edit_blocks", "verdict")),
    # Pictures to look at, as absolute paths Cognition can read (a camera
    # still, a screenshot). Paths, not bytes: a base64 JPEG in the payload
    # would be written into the Ledger for every call. Only a provider
    # that says `supports_images` is dialled when these are set.
    O("images", List(Str)),
    O("allow_summarize", Bool),
    O("last_step", Bool),
    # Tool calls left in this attempt. So the assembler can tell the
    # model to wind down BEFORE the wall rather than at it -- a run that
    # only learns its budget on the final step discovers the limit at
    # the moment it can no longer act on it.
    O("steps_left", Int),
    # Read-only tools the session runs together when one reply asks for
    # several, up to `max_parallel_tools` ([orchestration]
    # parallel_read_tools). Absent: one tool call per reply.
    O("parallel_tools", List(Str)),
    O("max_parallel_tools", Int),
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
    # Which model this provider is actually configured to call, and
    # whether it is the one currently answering. Without these, nothing
    # downstream can say what is thinking -- asked directly, Sim could
    # only answer honestly that it had no way to know (2026-09-07).
    O("model", Str),
    O("selected", Bool),
])
