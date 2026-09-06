"""`self.*` -- the Self Model surface (section 4.10). `self.model.updated`
is published only by worldmodel (single writer of `self:model`);
reflection contributes `self.observation`."""

from __future__ import annotations

from ..fields import Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

SelfSummary = define(t.SELF_SUMMARY, [F("budget_tokens", Int)])
SelfSummaryReply = define(t.SELF_SUMMARY_REPLY, [F("text", Str), F("version", Int)])
SelfGaps = define(t.SELF_GAPS, [F("k", Int)])
SelfGapsReply = define(t.SELF_GAPS_REPLY, [
    F("version", Int),
    F("gaps", List(Obj(F("competence", Str), F("task_type", Str), F("score", Float), F("samples", Int)))),
    F("unexplored_areas", List(Obj(
        F("area", Str), F("modules", List(Str)), F("tasks_ever", Int), O("last_touched", Float),
    ))),
])
SelfModelUpdated = define(t.SELF_MODEL_UPDATED, [
    F("version", Int),
    F("changed_sections", List(Str)),
    F("reason", Str),
])
SelfObservation = define(t.SELF_OBSERVATION, [
    F("kind", Enum("restart", "change", "limitation", "success", "failure", "open_question")),
    F("detail", Str),
    O("ref", Str),
], doc="`open_question` added alongside Self Model completeness (milestone "
       "115): the Self Model's own `open_questions` section has no "
       "producer yet -- nothing publishes this kind -- so it stays empty "
       "until something does; the enum value exists so a future producer "
       "doesn't also need a contracts change.")
