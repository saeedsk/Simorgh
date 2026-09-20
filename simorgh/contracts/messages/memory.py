"""`memory.*` -- retrieval, storage, consolidation (section 4.9)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

MEMORY_KIND = Enum("working", "episodic", "semantic", "procedural")

MemoryRetrieve = define(t.MEMORY_RETRIEVE, [
    F("query", Str),
    F("kinds", List(MEMORY_KIND)),
    F("k", Int),
    O("budget_tokens", Int),
    O("filters", Obj(O("session_id", Str), O("task_type", Str), O("tags", List(Str)), O("since", Float))),
])
MemoryRetrieveReply = define(t.MEMORY_RETRIEVE_REPLY, [
    F("items", List(Obj(
        F("ref", Str), F("kind", MEMORY_KIND), F("content", Str),
        F("score", Float), F("confidence", Float), F("ts", Float),
    ))),
    F("truncated", Bool),
    # What HOLDS, as opposed to what was said (stage 5 item 3): the facts
    # the query mentions, each with what it replaced when it replaced one.
    O("facts", List(Obj(
        F("id", Str), F("subject", Str), F("predicate", Str), F("object", Str),
        F("person_scope", Str), F("confidence", Float), O("valid_from", Float),
        O("was", Str), O("was_until", Float), O("source_refs", List(Str)),
    ))),
])
MemoryStore = define(t.MEMORY_STORE, [
    F("kind", MEMORY_KIND),
    F("content", Str),
    F("tags", List(Str)),
    F("source_ref", Str),
    O("confidence", Float),
], doc="Command.")
MemoryStored = define(t.MEMORY_STORED, [F("ref", Str), F("kind", MEMORY_KIND)])
_FACT = [
    F("id", Str), F("subject", Str), F("predicate", Str), F("object", Str),
    F("person_scope", Str), F("valid_from", Float), F("confidence", Float),
    O("source_refs", List(Str)),
]
MemoryFactStored = define(t.MEMORY_FACT_STORED, _FACT)
MemoryFactSuperseded = define(t.MEMORY_FACT_SUPERSEDED, [
    F("id", Str), F("valid_to", Float), F("superseded_by", Str),
])
MemoryContradictionFlagged = define(t.MEMORY_CONTRADICTION_FLAGGED, [
    F("ref_a", Str),
    F("ref_b", Str),
    F("evidence", Str),
    F("confidence_after", Float),
])
MemoryConsolidated = define(t.MEMORY_CONSOLIDATED, [
    F("window", Float),
    F("distilled", Int),
    F("pruned", Int),
    # Distillations thrown away this cycle for naming things the
    # transcript never did (memory/consolidation.py::untraceable).
    # Optional: a publisher predating the check is still valid.
    O("refused", Int),
])
MemoryForgotten = define(t.MEMORY_FORGOTTEN, [F("refs", List(Str)), F("reason", Str)])
# "forget the last minute, that was all from TV" (the creator, 2026-09-13):
# the last `minutes`, or `since`..`until`; `kinds` default episodic;
# `containing` keeps it to records with those words. Request/reply.
MemoryForget = define(t.MEMORY_FORGET, [
    O("minutes", Float), O("since", Float), O("until", Float), O("kinds", List(MEMORY_KIND)),
    O("containing", Str), O("reason", Str),
])
MemoryForgetReply = define(t.MEMORY_FORGET_REPLY, [F("forgotten", Int), F("refs", List(Str)), O("since", Float)])
