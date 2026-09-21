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
VerifyCheckpointRequest = define(t.VERIFY_CHECKPOINT_REQUEST, [
    F("task_id", Str), F("goal", Str), F("trajectory", Str), O("acceptance", List(Str)),
])
VerifyCheckpointReply = define(t.VERIFY_CHECKPOINT_REPLY, [
    F("verdict", Enum("on_track", "drifting", "blocked", "insufficient_evidence")),
    O("unmet", List(Str)), O("next", Str), O("why", Str), O("votes", Str),
], doc="Whether the work so far is still going to meet the acceptance criteria. "
       "`insufficient_evidence` when the trajectory does not say -- never guessed. "
       "`votes` (\"2/3\") is present when the verdict was confirmed by a second and "
       "third cheap sample, which happens only for a verdict that would end the attempt.")
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
