"""`guardian.*` -- the review req/rep Verification uses on candidate
code, and the trust posture (section 4.15)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

GuardianReview = define(t.GUARDIAN_REVIEW, [
    F("subject", Str),
    F("code_ref", Str),
    F("kind", Enum("self_patch", "skill")),
])
GuardianReviewReply = define(t.GUARDIAN_REVIEW_REPLY, [
    F("approved", Bool),
    F("reasons", List(Str)),
    F("layers_run", List(Str)),
])
GuardianPostureChanged = define(t.GUARDIAN_POSTURE_CHANGED, [
    F("mode", Enum("observe", "plan", "guarded", "trusted", "locked")),
    F("trust_score", Float),
    F("reason", Str),
])
GuardianPostureRequest = define(t.GUARDIAN_POSTURE_REQUEST, [])
GuardianStandingRequest = define(t.GUARDIAN_STANDING_REQUEST, [
    F("action", Enum("list", "revoke")),
    O("key", Str),
], doc="list: every standing approval; revoke: drop the one whose `key` is given, or all with key=\"all\".")
GuardianStandingReply = define(t.GUARDIAN_STANDING_REPLY, [
    F("standing", List(Obj())),
    O("revoked", Int),
], doc="standing: [{key, tool, requester, layer, approved_at, uses}] -- what \"always\" has approved.")
GuardianPostureReply = define(t.GUARDIAN_POSTURE_REPLY, [
    F("mode", Enum("observe", "plan", "guarded", "trusted", "locked")),
    F("trust_score", Float),
    F("tightened_by", List(Str)),
    O("paused_scope", Enum("all", "autonomous")),
])
