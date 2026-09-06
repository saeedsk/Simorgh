"""`research.*` -- a research task's finding (section 4.15; Flow 6)."""

from __future__ import annotations

from ..fields import F, O, Obj, Str
from ..registry import define
from .. import topics as t

ResearchFindingRecorded = define(t.RESEARCH_FINDING_RECORDED, [
    F("task_id", Str),
    F("finding_ref", Str),
    O("follow_up", Obj(F("subject", Str), F("description", Str))),
])
