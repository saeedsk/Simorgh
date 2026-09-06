"""`verify.*` -- independent verification (section 4.8)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t
from .plan import CHECKLIST_ITEM

VerifyRequested = define(t.VERIFY_REQUESTED, [
    F("verification_id", Str),
    F("task_id", Str),
    F("kind", Enum("task", "plan", "self_patch", "skill")),
    F("subject_ref", Str),
    O("checklist_hint", Str),
])
VerifyResult = define(t.VERIFY_RESULT, [
    F("verification_id", Str),
    F("task_id", Str),
    F("verdict", Enum("pass", "fail", "insufficient_evidence")),
    F("checklist", List(CHECKLIST_ITEM)),
    F("trajectory", Obj(F("steps", Int), F("wasted", Int), F("recovered_errors", Int))),
    F("mechanical", Obj(O("tests_passed", Bool), O("baseline", Int), O("patched", Int))),
    O("feedback", Obj(F("items", List(Obj(F("what", Str), F("why", Str), F("suggested_fix", Str)))))),
    O("confidence", Float),
], doc="A non-answer from the reviewer is insufficient_evidence, never fail.")
