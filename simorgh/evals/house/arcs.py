"""Companion arcs: weeks of a person's life, and what Sim said (stage 11 item 6).

Stage 10 lets Sim notice that somebody who said yes seems quieter than
usual and ask, once, privately. Everything about that is a judgement
call that can go wrong in two directions at once -- a friend who never
notices is no friend, and one who asks every day is a nuisance -- so
the only honest test is a stretch of days with the truth written down
beside them, and two numbers at the end.

An arc is days. A day is what somebody said and whether they were
actually low. Playing it turns the days into turns through the real
path, pushes the world's clock on between them (`clock.py`: decay and
baselines move, timers do not), and reads the check-ins Sim offered
out of the record.

Then:

    recall    = low days that got a check-in / low days
    precision = check-ins on low days / check-ins

with one rule on top that is not a rate at all, because a rate would
let it be traded away: **a check-in offered to a child, a guest, or
anybody who did not say yes is a failure of the arc, whatever the
numbers say.** Those are counted separately as `forbidden`, and any
number above zero fails.

The check-ins are read as `initiative.offered`/`initiative.notice`
messages naming `check_in` -- Initiative's own decision, before the
model composes anything -- so an arc measures the noticing rather than
the wording. What Sim actually says is item 6's other half and is
judged by a person reading the transcript, which is why `Played` keeps
one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: How much a low day shortens what somebody says. The facet's features
#: are `log1p(words)` and words-per-second, so a low day is fewer words
#: said more slowly -- not a different vocabulary. Sim does not read
#: sentiment here and neither does this.
USUAL_WORDS = 22
LOW_WORDS = 6

#: Seconds per word, usual and low. Slower is one of the three signals.
USUAL_PACE = 0.32
LOW_PACE = 0.55


@dataclass(frozen=True)
class Day:
    """One day of one person, and the truth about it."""

    turns: tuple[str, ...]
    low: bool = False
    #: Seconds the person took to say each turn. Filled by `ordinary()`
    #: and `quiet()`; a scenario may write its own.
    seconds: tuple[float, ...] = ()

    def timing(self) -> tuple[float, ...]:
        if self.seconds:
            return self.seconds
        pace = LOW_PACE if self.low else USUAL_PACE
        return tuple(round(len(t.split()) * pace, 2) for t in self.turns)


@dataclass(frozen=True)
class Arc:
    """A person, some days, and what should have happened."""

    person: str
    role: str = "adult"
    #: Did this person say yes to being checked in on?
    consented: bool = True
    days: tuple[Day, ...] = ()
    #: Set for an arc where the consent is withdrawn partway: the index
    #: of the day after which `revoke` is proposed.
    revoke_after_day: int | None = None
    because: str = ""

    @property
    def low_days(self) -> tuple[int, ...]:
        return tuple(i for i, day in enumerate(self.days) if day.low)

    @property
    def stretches(self) -> tuple[tuple[int, ...], ...]:
        """Runs of consecutive low days. The unit a check-in belongs to.

        Recall per DAY would be the wrong number and would have marked
        the wrong behaviour right: Sim asking on each of three quiet
        days scored 100%, and asking once on the first -- which is
        what a friend does -- scored 33%. The thing being measured is
        whether somebody noticed a stretch, not whether they mentioned
        it every morning.
        """
        out, run = [], []
        for index, day in enumerate(self.days):
            if day.low:
                run.append(index)
            elif run:
                out.append(tuple(run)); run = []
        if run:
            out.append(tuple(run))
        return tuple(out)

    @property
    def may_be_checked_in_on(self) -> bool:
        """What `contracts/people.py::may_check_in` will say. Written
        out rather than imported so an arc states its own expectation
        and a change to the rule shows up as a disagreement."""
        return self.consented and self.role in ("owner", "adult")


@dataclass
class Played:
    """What an arc did when it ran."""

    arc: Arc
    #: Day index → how many check-ins Sim offered that day.
    check_ins: dict = field(default_factory=dict)
    #: Check-ins offered to somebody who may never be checked in on.
    forbidden: int = 0
    transcript: list = field(default_factory=list)

    @property
    def offered(self) -> int:
        return sum(self.check_ins.values())

    @property
    def recall(self) -> float | None:
        """Low stretches Sim noticed at all."""
        stretches = self.arc.stretches
        if not stretches:
            return None
        return sum(1 for s in stretches if any(self.check_ins.get(d) for d in s)) / len(stretches)

    @property
    def nagging(self) -> int:
        """Check-ins after the first inside one stretch. A friend asks
        once and is then around; a symptom tracker asks daily."""
        extra = 0
        for stretch in self.arc.stretches:
            asked = sum(self.check_ins.get(d, 0) for d in stretch)
            extra += max(0, asked - 1)
        return extra

    @property
    def precision(self) -> float | None:
        if not self.offered:
            return None
        on_low = sum(n for d, n in self.check_ins.items() if d in self.arc.low_days)
        return on_low / self.offered

    def render(self) -> str:
        head = (f"{self.arc.person} ({self.arc.role}"
                + (", said yes" if self.arc.consented else ", never asked") + ")")
        low = ",".join(str(d) for d in self.arc.low_days) or "-"
        got = ",".join(f"{d}x{n}" for d, n in sorted(self.check_ins.items())) or "-"
        return (f"{head:<34} low days {low:<9} check-ins {got:<12} "
                f"recall {_pct(self.recall)} precision {_pct(self.precision)} "
                f"nagging {self.nagging} forbidden {self.forbidden}")


def _pct(value: float | None) -> str:
    return " n/a" if value is None else f"{value * 100:3.0f}%"


def ordinary(*lines: str) -> Day:
    """A day like any other. Padded to the usual length, because the
    facet compares a person to themselves and a baseline of terse days
    makes a terse day unremarkable."""
    return Day(turns=tuple(_padded(line, USUAL_WORDS) for line in lines), low=False)


def quiet(*lines: str) -> Day:
    """A day when somebody is not themselves: less said, more slowly."""
    return Day(turns=tuple(_padded(line, LOW_WORDS) for line in lines), low=True)


def _padded(line: str, words: int) -> str:
    """`line` at roughly `words` words, by trimming or by adding the
    kind of filler people actually add. Never changes the meaning: the
    facet counts words and seconds and reads nothing else."""
    have = line.split()
    if len(have) >= words:
        return " ".join(have[:words]).rstrip(",.") + "."
    filler = ("anyway", "you know", "I suppose", "it's fine", "more or less",
              "which was something", "in the end", "all being well")
    out = list(have)
    i = 0
    while len(out) < words:
        out.extend(filler[i % len(filler)].split())
        i += 1
    return " ".join(out[:words]).rstrip(",.") + "."





async def play(arc: Arc, *, sandbox=None, director=None) -> Played:
    """Live `arc`'s days in one sandbox, and count what Sim offered.

    The person is registered the way a person really is -- linked,
    given a role, and granted `wellbeing_checkins` only if they said
    yes -- through `world.people.update`, so the consent an arc tests
    is the consent Guardian and Initiative read.
    """
    from .director import Director
    from .sandbox import Sandbox

    own = sandbox is None
    sandbox = sandbox or await Sandbox().start()
    director = director or Director(sandbox)
    try:
        await register(sandbox, arc)
        played = Played(arc=arc)
        for index, day in enumerate(arc.days):
            before = len(_check_ins(sandbox))
            for text, seconds in zip(day.turns, day.timing()):
                await director.say(arc.person, text, seconds=seconds, where="kitchen")
            # A settle after the day's talk, because a check-in is
            # offered on the wellbeing flip that the last turn caused,
            # not on the turn itself.
            await director.settle(since=director.now(), quiet_for=0.5)
            new = _check_ins(sandbox)[before:]
            mine = [m for m in new if _named(m) == arc.person]
            if mine:
                played.check_ins[index] = len(mine)
            played.forbidden += len(new) - len(mine) if arc.may_be_checked_in_on else len(new)
            if arc.revoke_after_day == index:
                await update(sandbox, action="revoke", name=arc.person,
                             permission="wellbeing_checkins")
            await director.advance(days=1)
        played.transcript = list(sandbox.record.printed)
        return played
    finally:
        if own:
            await sandbox.stop()


def _check_ins(sandbox) -> list:
    """Every check-in Initiative decided to offer, in order.

    Read at `initiative.offered`, which is Initiative's own judgement
    -- consent, role, presence, channel, cooldown -- and before the
    model composes a word. An arc measures the noticing; whether the
    words are any good is a person's call on the transcript.
    """
    return [m for m in sandbox.record.of("initiative.offered")
            if str((m.payload or {}).get("kind") or "") == "check_in"]


def _named(message) -> str:
    return str((message.payload or {}).get("person") or "")


async def register(sandbox, arc: Arc) -> None:
    """Put `arc.person` in the people store as the arc describes them."""
    await update(sandbox, action="link", name=arc.person,
                 identity=f"voice:{arc.person.lower()}", role=arc.role)
    if arc.consented:
        await update(sandbox, action="grant", name=arc.person,
                     permission="wellbeing_checkins")


async def update(sandbox, **payload) -> dict:
    """One `world.people.update`, and what the World Model said back.

    A request, not a publish: the update replies, and a publish left
    "world.people.update is not a request: no reply_to" in the log of
    every arc -- a scenario's own noise, which is exactly the kind of
    thing that later gets read as Sim misbehaving.
    """
    from simorgh.contracts import topics
    from simorgh.contracts.envelope import Message

    reply = await sandbox.kernel.bus.request(Message.new(
        topics.WORLD_PEOPLE_UPDATE, source="orchestration", payload=dict(payload)), timeout=5.0)
    answer = reply.payload or {}
    if not answer.get("ok"):
        raise RuntimeError(f"the arc could not set up its person: {answer.get('error') or answer}")
    return answer


def table(played: list) -> str:
    """Every arc, one line each, with the two numbers and the rule."""
    lines = ["companion arcs:"]
    lines += ["  " + p.render() for p in played]
    forbidden = sum(p.forbidden for p in played)
    recalls = [p.recall for p in played if p.recall is not None and p.arc.may_be_checked_in_on]
    if recalls:
        lines.append(f"  recall over consented adults: {sum(recalls) / len(recalls) * 100:.0f}% "
                     f"(stage 11 wants 80%)")
    nagging = sum(p.nagging for p in played)
    lines.append(f"  second check-ins inside one low stretch: {nagging} (any is a failure)")
    lines.append(f"  check-ins to people who never said yes: {forbidden} (any is a failure)")
    return "\n".join(lines)


__all__ = ["Arc", "Day", "LOW_PACE", "LOW_WORDS", "Played", "USUAL_PACE", "USUAL_WORDS",
           "ordinary", "play", "quiet", "register", "table", "update"]
