"""`growth.*` -- what Sim decided to do differently (stage 8 item 4).

A lesson that only becomes a memory record changes nothing: the next
session recalls it if the vocabulary happens to match, and otherwise
repeats the mistake. A policy is the durable form -- with the evidence
that motivated it, the measurement that justified it, and a way back.

These four say what happened to one. `growth.lesson.found` is the
counting's output, before anything is decided; the three `policy.*`
are the decision itself.
"""

from __future__ import annotations

from ..fields import Enum, F, Float, Int, List, O, Str
from ..registry import define
from .. import topics as t

GrowthLessonFound = define(t.GROWTH_LESSON_FOUND, [
    # Which counting found it: a failure cluster, the denial miner, or
    # the pattern miner (`growth/diagnose.py::Candidate`).
    F("source", Enum("failures", "denials", "patterns")),
    F("what", Str),
    F("count", Int),
    O("subject", Str),        # the task type or the tool it is about
    O("evidence", List(Str)),
], doc="Something that keeps happening, found by counting. Not a decision: nothing has changed "
       "because of it yet.")

_POLICY = [
    F("policy_id", Str),
    F("kind", Enum("rule", "skill", "routing", "patch")),
    F("task_type", Str),
    F("body", Str),
    O("why", Str),
    O("evidence_refs", List(Str)),
]

GrowthPolicyProposed = define(t.GROWTH_POLICY_PROPOSED, list(_POLICY))
GrowthPolicyAdopted = define(t.GROWTH_POLICY_ADOPTED, [
    *_POLICY,
    # What it was measured against, and what it got. An adoption
    # without both is the thing this subsystem exists not to do.
    F("baseline", Float),
    F("result", Float),
    F("evaluated_on", Int),
    O("ttl_s", Float),
])
GrowthPolicyRetired = define(t.GROWTH_POLICY_RETIRED, [
    *_POLICY,
    F("reason", Str),
], doc="A policy stopped: its TTL ran out, or the task type it was about got worse. Every policy "
       "is reversible and time-bounded, so this is the ordinary end of one, not a failure.")

__all__ = ["GrowthLessonFound", "GrowthPolicyAdopted", "GrowthPolicyProposed", "GrowthPolicyRetired"]
