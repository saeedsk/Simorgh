"""The people who live in the simulated house (stage 11 item 2).

A persona is a name, a role, a voice, a way of speaking and a day.
Five of them, and deliberately not the creator's family: cloning a
household member's voice needs that person to say so, and the
simulator's job is to prove mechanics rather than to imitate anybody.
A real voice enters only as a recording somebody made for the purpose.

The voices are Kokoro's, which means they can be *enrolled* -- three
synthesised sentences through the same sherpa CAM++ embedder the house
uses, into the sandbox's own speaker book. So identification in a
scenario is tested with the same numbers a real voice gets, and a
persona Sim cannot place is a finding rather than a fixture problem.

Which Kokoro voices are usable is a measurement, not an opinion:
`enrol()` reports every persona's self-identification and the worst
cross-persona score, and `check()` says which pairs are too alike to
tell apart. Two voices that a real family would distinguish and the
embedder cannot are worth knowing about before a scenario blames Sim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Sentences a persona says to be enrolled. Ordinary household speech,
#: varied in length, because three takes of "testing one two three"
#: describe a way of counting rather than a voice.
ENROLMENT_LINES: tuple[str, ...] = (
    "Morning, I'm just putting the kettle on before anyone else is up.",
    "Has anyone seen the blue folder that was on the kitchen table yesterday?",
    "I'll be back around six, maybe a bit later if the traffic is bad again.",
)


@dataclass(frozen=True)
class Persona:
    """One person in the simulated house."""

    name: str
    role: str                       # owner | adult | child | guest
    voice: str                      # a Kokoro voice id
    #: Where they usually are, by hour of the day. The scene and the
    #: companion arcs read it; a scenario may override per beat.
    day: dict = field(default_factory=dict)
    interests: tuple[str, ...] = ()
    #: How they talk: a rough pace multiplier and the filler they use.
    pace: float = 1.0
    says_sim_as: str = "Sim"        # what whisper tends to write for them

    def addressing(self, text: str) -> str:
        """`text` with this persona's way of naming Sim in front."""
        return f"{self.says_sim_as}, {text}"


#: The stock household: two adults, two children, one guest who visits.
#: Names chosen to be nobody in particular, and roles chosen to exercise
#: every gate -- an owner, an adult, a child who may never be checked in
#: on, and a guest who gets nothing.
#: The five voices, chosen by measurement rather than by ear. Every one
#: of Kokoro's 28 was synthesised on the same sentence and embedded with
#: the sherpa CAM++ model the house uses; these five are the set whose
#: worst pair is furthest apart (2026-09-20).
#:
#: The first attempt picked plausible-sounding voices and `af_heart` and
#: `af_bella` scored **0.77** against each other -- two personas the
#: embedder simply could not tell apart, which would have looked like
#: Sim misidentifying people in every scenario. The measured set's worst
#: pair is 0.24, against a target of 0.4:
#:
#:     am_puck / bm_lewis     0.00      bm_lewis / af_nicole   0.02
#:     am_puck / bf_isabella  0.11      bm_lewis / af_river    0.12
#:     bm_lewis / bf_isabella 0.14      am_puck / af_river     0.17
#:     bf_isabella / af_river 0.17      am_puck / af_nicole    0.22
#:     af_river / af_nicole   0.23      bf_isabella / af_nicole 0.24
#:
#: `tools/house_voices.py` re-runs the measurement when Kokoro changes.
HOUSEHOLD: tuple[Persona, ...] = (
    Persona(name="Mara", role="owner", voice="af_river", pace=1.0,
            day={7: "kitchen", 9: "office", 18: "kitchen", 21: "living room"},
            interests=("sailing", "bread"), says_sim_as="Sim"),
    Persona(name="Devin", role="adult", voice="bm_lewis", pace=0.95,
            day={7: "kitchen", 8: "out", 19: "living room"},
            interests=("cycling", "jazz"), says_sim_as="Sim"),
    Persona(name="Nell", role="child", voice="bf_isabella", pace=1.1,
            day={8: "kitchen", 16: "living room", 20: "bedroom"},
            interests=("dinosaurs", "swimming"), says_sim_as="Sim"),
    Persona(name="Otto", role="child", voice="am_puck", pace=1.15,
            day={8: "kitchen", 16: "garden", 20: "bedroom"},
            interests=("space", "lego"), says_sim_as="Sim"),
    Persona(name="Priya", role="guest", voice="af_nicole", pace=1.0,
            day={19: "living room"}, interests=(), says_sim_as="Sim"),
)


