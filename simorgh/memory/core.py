"""Core memory blocks (stage 15 item 8, after Letta's core tier).

Everything else Memory holds is *recalled*: a turn gets what its words
happen to match, the speaker's digest, and the recent window. A core block
is the opposite -- a few small, labelled notes that are always in front of
the model and that the model itself keeps current, the way Letta keeps a
`human` and a `persona` block in every prompt. "About Soodeh: prefers
Farsi, tea not coffee, works Tuesdays" is the shape: what is worth knowing
before anything is asked.

There is one block per person (`person:<slug>`) and one `household` block,
each at most `[memory] core_block_chars`. They live on `memory:core` as
`core.edited` events, each carrying the whole new text and the text it
replaced, so an edit is undone by another edit and nothing is ever
rewritten. `CoreIndex` is the fold of that stream, as `FactIndex` is of
`memory:facts`.

An edit is Letta's `core_memory_replace`: `old` must be in the block and
is replaced by `new` -- `old` empty appends `new` as a line of its own,
`new` empty removes `old`. A person may edit only their own block and
`household`; who is asking comes from Guardian's record of the proposal,
never from the model's arguments (execution/tools.py
`MemoryCoreEditTool`), and is checked again here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Which block an edit names, and who is unplaced, are shared with
# Guardian's rule and the tool (`contracts/coreblocks.py`); re-exported
# here under the names this module always had.
from simorgh.contracts.coreblocks import HOUSEHOLD, UNPLACED, block_for, is_outside, is_unplaced, person_block

#: One event per edit, on `memory:core` (a `memory:` stream, so it needs no
#: entry of its own in `contracts/streamnames.py`).
CORE_STREAM = "memory:core"
EDITED = "core.edited"


def owner_name(people) -> str:
    """The owner's name in the People registry: whose a typed console turn
    is (Guardian treats an absent requester as the console, the owner's)."""
    for person in people or ():
        if getattr(person, "role", "") == "owner":
            return str(getattr(person, "name", "") or "")
    return ""


def requester_name(requester: str, people, *, channel: str = "") -> str:
    """The person a turn belongs to: the named speaker, the owner for the
    console (no requester on `""`/`cli`), "" for an unplaced voice, for
    nobody named anywhere else (Sim's own idea, a plan node), and for an
    outside channel (`a2a`), whoever it names."""
    from simorgh.contracts.channels import is_console

    if is_outside(channel):
        return ""
    name = " ".join((requester or "").split())
    if not name:
        return owner_name(people) if is_console(channel) else ""
    if is_unplaced(name):
        return ""
    return name


def apply_edit(text: str, old: str, new: str, *, limit: int) -> tuple[str, str]:
    """`(the block after, why not)`: replace `old` with `new` in `text`.

    `old` must occur exactly once: twice is ambiguous, and Letta's
    replace-all would change a line the model did not mean. `old` empty
    appends `new` on its own line; `new` empty removes `old`. The result
    must fit in `limit` characters; a block that would not is refused
    whole, never cut."""
    old = old or ""
    new = (new or "").strip()
    if not old.strip() and not new:
        return text, "nothing to change: give `old` to replace or remove, `new` to add"
    if not old.strip():
        after = f"{text.rstrip()}\n{new}" if text.strip() else new
    else:
        count = text.count(old)
        if not count:
            return text, f"{old!r} is not in the block; copy the words exactly as the block has them"
        if count > 1:
            return text, f"{old!r} is in the block {count} times; give more of the line"
        after = text.replace(old, new)
        # A removed line leaves no blank line behind.
        after = "\n".join(line for line in after.splitlines() if line.strip()).strip()
    if len(after) > limit:
        return text, (f"the block would be {len(after)} characters and the limit is {limit}: "
                      "shorten or replace a line rather than adding one")
    if after == text:
        return text, "the block already says that"
    return after, ""


@dataclass
class CoreIndex:
    """Every block's current text, from `memory:core`."""

    blocks: dict[str, str] = field(default_factory=dict)
    #: Per block, the source turn and the editor of its latest edit.
    last: dict[str, dict] = field(default_factory=dict)
    cursor: int = 0

    def apply(self, event) -> None:
        if event.type != EDITED:
            return
        payload = event.payload or {}
        block = str(payload.get("block") or "")
        if not block:
            return
        self.blocks[block] = str(payload.get("text") or "")
        self.last[block] = {"by": str(payload.get("by") or ""), "source_ref": str(payload.get("source_ref") or "")}

    def text(self, block: str) -> str:
        return self.blocks.get(block, "")


__all__ = ["CORE_STREAM", "EDITED", "HOUSEHOLD", "UNPLACED", "CoreIndex", "apply_edit", "block_for", "owner_name",
           "person_block", "requester_name"]
