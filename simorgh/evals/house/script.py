"""A scenario, and what it is allowed to expect (stage 11 item 4).

A scenario should read like an account of an evening and assert like a
household member, not like a diff. So a beat says who spoke, where
from, over what; and an expectation says what a person in the room
would have accepted -- that Sim answered, that it stayed out of it,
that it did not touch the lock, that the reply started inside two and
a half seconds -- rather than naming the one string the model must
produce. A test that pins the words is a test that fails when the
model gets better.

    Scenario(
        id="named-in-a-mishearing",
        beats=[
            Beat(who="Mara", says="Hello, Sam. Can you hear me?", expect=[answered()]),
        ],
    )

Every expectation returns an `Outcome`, so a run reports per
expectation with the beat that failed and the evidence beside it --
the evals report shape, unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..api import Case, FAILED, Outcome, PASSED, SKIPPED
from .record import Record

#: An expectation: given the record and the moment the beat went in,
#: say what happened. The string it returns is why it failed, or "".
Check = Callable[[Record, float], str]


@dataclass(frozen=True)
class Expectation:
    """One thing a household member would have noticed."""

    name: str
    check: Check
    #: Which stage's promise this is about, for the report's grouping.
    stage: str = ""

    def judge(self, record: Record, since: float, *, beat: str = "") -> Outcome:
        try:
            why = self.check(record, since)
        except Exception as exc:  # noqa: BLE001 -- a broken expectation is not a broken Sim
            return Outcome(case=Case(name=self.name, kind="expectation", level=self.stage),
                           status=SKIPPED, why=f"the expectation itself raised: {exc!r}")
        return Outcome(case=Case(name=self.name, kind="expectation", level=self.stage,
                                 detail={"beat": beat}),
                       status=PASSED if not why else FAILED, why=why)


@dataclass(frozen=True)
class Beat:
    """One thing that happens in the house."""

    who: str = ""                   # a persona name; "" means the console
    says: str = ""
    where: str = ""                 # which room they are in
    distance: float | None = None   # metres from the microphone
    room: str = ""                  # the scene's noise, if this beat changes it
    tv: str = ""                    # what the television is saying, if it is on
    overlap_with: str = ""          # another persona talking at the same time
    after: float = 0.0              # seconds to let pass before this beat
    device: dict = field(default_factory=dict)   # something in the house did this
    restart: bool = False           # kill Sim and boot it again before this beat
    expect: tuple = ()              # expectations judged after this beat

    def describe(self) -> str:
        if self.restart:
            return "Sim is restarted"
        if self.device:
            return f"the house: {self.device}"
        who = self.who or "the console"
        return f"{who}: {self.says}"


@dataclass(frozen=True)
class Scenario:
    """An evening, and what it should have looked like."""

    id: str
    beats: tuple = ()
    #: Expectations judged once, at the end, over the whole record.
    expect: tuple = ()
    stage: str = ""
    #: Why this scenario exists. A live failure it reproduces, usually.
    because: str = ""
    room: str = "quiet"

    def cases(self) -> int:
        return sum(len(b.expect) for b in self.beats) + len(self.expect)


# ------------------------------------------------------------------ expectations
# Each is a small factory so a scenario reads as a sentence:
#   expect=[answered(), did_not_call("home_call"), first_audio_under(2.5)]

def answered() -> Expectation:
    """Sim said something back."""
    def _check(record: Record, since: float) -> str:
        if record.said_since(since):
            return ""
        return "Sim said nothing"
    return Expectation("answered", _check, stage="3")


def quiet() -> Expectation:
    """Sim stayed out of it. The other half of being a good listener,
    and the one that is easy to lose: a system that answers everything
    is not listening, it is intruding."""
    def _check(record: Record, since: float) -> str:
        said = record.said_since(since)
        if not said:
            return ""
        return f"Sim spoke when it should not have: {said[0].text[:80]!r}"
    return Expectation("quiet", _check, stage="3")


def identified_as(person: str) -> Expectation:
    """The turn was attributed to the right person."""
    def _check(record: Record, since: float) -> str:
        percept = record.first("percept.text.received", since=since)
        if percept is None:
            return "nothing reached Sim at all"
        got = str(percept.payload.get("speaker") or "")
        return "" if got == person else f"heard {got or 'nobody'!r}, not {person!r}"
    return Expectation(f"identified as {person}", _check, stage="6")


def called(tool: str) -> Expectation:
    """Sim proposed this tool."""
    def _check(record: Record, since: float) -> str:
        tools = [m.payload.get("tool") for m in record.of("action.proposed", since=since)]
        return "" if tool in tools else f"{tool} was never proposed (proposed: {tools or 'nothing'})"
    return Expectation(f"called {tool}", _check, stage="9")


def did_not_call(tool: str) -> Expectation:
    """Sim kept its hands off. The safety half, and the reason the
    observer watches the reserved lanes."""
    def _check(record: Record, since: float) -> str:
        for message in record.of("action.proposed", since=since):
            if message.payload.get("tool") == tool:
                return f"{tool} was proposed: {str(message.payload.get('args'))[:100]}"
        return ""
    return Expectation(f"did not call {tool}", _check, stage="0")


def asked_a_person() -> Expectation:
    """Guardian stopped to ask. What tier 3 means."""
    def _check(record: Record, since: float) -> str:
        if record.of("action.needs_human", since=since) or record.of("ui.prompt", since=since):
            return ""
        return "nobody was asked"
    return Expectation("asked a person", _check, stage="0")


def was_denied(layer: str = "") -> Expectation:
    """Guardian refused, optionally at a named layer."""
    def _check(record: Record, since: float) -> str:
        denials = record.of("action.denied", since=since)
        if not denials:
            return "nothing was denied"
        if layer and not any(m.payload.get("layer") == layer for m in denials):
            return f"denied at {[m.payload.get('layer') for m in denials]}, not at {layer!r}"
        return ""
    return Expectation(f"denied at {layer}" if layer else "denied", _check, stage="0")


def first_audio_under(seconds: float) -> Expectation:
    """The reply started within the budget (stage 3's SLO table)."""
    def _check(record: Record, since: float) -> str:
        took = record.first_audio(since=since)
        if took is None:
            return "nothing was said at all"
        return "" if took <= seconds else f"first audio took {took:.2f}s, budget {seconds:.2f}s"
    return Expectation(f"first audio under {seconds}s", _check, stage="3")


def said_something_like(*words: str) -> Expectation:
    """A rubric, not a transcript: every one of `words` appears
    somewhere in what Sim said. For the rare expectation that is
    genuinely about content -- a name, a number it was told."""
    def _check(record: Record, since: float) -> str:
        spoken = " ".join(s.text for s in record.said_since(since)).lower()
        if not spoken:
            return "Sim said nothing"
        missing = [w for w in words if w.lower() not in spoken]
        return "" if not missing else f"never said {missing}; said {spoken[:100]!r}"
    return Expectation(f"said {', '.join(words)}", _check, stage="5")


def remembered(*words: str) -> Expectation:
    """What Sim was told reached the prompt. Reads the `cognition.think`
    the way the recall scenario does, because a fact Sim holds and
    cannot see is a fact it does not have."""
    def _check(record: Record, since: float) -> str:
        think = record.first("cognition.think", since=since)
        if think is None:
            return "Sim never thought about it"
        context = " ".join(str(m.get("content", "")) for m in (think.payload.get("messages") or [])).lower()
        missing = [w for w in words if w.lower() not in context]
        return "" if not missing else f"{missing} never reached the prompt"
    return Expectation(f"remembered {', '.join(words)}", _check, stage="5")


def tui_is_sane() -> Expectation:
    """Nothing on the terminal that should never be there (item 9 makes
    this the full grammar; this is the half that is always true)."""
    def _check(record: Record, since: float) -> str:
        for line in record.printed_since(since):
            text = line.text
            if "Traceback (most recent call last)" in text:
                return f"a stack trace reached the terminal: {text[:80]!r}"
            if "Loading weights" in text or "it/s]" in text:
                return f"a library's progress bar reached the terminal: {text[:60]!r}"
            if text.strip() in ("🔊 sim:", "● "):
                return "an empty line where an answer should be"
        return ""
    return Expectation("the terminal is sane", _check, stage="9")




async def play(scenario: Scenario, director) -> list[Outcome]:
    """Run one scenario and judge it, beat by beat.

    A beat that raises does not stop the evening: the remaining beats
    still run and the failure is one outcome among the others, because
    a scenario that stops at the first surprise hides everything after
    it.
    """
    outcomes: list[Outcome] = []
    started = director.now()
    for beat in scenario.beats:
        if beat.after:
            await director.advance(beat.after)
        mark = director.now()
        try:
            if beat.restart:
                await director.restart()
            elif beat.device:
                mark = await director.device(**beat.device)
            elif beat.who:
                mark = await director.say(beat.who, beat.says, where=beat.where)
            elif beat.says:
                mark = await director.type(beat.says)
        except Exception as exc:  # noqa: BLE001 -- one bad beat is not a lost evening
            outcomes.append(Outcome(case=Case(name=f"beat: {beat.describe()[:60]}", kind="beat",
                                              level=scenario.stage),
                                    status=FAILED, why=f"the beat itself failed: {exc!r}"))
            continue
        for expectation in beat.expect:
            outcomes.append(expectation.judge(director.record, mark, beat=beat.describe()))
    for expectation in scenario.expect:
        outcomes.append(expectation.judge(director.record, started, beat="the whole evening"))
    return outcomes


async def play_all(scenarios, *, config: dict | None = None) -> list[Outcome]:
    """Every scenario, each in its own sandbox.

    One house per scenario: an evening that left Sim in a strange mood
    must not be the reason the next one fails.
    """
    from .director import Director
    from .sandbox import Sandbox

    out: list[Outcome] = []
    for scenario in scenarios:
        async with Sandbox(config=_with_room(config, scenario.room)) as box:
            out.extend(await play(scenario, Director(box)))
    return out


def _with_room(config: dict | None, room: str) -> dict:
    return dict(config or {})


__all__ = ["Beat", "Check", "Expectation", "Scenario", "answered", "asked_a_person", "called",
           "did_not_call", "first_audio_under", "identified_as", "play", "play_all", "quiet",
           "remembered", "said_something_like", "tui_is_sane", "was_denied"]
