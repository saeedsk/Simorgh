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
