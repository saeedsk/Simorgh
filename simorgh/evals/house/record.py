"""What a scenario run leaves behind (stage 11 item 1).

One object, written by the sandbox while Sim runs and read by the
expectations afterwards. It is deliberately dumb: every message in the
order the bus delivered it, every line the Interface printed, every
piece the synthesiser was asked to say and when, and the spans. No
judgement is made here -- an expectation reads this and decides, and
the failure message it prints has to be able to quote the evidence.

Wall-clock times are `time.monotonic()` at the moment the thing
happened, so latency comes out of the record rather than out of an
instrument the simulator holds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Said:
    """One piece the synthesiser was asked for: what, when, how fast."""

    text: str
    at: float
    voice: str = ""
    speed: float = 1.0


@dataclass(frozen=True)
class Printed:
    """One line the Interface put on the terminal."""

    text: str
    at: float


@dataclass(frozen=True)
class Seen:
    """One message off the bus."""

    type: str
    payload: dict
    at: float
    source: str = ""


@dataclass
class Record:
    """Everything that happened, in order."""

    messages: list[Seen] = field(default_factory=list)
    printed: list[Printed] = field(default_factory=list)
    said: list[Said] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)

    # -- writing (the sandbox's side) -------------------------------------------
    def saw(self, message) -> None:
        self.messages.append(Seen(type=message.type, payload=dict(message.payload or {}),
                                  at=time.monotonic(), source=str(getattr(message, "source", "") or "")))

    def printed_line(self, text: str) -> None:
        self.printed.append(Printed(text=str(text), at=time.monotonic()))

    def spoke(self, text: str, *, voice: str = "", speed: float = 1.0) -> None:
        self.said.append(Said(text=str(text), at=time.monotonic(), voice=voice, speed=speed))

    # -- reading (an expectation's side) ----------------------------------------
    def of(self, type_: str, *, since: float = 0.0) -> list[Seen]:
        return [m for m in self.messages if m.type == type_ and m.at >= since]

    def first(self, type_: str, *, since: float = 0.0) -> Seen | None:
        found = self.of(type_, since=since)
        return found[0] if found else None

    def said_since(self, since: float) -> list[Said]:
        return [s for s in self.said if s.at >= since]

    def printed_since(self, since: float) -> list[Printed]:
        return [p for p in self.printed if p.at >= since]

    def transcript(self, *, since: float = 0.0) -> str:
        """The run as a person would read it: who said what, in order.

        This is what a rubric judges and what a failure quotes, so it
        carries the turns and the spoken lines and nothing else.
        """
        rows: list[tuple[float, str]] = []
        for message in self.messages:
            if message.at < since:
                continue
            if message.type.endswith("percept.text.received"):
                who = str(message.payload.get("speaker") or "someone")
                rows.append((message.at, f"{who}: {message.payload.get('text', '')}"))
        for piece in self.said:
            if piece.at >= since:
                rows.append((piece.at, f"sim: {piece.text}"))
        return "\n".join(text for _at, text in sorted(rows, key=lambda row: row[0]))

    def latency(self, *, since: float, until_type: str) -> float | None:
        """Seconds from `since` to the first `until_type` after it."""
        found = self.first(until_type, since=since)
        return (found.at - since) if found is not None else None

    def first_audio(self, *, since: float) -> float | None:
        """Seconds from `since` to the first piece Sim was asked to say.

        Not the same as sound leaving the speaker -- the synthesiser is
        a fake until the audio scene lands (item 3) -- so it measures
        everything up to synthesis and says so by its name.
        """
        pieces = self.said_since(since)
        return (pieces[0].at - since) if pieces else None


__all__ = ["Printed", "Record", "Said", "Seen"]
