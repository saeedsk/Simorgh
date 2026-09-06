"""Stream naming (02-ledger section 4.1): the grammar, the filename
escaping the `jsonl` backend uses, and the registry of known prefixes
with their owning subsystem. Names are `<kind>[:<id>]`, lowercase,
`[a-z0-9_.:-]`, at most 128 characters -- restrictive on purpose, so a
stream name is always a safe filename, DynamoDB key, and log line.
"""

from __future__ import annotations

import re

MAX_STREAM_NAME = 128
_NAME = re.compile(r"^[a-z0-9_.:-]{1,128}$")

# Prefix -> owning subsystem. Informational (the Ledger does not enforce
# writers -- the Kernel's topology rules do that at the message level);
# `retention` policies in config are keyed by these prefixes.
KNOWN_PREFIXES: dict[str, str] = {
    "trace:": "bus",
    "dead:": "bus",
    "activity": "orchestration",
    "task:": "planning",
    "project:": "planning",
    "plan:": "planning",
    "action:": "guardian",
    "verify:": "verification",
    "memory:": "memory",
    "self:": "worldmodel",
    "world:": "worldmodel",
    "learn:": "learning",
    "reflect:": "reflection",
    "curiosity:": "curiosity",
    "persona:": "persona",
    "cognition:": "cognition",
    "guardian:": "guardian",
    "schedule": "kernel",
    "system": "kernel",
    "ledger:": "ledger",
}

COMPACTION_STREAM = "ledger:compaction"


def is_valid_stream(name: str) -> bool:
    return isinstance(name, str) and bool(_NAME.match(name))


def validate_stream(name: str) -> str:
    if not is_valid_stream(name):
        raise ValueError(
            f"invalid stream name {name!r}: must match [a-z0-9_.:-]{{1,{MAX_STREAM_NAME}}}"
        )
    return name


def prefix_of(name: str) -> str:
    """`task:abc` -> `task:`; `activity` -> `activity`. The first segment
    plus its colon when the stream is per-id."""
    head, sep, _ = name.partition(":")
    return head + sep if sep else head


def is_per_id(name: str) -> bool:
    return ":" in name


def escape(name: str) -> str:
    """A filesystem-safe form. `%` is outside the grammar, so `%3A` for
    `:` can never collide with a real name."""
    return validate_stream(name).replace(":", "%3A")


def unescape(filename: str) -> str:
    return filename.replace("%3A", ":")


__all__ = [
    "COMPACTION_STREAM", "KNOWN_PREFIXES", "MAX_STREAM_NAME", "escape", "is_per_id",
    "is_valid_stream", "prefix_of", "unescape", "validate_stream",
]
