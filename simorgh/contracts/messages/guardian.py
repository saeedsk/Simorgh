"""`guardian.*` -- the review req/rep Verification uses on candidate
code, and the trust posture (section 4.15)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, List, O, Str
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
GuardianPostureReply = define(t.GUARDIAN_POSTURE_REPLY, [
    F("mode", Enum("observe", "plan", "guarded", "trusted", "locked")),
    F("trust_score", Float),
    F("tightened_by", List(Str)),
    O("paused_scope", Enum("all", "autonomous")),
])
