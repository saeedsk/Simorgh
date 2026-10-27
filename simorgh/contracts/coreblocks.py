"""Whose core memory block is whose (stage 15 item 8).

A core block is one of the short notes Memory keeps in front of the model
on every chat turn: one per person (`person:<slug>`) and one `household`.
Three packages have to agree on which block an edit names and whether the
person asking may touch it -- Guardian's rule (`guardian/corememory.py`),
Execution's `memory_core_edit` tool and Memory's own check -- and none may
import another, so the naming lives here once. The decision itself stays
with each of them; this is only the vocabulary.
"""

from __future__ import annotations

import re

#: The tool that edits a block (execution/tools.py `MemoryCoreEditTool`).
CORE_EDIT_TOOL = "memory_core_edit"
HOUSEHOLD = "household"
#: What an edit may call the household block.
HOUSEHOLD_NAMES = frozenset({HOUSEHOLD, "house", "family", "home"})

#: Speakers whose block there is none of: a voice nobody matched is not a
#: person to keep notes about, nor one who may edit the household's.
UNPLACED = frozenset({"unknown", "unknown speaker", "stranger", "guest"})

#: Channels a block is never edited from: an outside agent (the A2A
#: server, interface/a2a.py) acts for a device's person, but what Sim
#: keeps in front of itself about the household is not theirs to write.
OUTSIDE_CHANNELS = frozenset({"a2a"})

_SLUG = re.compile(r"[^a-z0-9؀-ۿ]+")
#: What the model may write for "my own block".
_MINE = frozenset({"me", "mine", "my", "self", "own", "person"})


def _flat(text: str) -> str:
    return " ".join((text or "").casefold().split())


def person_block(name: str) -> str:
    """`Soodeh` -> `person:soodeh`; "" for no name."""
    slug = _SLUG.sub("-", _flat(name)).strip("-")
    return f"person:{slug}" if slug else ""


def is_household(asked: str) -> bool:
    """Does an edit's `block` name the household's?"""
    return _flat(asked) in HOUSEHOLD_NAMES


def is_unplaced(requester: str) -> bool:
    """A requester named as a voice nobody matched ("unknown", "guest")."""
    return _flat(requester) in UNPLACED


def is_outside(channel: str) -> bool:
    return _flat(channel) in OUTSIDE_CHANNELS


def block_for(asked: str, requester: str) -> str:
    """The block id an edit names: `household`, the requester's own (by
    their name or `me`), or "" for anything else -- somebody else's block
    included."""
    flat = _flat(asked)
    if flat in HOUSEHOLD_NAMES:
        return HOUSEHOLD
    own = person_block(requester)
    if not own:
        return ""
    if flat in _MINE or flat == own or person_block(flat) == own:
        return own
    return ""


__all__ = ["CORE_EDIT_TOOL", "HOUSEHOLD", "HOUSEHOLD_NAMES", "OUTSIDE_CHANNELS", "UNPLACED", "block_for",
           "is_household", "is_outside", "is_unplaced", "person_block"]
