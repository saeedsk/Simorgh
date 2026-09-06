"""One module per domain; importing this package registers every v1
message type with `registry`. Keep the import list in sync with
`topics.DOMAINS` (a test checks that every catalog type is defined)."""

from __future__ import annotations

from . import (  # noqa: F401 -- side effect: registration
    action,
    cognition,
    curiosity,
    guardian,
    intent,
    learn,
    memory,
    percept,
    persona,
    plan,
    reflect,
    research,
    self_,
    system,
    task,
    tool,
    ui,
    verify,
    world,
)
