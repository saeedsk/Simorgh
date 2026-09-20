"""`plan.*` and `project.*` -- planning artifacts and rollups (section 4.5)."""

from __future__ import annotations

from ..fields import Any_, Bool, Enum, F, Float, Int, List, O, Obj, Str  # noqa: F401
from ..registry import define
from .. import topics as t

STEP = Obj(
    F("step_id", Str),
    F("kind", Enum("patch", "skill", "research")),
    F("description", Str),
    F("depends_on", List(Str)),
    F("why", Str),
    O("subject", Str),
)
#: A plan node as the planner agent writes it (stage 7 item 3), and what
#: `planning/decomposer.py::parse_plan` validates its JSON against. Not a
#: message: the plan reaches Planning as the planner task's artifact, and
#: a shape nobody publishes should not pretend to be a topic. Wider
#: than STEP on purpose: a household goal decomposes into `action` and
#: `wait` nodes that name no repo path, and every node carries the
#: acceptance criteria the checkpoint critic scores it against.
PLAN_NODE = Obj(
    F("id", Str),
    F("kind", Enum("patch", "skill", "research", "action", "question", "wait")),
    F("description", Str),
    O("subject", Str),
    O("acceptance", List(Str)),
    O("depends_on", List(Str)),
    O("agent", Str),
)
CHECKLIST_ITEM = Obj(F("q", Str), F("answer", Str), F("evidence", Str))

PlanProposed = define(t.PLAN_PROPOSED, [
    F("plan_id", Str),
    F("task_id", Str),
    F("goal", Str),
    F("steps", List(STEP)),
    F("risk", Enum("low", "medium", "high")),
    F("estimated_cost", Float),
], doc="Published only by planning (single owner of plan:<id>).")
PlanReviewed = define(t.PLAN_REVIEWED, [
    F("plan_id", Str),
    F("verdict", Enum("approve", "revise", "reject", "insufficient_evidence")),
    F("checklist", List(CHECKLIST_ITEM)),
    O("feedback", Str),
])
PlanApproved = define(t.PLAN_APPROVED, [
    F("plan_id", Str),
    F("approved_by", Enum("human", "auto")),
    F("children", List(Str)),
])
PlanRevised = define(t.PLAN_REVISED, [
    F("plan_id", Str),
    F("reason", Str),
    F("diff", Obj(F("added", List(Any_)), F("removed", List(Any_)), F("reordered", List(Any_)))),
], doc="A plan change is an event with a reason, never a silent overwrite.")
PlanReground = define(t.PLAN_REGROUND, [
    F("plan_id", Str),
    F("task_id", Str),
    F("changes_since", List(Any_)),
])
PlanRegroundReply = define(t.PLAN_REGROUND_REPLY, [
    F("still_valid", Bool),
    F("reason", Str),
    O("suggested_revision", Obj()),
])
_PROJECT = [F("project_id", Str), F("done", Int), F("total", Int), F("summary", Str)]
ProjectCompleted = define(t.PROJECT_COMPLETED, _PROJECT)
ProjectFailed = define(t.PROJECT_FAILED, _PROJECT)
