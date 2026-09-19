"""A session's messages as its typed transcript on the ledger (stage 4 item 2).

`session.messages` -- what the model is shown each step -- is written to
`session:<id>` as one `session.turn.appended` event per message, so a
session that dies mid-task resumes with its context and not only its step
count (evaluation L5). When the messages are replaced wholesale (a progress
note re-grounds the session, or old tool results are folded), the new list
is written as one `session.compacted` event; a `session.snapshot` every
`SNAPSHOT_EVERY` turns means a reader never replays from the start.
"""

from __future__ import annotations

from simorgh.contracts import session as s
from simorgh.contracts.envelope import Event

SNAPSHOT_EVERY = 50


def to_turn(message: dict, seq: int, ts: float = 0.0) -> s.Turn:
    role = str(message.get("role") or "user")
    content = str(message.get("content") or "")
    if role == "tool":
        blocks = (s.ToolResult(str(message.get("tool_call_id") or ""), content),)
    else:
        blocks = (s.Text(content),) if content else ()
        for call in message.get("tool_calls") or ():
            blocks += (s.ToolUse(str(call.get("id") or ""), str(call.get("tool") or ""), dict(call.get("args") or {})),)
    meta = {"name": message["name"]} if message.get("name") else {}
    return s.Turn(seq=seq, role=role if role in s.ROLES else "user", blocks=blocks, ts=ts, meta=meta)


def to_message(turn: s.Turn) -> dict:
    if turn.role == "tool":
        result = next((b for b in turn.blocks if isinstance(b, s.ToolResult)), None)
        message = {"role": "tool", "tool_call_id": result.tool_use_id if result else "",
                   "content": result.content if result else ""}
    else:
        message = {"role": turn.role, "content": turn.text()}
        uses = [b for b in turn.blocks if isinstance(b, s.ToolUse)]
        if uses:
            message["tool_calls"] = [{"id": u.id, "tool": u.name, "args": dict(u.input)} for u in uses]
    if turn.meta.get("name"):
        message["name"] = turn.meta["name"]
    return message


class TranscriptWriter:
    """Writes what is new in `session.messages` since the last call."""

    def __init__(self, ledger, clock=None) -> None:
        self._ledger = ledger
        self._clock = clock
        self._state: dict[str, tuple[int, int, int]] = {}   # session id -> (list id, messages written, next seq)

    def _now(self) -> float:
        if self._clock is None:
            return 0.0
        return float(self._clock() if callable(self._clock) else self._clock.now())

    async def _event(self, stream: str, type_: str, payload: dict) -> None:
        await self._ledger.append(stream, Event(stream=stream, type=type_, ts=self._now(), trace_id=stream,
                                                causation_id=None, payload=payload))

    async def persist(self, session_id: str, messages: list[dict]) -> None:
        if self._ledger is None or not session_id:
            return
        stream = s.stream_name(session_id)
        list_id, written, seq = self._state.get(session_id, (id(messages), 0, 0))
        if id(messages) != list_id or len(messages) < written:
            # Replaced wholesale: the new transcript is the state from here.
            turns = [to_turn(m, seq + i, self._now()) for i, m in enumerate(messages)]
            await self._event(stream, s.COMPACTED, {"turns": [s.turn_to_dict(t) for t in turns],
                                                    "dropped_seq_range": [0, max(0, seq - 1)]})
            self._state[session_id] = (id(messages), len(messages), seq + len(messages))
            return
        for message in messages[written:]:
            turn = to_turn(message, seq, self._now())
            await self._event(stream, s.TURN_APPENDED, s.turn_to_dict(turn))
            seq += 1
            if seq % SNAPSHOT_EVERY == 0:
                await self._event(stream, s.SNAPSHOT, {"turns": [s.turn_to_dict(to_turn(m, i)) for i, m in
                                                                 enumerate(messages[:written + 1])]})
            written += 1
        self._state[session_id] = (id(messages), written, seq)

    def forget(self, session_id: str) -> None:
        self._state.pop(session_id, None)


def fold(events) -> list[dict]:
    """The messages a session stream describes: the last snapshot or
    compaction, then every turn appended after it."""
    messages: list[dict] = []
    for event in events:
        if event.type in (s.SNAPSHOT, s.COMPACTED):
            messages = [to_message(s.turn_from_dict(t)) for t in event.payload.get("turns") or ()]
        elif event.type == s.TURN_APPENDED:
            messages.append(to_message(s.turn_from_dict(event.payload)))
    return messages


__all__ = ["SNAPSHOT_EVERY", "TranscriptWriter", "fold", "to_message", "to_turn"]
