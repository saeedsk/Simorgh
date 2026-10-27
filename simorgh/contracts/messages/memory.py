"""`memory.*` -- retrieval, storage, consolidation (section 4.9)."""

from __future__ import annotations

from ..fields import Bool, Enum, F, Float, Int, List, O, Obj, Str
from ..registry import define
from .. import topics as t

MEMORY_KIND = Enum("working", "episodic", "semantic", "procedural")
#: What `memory.forget` may reach: the kinds, and the consolidated facts
#: (`memory:facts`). `forget facts` / `forget all` were added to the
#: console on 2026-09-25 and this enum was not, so both were refused at
#: publish ("'facts' not in enum", live 2026-09-27) -- the one record kind
#: most worth removing stayed out of reach.
FORGET_KIND = Enum("working", "episodic", "semantic", "procedural", "facts")

MemoryRetrieve = define(t.MEMORY_RETRIEVE, [
    F("query", Str),
    F("kinds", List(MEMORY_KIND)),
    F("k", Int),
    O("budget_tokens", Int),
    O("filters", Obj(O("session_id", Str), O("task_type", Str), O("tags", List(Str)), O("since", Float))),
    # Stage 15 item 8: whose core memory blocks to send back as `core` --
    # the speaker's name, "" the console (the owner's). Absent, none.
    O("core_for", Str),
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
        # Stage 15. `hop` (1 or 2): reached through the entity graph rather
        # than by the query's words, and `via` the name of the entity it
        # was reached through. `summary: true` marks an entity's summary
        # line (not a fact), and `entity` is that entity's id.
        O("hop", Int), O("via", Str), O("summary", Bool), O("entity", Str),
    ))),
    # Stage 15 item 8: the core blocks a recall asked for with `core_for`,
    # sent only while `[memory] core_blocks` is on -- `[]` says "on, none
    # written". `block` is `household` or `person:<slug>`, `label` what a
    # prompt calls it.
    O("core", List(Obj(F("block", Str), F("label", Str), F("text", Str)))),
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
    O("minutes", Float), O("since", Float), O("until", Float), O("kinds", List(FORGET_KIND)),
    O("containing", Str), O("reason", Str),
])
MemoryForgetReply = define(t.MEMORY_FORGET_REPLY, [F("forgotten", Int), F("refs", List(Str)), O("since", Float)])
# Stage 15 item 8: one edit of a core memory block, Letta's
# `core_memory_replace` -- `old` replaced by `new` in `block` (`household`,
# `me`, or a person's name). `requester`/`requester_channel` are who asked,
# from Guardian's record of the proposal, never the model's arguments;
# Memory checks the block against them again. The reply says whether it
# was `edited`, the block's text after (or as it stands, when refused) and
# the `reason` when not -- not `ok`/`error`, which every reply reserves for
# "failed to answer" (registry.py).
MemoryCoreEdit = define(t.MEMORY_CORE_EDIT, [
    F("block", Str), O("old", Str), O("new", Str),
    F("requester", Str), O("requester_channel", Str),
    O("source_ref", Str), O("action_id", Str),
], doc="Command.")
MemoryCoreEditReply = define(t.MEMORY_CORE_EDIT_REPLY, [
    F("edited", Bool), F("block", Str), F("text", Str), F("reason", Str),
])
