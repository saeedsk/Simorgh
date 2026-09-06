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
])
MemoryStore = define(t.MEMORY_STORE, [
    F("kind", MEMORY_KIND),
    F("content", Str),
    F("tags", List(Str)),
    F("source_ref", Str),
    O("confidence", Float),
], doc="Command.")
MemoryStored = define(t.MEMORY_STORED, [F("ref", Str), F("kind", MEMORY_KIND)])
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
])
MemoryForgotten = define(t.MEMORY_FORGOTTEN, [F("refs", List(Str)), F("reason", Str)])
