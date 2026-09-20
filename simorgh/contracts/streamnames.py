"""What a stream may be called.

The grammar lives here rather than in the Ledger because it is not only
the Ledger's business: anything that builds a stream name from something
a caller supplied has to know whether the result is legal BEFORE the
work starts, and a subsystem may not import another subsystem to ask.

The cost of not knowing, live 2026-09-10: the dashboard accepted a chat
`session_id` containing a slash, ran the whole turn, got a real answer
from the model, and then raised inside the worker's own reporting --
where nothing retrieves the exception -- so `turn.completed` was never
published and the caller waited out the full chat timeout to be told
"no response in time". An uppercase letter did the same thing, which
means a client sending uppercase UUIDs met a two-minute silence.

Restrictive on purpose, so a stream name is always a safe filename, a
safe key, and a safe log line.
"""

from __future__ import annotations

import re

MAX_STREAM_NAME = 128
_NAME = re.compile(r"^[a-z0-9_.:-]{1,128}$")


def is_valid_stream(name: str) -> bool:
    return isinstance(name, str) and bool(_NAME.match(name))


def stream_name_rule() -> str:
    """The grammar, in words, for a message a person or a model reads."""
    return f"lowercase letters, digits, and _ . : - only, at most {MAX_STREAM_NAME} characters"


__all__ = ["MAX_STREAM_NAME", "is_valid_stream", "stream_name_rule"]


# Which subsystems may write which streams (stage 1 item 8). Filled from a
# recorded run of every test that boots subsystems (SIMORGH_LEDGER_WRITER_AUDIT),
# not from the informational owner table in `ledger/streams.py`, which had
# drifted. A stream matching no prefix here is unrestricted.
WRITERS: dict[str, frozenset[str]] = {
    # Two writers each, both observed: Guardian records the decision,
    # Execution the run; Planning owns the task, Orchestration its steps.
    "action:": frozenset({"guardian", "execution"}),
    "task:": frozenset({"planning", "orchestration"}),
    # Typed transcripts (stage 4): Orchestration runs every session.
    "session:": frozenset({"orchestration"}),
    "project:": frozenset({"planning"}),
    "plan:": frozenset({"planning"}),
    "planning:": frozenset({"planning"}),
    "guardian:": frozenset({"guardian"}),
    # The self model and the world are WorldModel's alone (the
    # evaluation's example: Reflection must not write `self:model`).
    "self:": frozenset({"worldmodel"}),
    "world:": frozenset({"worldmodel"}),
    "memory:": frozenset({"memory"}),
    "persona:": frozenset({"persona"}),
    "cognition:": frozenset({"cognition"}),
    "verify:": frozenset({"verification"}),
    # One subsystem writes all four since the growth merge (stage 8
    # item 1): `learning`, `reflection` and `curiosity` became parts of
    # `growth` and publish under its name, but this table still said
    # otherwise -- so from the merge until 2026-09-20 every write to
    # these prefixes raised `WriterViolation` and growth silently
    # recorded nothing at all: no outcomes, no findings, no ticks. The
    # module tiers did not catch it because they build a Service
    # directly, and only a booted Kernel hands out a BOUND ledger. The
    # household simulator found it on its second real boot.
    #
    # The stream names keep their old prefixes on purpose: renaming
    # them would orphan every event written before the merge.
    "learn:": frozenset({"growth"}),
    "reflect:": frozenset({"growth"}),
    "reflection:": frozenset({"growth"}),
    "curiosity:": frozenset({"growth"}),
    "growth:": frozenset({"growth"}),
    "voice:": frozenset({"voice"}),
    "benchmark:": frozenset({"benchmark"}),
    "execution:": frozenset({"execution"}),
    "mcp:": frozenset({"execution"}),
    "capabilities": frozenset({"execution", "voice"}),
    "ledger:": frozenset({"ledger"}),
    # The Kernel's own streams: it writes them through its own client,
    # which is not bound; no subsystem writes them.
    "system": frozenset({"kernel"}),
    "schedule": frozenset({"kernel"}),
    "config:": frozenset({"kernel"}),
    "metrics:": frozenset({"kernel"}),
}


def writers_for(stream: str) -> frozenset[str] | None:
    """The subsystems allowed to write `stream`, by its longest matching
    prefix in `WRITERS`; None when no prefix names it."""
    best = None
    for prefix, who in WRITERS.items():
        if (stream == prefix or stream.startswith(prefix)) and (best is None or len(prefix) > len(best[0])):
            best = (prefix, who)
    return None if best is None else best[1]