def by_name(name: str) -> Persona | None:
    lowered = (name or "").strip().lower()
    return next((p for p in HOUSEHOLD if p.name.lower() == lowered), None)


def by_role(role: str) -> tuple[Persona, ...]:
    return tuple(p for p in HOUSEHOLD if p.role == role)


@dataclass
class Enrolment:
    """What enrolling the household measured."""

    scores: dict = field(default_factory=dict)          # name -> self-identification
    cross: dict = field(default_factory=dict)           # (a, b) -> how alike
    coherence: dict = field(default_factory=dict)       # name -> profile self-agreement
    problems: list = field(default_factory=list)

    @property
    def worst_cross(self) -> float:
        return max(self.cross.values(), default=0.0)

    def too_alike(self, bar: float = 0.4) -> list:
        """Pairs the embedder cannot tell apart, worst first. A finding
        about the VOICES, reported before a scenario blames Sim."""
        return sorted(((pair, score) for pair, score in self.cross.items() if score >= bar),
                      key=lambda row: -row[1])

    def as_dict(self) -> dict:
        return {"scores": {k: round(v, 3) for k, v in self.scores.items()},
                "coherence": {k: round(v, 3) for k, v in self.coherence.items()},
                "worst_cross": round(self.worst_cross, 3),
                "too_alike": [[list(pair), round(score, 3)] for pair, score in self.too_alike()],
                "problems": list(self.problems)}


async def enrol(book, synthesiser, embedder, people=HOUSEHOLD, *,
                lines: tuple[str, ...] = ENROLMENT_LINES) -> Enrolment:
    """Enrol each persona into `book` from synthesised speech, and
    measure what that bought.

    The same path a person takes: speak, embed, enrol. Nothing here
    writes a vector by hand, so a change to the embedder or to the
    book's rules shows up in these numbers rather than hiding behind a
    fixture.
    """
    from simorgh.voice.speakers import coherence

    def _embed(audio) -> list:
        """An `Audio` through the embedder, which wants float samples
        and their rate (`speakers.SpeakerEmbedder.embed`).

        numpy where it exists (it comes with sherpa-onnx, so in
        practice it always does) and `array` otherwise, the way
        `speakers.py` handles the same conversion -- a guarded
        third-party import, because nothing in a package may depend on
        one that is not declared."""
        try:
            import numpy as np

            samples = np.frombuffer(audio.pcm, dtype=np.int16).astype(np.float32) / 32768.0
        except ImportError:  # pragma: no cover -- numpy comes with sherpa-onnx
            import array

            samples = [s / 32768.0 for s in array.array("h", audio.pcm)]
        return embedder.embed(samples, audio.sample_rate)

    report = Enrolment()
    vectors: dict[str, list] = {}
    for persona in people:
        takes = []
        for line in lines:
            audio = await synthesiser.synthesise(line, voice=persona.voice)
            takes.append(_embed(audio))
        for take in takes:
            _person, note = book.enroll(persona.name, take, relation=persona.role, insist=True)
            if note:
                report.problems.append(f"{persona.name}: {note}")
        vectors[persona.name] = takes
        entry = book.get(persona.name)
        report.coherence[persona.name] = coherence(entry.embeddings) if entry else 0.0

    # A fresh sentence nobody enrolled: can the book place it?
    for persona in people:
        audio = await synthesiser.synthesise(
            "I was going to ask you something and now it has gone completely out of my head.",
            voice=persona.voice)
        fresh = _embed(audio)
        scores = dict(book.scores(fresh))
        report.scores[persona.name] = scores.get(persona.name, 0.0)
        for other, score in scores.items():
            if other != persona.name:
                pair = tuple(sorted((persona.name, other)))
                report.cross[pair] = max(report.cross.get(pair, 0.0), score)
    return report


__all__ = ["ENROLMENT_LINES", "Enrolment", "HOUSEHOLD", "Persona", "by_name", "by_role", "enrol"]
