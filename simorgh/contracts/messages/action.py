"""`action.*` -- the guarded action path (section 4.6; docs/blueprint/
02 section 3). Only guardian may consume `action.proposed`; only
execution may consume `action.approved`."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

REVERSIBILITY = Enum("read_only", "reversible", "irreversible")
DENY_LAYER = Enum("policy", "denylist", "immunity", "budget", "paused", "scope", "classifier", "token")

ActionProposed = define(t.ACTION_PROPOSED, [
    F("action_id", Str),
    F("tool", Str),
    F("args", Obj()),
    F("scope", Obj(O("paths", List(Str)), F("network", Bool))),
    F("reversibility", REVERSIBILITY),
    F("rationale", Str),
    F("proposed_by", Str),
    O("task_id", Str),
])
ActionApproved = define(t.ACTION_APPROVED, [
    F("action_id", Str),
    F("tool", Str),
    F("args_sha256", Str),
    F("expires_at", Float),
    F("approval_token", Str),
    F("mode_at_approval", Str),
    O("constraints", Obj(O("timeout_s", Float), O("max_output_bytes", Int))),
], doc="Carries the HMAC approval token Execution must verify (security.py).")
ActionDenied = define(t.ACTION_DENIED, [
    F("action_id", Str),
    F("reasons", List(Str)),
    F("layer", DENY_LAYER),
    # Which tool was refused. Without it a consumer can only count that
    # *something* was denied, which is not enough to raise a useful task
    # about it (reflection/denials.py).
    O("tool", Str),
    # Which task this proposal belonged to, when it belonged to one at
    # all (an Interface command has none). Without it a consumer that
    # tracks per-task state (reflection/drift.py's DriftTracker) cannot
    # attribute a denial to the task it happened on -- reflection/service.py
    # needs this to feed a layer="scope" denial into that task's tracker.
    O("task_id", Str),
], doc="layer=classifier omits detailed reasons; execution may publish only layer=token.")
ActionNeedsHuman = define(t.ACTION_NEEDS_HUMAN, [
    F("action_id", Str),
    F("question", Str),
    F("options", List(Str)),
    O("default", Str),
])
ActionResult = define(t.ACTION_RESULT, [
    F("action_id", Str),
    F("ok", Bool),
    F("output_ref", Str),
    F("stdout_preview", Str),
    F("duration_ms", Int),
    F("side_effects", List(Str)),
    O("error", Str),
    # Everything the tool reported ABOUT its result, as a blob ref.
    # Optional because every producer before 2026-09-09 sent none, and
    # a replayed historical event must still validate.
    O("metadata_ref", Str),
])
