"""Where a turn's seconds go (stage 11 item 8).

The creator's complaint on 2026-09-20 was twenty seconds of silence,
and the honest answer at the time was "part of it is my thinking step"
-- a guess, because nothing decomposed a turn. This does, from the
record the scenario already keeps: the moment the words went in, the
moment Sim thought, the moment the first piece of speech was asked
for, the moment the turn completed.

No instrument is added to Sim. Every number here is a difference
between two things already on the bus, which means the table cannot
drift away from what actually happened and costs nothing to collect.

The budgets are stage 3's own (`voice/session.py::STAGE_BUDGETS_S`),
so a breach here is a breach there and not a second opinion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: What each segment of a turn is allowed, in seconds. `think` and
#: `first_audio` are stage 3's table; `reply` is the whole turn, which
#: nothing had a number for -- 8 s is the point at which the creator
#: said a wait needs covering out loud.
BUDGETS_S: dict[str, float] = {"hear": 2.0, "think": 1.5, "first_audio": 2.5, "reply": 8.0}


@dataclass(frozen=True)
class Turn:
    """One turn, decomposed."""

    said: str
    #: Somebody started speaking -> Sim understood them. VAD, the
    #: recogniser and the speaker book, which is stage 3's 2 s STT
    #: budget and is invisible from the bus alone: a percept appears
    #: only once all three are done.
    hear: float | None = None
    think: float | None = None          # spoke -> Sim asked the model
    first_audio: float | None = None    # spoke -> first piece to synthesise
    reply: float | None = None          # spoke -> turn.completed
    in_the_room: bool = True

    def over(self) -> list[str]:
        return [name for name, budget in BUDGETS_S.items()
                if (value := getattr(self, name)) is not None and value > budget]


@dataclass
class Table:
    """Every turn of a run, and where the seconds went."""

    turns: list = field(default_factory=list)

    def add(self, turn: Turn) -> None:
        self.turns.append(turn)

    def percentile(self, segment: str, at: float = 0.5) -> float | None:
        values = sorted(v for t in self.turns if (v := getattr(t, segment)) is not None)
        if not values:
            return None
        return values[min(len(values) - 1, int(at * (len(values) - 1) + 0.5))]

    def breaches(self) -> dict:
        """How often each segment went over, worst first. The segment
        at the top is where an evening's work should go."""
        counts: dict[str, int] = {}
        for turn in self.turns:
            for name in turn.over():
                counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items(), key=lambda row: -row[1]))

    @property
    def worst_segment(self) -> str:
        breaches = self.breaches()
        return next(iter(breaches), "")

    def render(self) -> str:
        if not self.turns:
            return "no turns to time"
        lines = [f"{'segment':12} {'budget':>8} {'p50':>8} {'p95':>8} {'over':>6}  of {len(self.turns)} turns",
                 "-" * 58]
        counts = self.breaches()
        for name, budget in BUDGETS_S.items():
            p50, p95 = self.percentile(name, 0.5), self.percentile(name, 0.95)
            lines.append(f"{name:12} {budget:>7.1f}s "
                         f"{('-' if p50 is None else f'{p50:.2f}s'):>8} "
                         f"{('-' if p95 is None else f'{p95:.2f}s'):>8} "
                         f"{counts.get(name, 0):>6}")
        if self.worst_segment:
            lines.append(f"\nthe segment that most often breaks its budget: {self.worst_segment}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {"turns": len(self.turns), "breaches": self.breaches(),
                "worst_segment": self.worst_segment,
                "p50": {k: self.percentile(k, 0.5) for k in BUDGETS_S},
                "p95": {k: self.percentile(k, 0.95) for k in BUDGETS_S}}


def from_record(record) -> Table:
    """Decompose every turn in a record.

    A turn starts when a PERSON starts speaking, not when the percept
    appears -- the percept is already past VAD, the recogniser and the
    speaker book, and measuring from it hides the whole listening path.
    That is the moment somebody in the room starts waiting, which is
    the only clock that matters.
    """
    table = Table()
    beats = record.spoke
    for index, beat in enumerate(beats):
        until = beats[index + 1].at if index + 1 < len(beats) else None
        percept = record.first("percept.text.received", since=beat.at)
        heard = (percept.at - beat.at) if percept is not None and (until is None or percept.at <= until) else None
        table.add(Turn(
            said=beat.text[:60],
            hear=heard,
            think=_gap(record, "cognition.think", beat.at, until),
            first_audio=_first_said(record, beat.at, until),
            reply=_gap(record, "turn.completed", beat.at, until),
            in_the_room=beat.in_the_room,
        ))
    return table


def _gap(record, type_: str, since: float, until: float | None) -> float | None:
    found = record.first(type_, since=since)
    if found is None or (until is not None and found.at > until):
        return None
    return found.at - since


def _first_said(record, since: float, until: float | None) -> float | None:
    pieces = [s for s in record.said_since(since) if until is None or s.at <= until]
    return (pieces[0].at - since) if pieces else None


__all__ = ["BUDGETS_S", "Table", "Turn", "from_record"]
