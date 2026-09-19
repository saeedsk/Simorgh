"""`learn.*` -- the self-improvement subsystem's surface (section 4.11)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

LearnStrategySuggest = define(t.LEARN_STRATEGY_SUGGEST, [F("task_type", Str), O("context", Obj())])
LearnStrategySuggestReply = define(t.LEARN_STRATEGY_SUGGEST_REPLY, [
    F("success_rate", Float),
    F("samples", Int),
    O("strategy", Obj(F("approach", Str), F("provider", Str), F("purpose_config", Obj()))),
])
LearnOutcomeRecorded = define(t.LEARN_OUTCOME_RECORDED, [
    F("task_id", Str),
    F("task_type", Str),
    F("succeeded", Bool),
    F("verdict", Str),
    F("cost_usd", Float),
    F("duration_s", Float),
    O("strategy", Str),
    O("confidence", Float),
])
LearnCompetenceUpdated = define(t.LEARN_COMPETENCE_UPDATED, [
    F("task_type", Str),
    F("success_rate", Float),
    F("calibration", Float),
    F("samples", Int),
])
LearnSkillAcquired = define(t.LEARN_SKILL_ACQUIRED, [
    F("name", Str), F("path", Str), F("tests", Int), O("description", Str),
], doc="05-memory.md's own dependency table describes this as producing a "
       "procedural record {name, description, path, tests} directly -- "
       "`description` is optional here (a producer built against v1 of "
       "this catalog entry still validates) so a consumer can read it "
       "straight off this event once a producer sets it, instead of every "
       "consumer needing its own paired `memory.store` publish.")
_SELF_PATCH = [
    F("subject", Str),
    F("commit", Str),
    # Optional since 2026-09-19: the landing path (orchestration/session.py
    # `_land`) knows the commit but not the test counts; the retired
    # PatchPipeline was the only publisher that did.
    O("tests", Obj(F("baseline", Int), F("patched", Int))),
    O("reason", Str),
]
LearnSelfPatchApplied = define(t.LEARN_SELF_PATCH_APPLIED, _SELF_PATCH)
LearnSelfPatchReverted = define(t.LEARN_SELF_PATCH_REVERTED, _SELF_PATCH)
LearnExperimentResult = define(t.LEARN_EXPERIMENT_RESULT, [
    F("experiment_id", Str),
    F("variant", Str),
    F("metric", Float),
    F("promoted", Bool),
])
