"""`intent.*` -- a goal stated by a human or by the system's own drives
(section 4.3)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

IntentGoalStated = define(t.INTENT_GOAL_STATED, [
    F("goal", Str),
    F("origin", Enum("human", "curiosity", "reflection")),
    F("priority", Int),
    F("wants_project", Bool),
    O("constraints", Obj(O("scope", List(Str)), O("deadline", Float))),
])
