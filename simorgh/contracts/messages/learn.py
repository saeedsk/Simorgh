"""`learn.*` -- the self-improvement subsystem's surface (section 4.11)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

SelfEstimateRequest = define(t.SELF_ESTIMATE_REQUEST, [F("task_type", Str), O("strategy", Str)])
SelfEstimateReply = define(t.SELF_ESTIMATE_REPLY, [
    F("task_type", Str), F("mean", Float), F("samples", Float), F("alpha", Float), F("beta", Float),
    F("spread", Float), O("strategy", Str), O("calibration", Float), O("ece", Float),
    O("eval_suite", Str),
], doc="A Beta posterior over whether this task type succeeds: mean with the spread that says "
       "how much it rests on. Beta(1,1) -- mean 0.5, spread 0.29 -- means nothing is recorded yet, "
       "not that it succeeds half the time. `samples` is a FLOAT and an EFFECTIVE count: the "
       "competence table forgets exponentially (2026-09-21), so five outcomes seconds apart are "
       "4.999997 and an integer here would truncate one away at every boundary. `ece` is the "
       "expected calibration error when any confidence was stated.")
LearnStrategySuggest = define(t.LEARN_STRATEGY_SUGGEST, [F("task_type", Str), O("context", Obj())])
LearnStrategySuggestReply = define(t.LEARN_STRATEGY_SUGGEST_REPLY, [
    F("success_rate", Float),
    F("samples", Float),
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
    # A FLOAT, and an effective count: the competence table forgets
    # exponentially since 2026-09-21, so what "8 samples" means decays
    # between outcomes. An integer here rejected every publish the
    # moment forgetting landed -- live, in the creator's session, one
    # ContractError per completed task.
    F("samples", Float),
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
