"""`reflect.*` -- meta-cognition findings (section 4.12)."""

from __future__ import annotations

from ..fields import Any_, Enum, F, Float, List, O, Obj, Str
from ..registry import define
from .. import topics as t

ReflectPatternsFound = define(t.REFLECT_PATTERNS_FOUND, [
    F("window", Float),
    F("patterns", List(Obj(F("kind", Str), F("rate", Float), F("proposal", Str), O("agent", Str)))),
])
ReflectDriftDetected = define(t.REFLECT_DRIFT_DETECTED, [
    F("kind", Enum("goal", "scope", "behavior")),
    F("evidence", Str),
    F("recommendation", Str),
    O("task_id", Str),
    O("plan_id", Str),
], doc="At least one of task_id / plan_id (validated by consumers).")
ReflectCalibrationUpdated = define(t.REFLECT_CALIBRATION_UPDATED, [
    F("task_type", Str),
    F("stated_confidence", Float),
    F("empirical_accuracy", Float),
])
ReflectHealthFinding = define(t.REFLECT_HEALTH_FINDING, [
    F("severity", Enum("info", "warn", "critical")),
    F("detail", Str),
    O("action_taken", Enum("none", "request_reset", "request_pause_hint")),
])
ReflectReviewRequest = define(t.REFLECT_REVIEW_REQUEST, [O("window_seconds", Float)])
ReflectReviewReply = define(t.REFLECT_REVIEW_REPLY, [
    F("patterns", List(Any_)),
    F("takeaways", List(Any_)),
])
