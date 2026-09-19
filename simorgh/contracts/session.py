"""Sessions as typed transcripts (stage 4 item 1).

Every kind of session -- a chat, a spoken conversation, a task, a project,
a sub-agent -- is a `Session` whose history is a list of `Turn`s, each made
of `Block`s: text, a tool use, a tool result, an image reference. The
history is the ledger stream `session:<id>`, one event per turn
(`session.turn.appended`), with `session.compacted` when old turns are
folded into a summary and `session.snapshot` every so often so a reader
does not replay from the start.

Pure shapes: `to_dict`/`from_dict` round-trip, `validate_*` return the
problems. Nothing here reads or writes a stream (stage 4 item 2 does).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Union

STREAM_PREFIX = "session:"
TURN_APPENDED = "session.turn.appended"
COMPACTED = "session.compacted"
SNAPSHOT = "session.snapshot"
STREAM_EVENTS = (TURN_APPENDED, COMPACTED, SNAPSHOT)

ROLES = ("system", "user", "assistant", "tool")
STATES = ("open", "waiting", "closed")


def stream_name(session_id: str) -> str:
    return f"{STREAM_PREFIX}{session_id}"


@dataclass(frozen=True)
class Budget:
    turns: int = 0          # 0: no limit
    tokens: int = 0
    usd: float = 0.0
    wall_s: float = 0.0


@dataclass(frozen=True)
class Session:
    id: str
    agent: str                      # the agent definition it runs (chat, patch, research, ...)
    channel: str = ""               # cli | voice | telegram | ... ; "" for a task
    person_id: str = ""
    parent_id: str = ""             # the session that started it (a sub-agent)
    depth: int = 0
    budget: Budget = field(default_factory=Budget)
    state: str = "open"


@dataclass(frozen=True)
class Text:
    text: str
    kind: str = "text"


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict = field(default_factory=dict)
    kind: str = "tool_use"


@dataclass(frozen=True)
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False
    ref: str = ""                   # a blob holding the whole result, when `content` is a stub
    bytes_total: int = 0
    kind: str = "tool_result"


@dataclass(frozen=True)
class Image:
    ref: str
    kind: str = "image"


Block = Union[Text, ToolUse, ToolResult, Image]
_BLOCKS = {"text": Text, "tool_use": ToolUse, "tool_result": ToolResult, "image": Image}


@dataclass(frozen=True)
class Turn:
    seq: int
    role: str
    blocks: tuple = ()
    ts: float = 0.0
    meta: dict = field(default_factory=dict)   # provider, model, in/out tokens, cached_input_tokens, cost

    def text(self) -> str:
        return "".join(b.text for b in self.blocks if isinstance(b, Text))


def block_from_dict(data: dict) -> Block:
    cls = _BLOCKS.get(str(data.get("kind") or ""))
    if cls is None:
        raise ValueError(f"unknown block kind {data.get('kind')!r}")
    fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
    return cls(**fields)


def turn_to_dict(turn: Turn) -> dict:
    return {"seq": turn.seq, "role": turn.role, "ts": turn.ts, "meta": dict(turn.meta),
            "blocks": [asdict(b) for b in turn.blocks]}


def turn_from_dict(data: dict) -> Turn:
    return Turn(seq=int(data["seq"]), role=str(data["role"]), ts=float(data.get("ts") or 0.0),
                meta=dict(data.get("meta") or {}),
                blocks=tuple(block_from_dict(b) for b in data.get("blocks") or ()))


def session_to_dict(session: Session) -> dict:
    return asdict(session)


def session_from_dict(data: dict) -> Session:
    budget = Budget(**{k: v for k, v in (data.get("budget") or {}).items() if k in Budget.__dataclass_fields__})
    fields = {k: v for k, v in data.items() if k in Session.__dataclass_fields__ and k != "budget"}
    return Session(budget=budget, **fields)


def validate_turn(turn: Turn) -> list[str]:
    problems = []
    if turn.seq < 0:
        problems.append("seq must be >= 0")
    if turn.role not in ROLES:
        problems.append(f"role {turn.role!r} is not one of {ROLES}")
    for block in turn.blocks:
        if not isinstance(block, (Text, ToolUse, ToolResult, Image)):
            problems.append(f"not a block: {block!r}")
        elif isinstance(block, ToolUse) and (not block.id or not block.name):
            problems.append("a tool use needs an id and a name")
        elif isinstance(block, ToolResult) and not block.tool_use_id:
            problems.append("a tool result needs the id of its tool use")
    if turn.role == "tool" and not all(isinstance(b, ToolResult) for b in turn.blocks):
        problems.append("a tool turn holds only tool results")
    if turn.role != "assistant" and any(isinstance(b, ToolUse) for b in turn.blocks):
        problems.append("only an assistant turn uses tools")
    return problems


def validate_session(session: Session) -> list[str]:
    problems = []
    if not session.id or not session.agent:
        problems.append("a session needs an id and an agent")
    if session.state not in STATES:
        problems.append(f"state {session.state!r} is not one of {STATES}")
    if session.depth < 0 or (session.depth > 0 and not session.parent_id):
        problems.append("a session below the top needs its parent")
    return problems


def validate_pairs(turns: list[Turn]) -> list[str]:
    """Every tool result answers a tool use made earlier in the transcript."""
    used: set[str] = set()
    problems = []
    for turn in turns:
        for block in turn.blocks:
            if isinstance(block, ToolUse):
                used.add(block.id)
            elif isinstance(block, ToolResult) and block.tool_use_id not in used:
                problems.append(f"turn {turn.seq}: result for unknown tool use {block.tool_use_id!r}")
    return problems


__all__ = [
    "Block", "Budget", "COMPACTED", "Image", "ROLES", "SNAPSHOT", "STATES", "STREAM_EVENTS", "STREAM_PREFIX",
    "Session", "TURN_APPENDED", "Text", "ToolResult", "ToolUse", "Turn", "block_from_dict", "session_from_dict",
    "session_to_dict", "stream_name", "turn_from_dict", "turn_to_dict", "validate_pairs", "validate_session",
    "validate_turn",
]
