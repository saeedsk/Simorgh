"""Who is speaking: speaker embeddings, a book of the household's voices,
and the decision "this is Ira" / "someone I don't know".

The creator, 2026-09-13: "I want Sim to have the ability to recognise
the voice of different family members ... when my daughter talks to
her, know who she is." This module is the recognition half; what Sim
does with the name (memory per person, who is talking to whom) lives
in the session and the memory subsystem.

How it works
------------
An utterance's audio becomes a fixed-size vector (a *speaker
embedding*) through an open-source speaker-verification model --
`wespeaker_en_voxceleb_CAM++_LM.onnx` (Apache-2.0, from the WeSpeaker
project, run by `sherpa-onnx` on the CPU; 29 MB, ~60 ms for a sentence
on the M3 Pro). Two vectors of the same person are close (cosine near
0.6-0.9 for real voices); different people sit lower. The `SpeakerBook`
keeps, per enrolled person, every enrolment vector, and decides by the
cosine to the nearest take:

    top score >= threshold  AND  top - second >= margin   -> that person
    otherwise                                             -> unknown

Both numbers are settings (`[voice] speaker_threshold`, `speaker_margin`),
because thresholds are model- and room-dependent; the defaults are the
WeSpeaker authors' for this model with a safety margin, and `voice
people test` shows the live scores so a household can tune them.

Enrolment is a few sentences (`voice enroll <name>`, three to five
takes); the book refuses a take that sounds like an already-enrolled
person, and says so, rather than blurring two people into one profile.
Everything is local: the book is JSON under `workspace/voice/speakers/`,
readable and deletable by hand (`voice forget <name>`).

Honesty rules: an identification is never asserted without its score,
`unknown` is a real answer, and the engine is refused by name when its
package or model is missing -- nothing pretends to recognise a voice.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

SPEAKER_MODEL = "wespeaker_en_voxceleb_CAM++_LM.onnx"
SPEAKER_MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
                     + SPEAKER_MODEL)
DEFAULT_THRESHOLD = 0.5
DEFAULT_MARGIN = 0.06
#: An utterance shorter than this carries too little voice to judge...
MIN_SECONDS = 0.8
#: ...and an enrolment take shorter than this is not worth keeping.
ENROLL_MIN_SECONDS = 1.5


class SpeakerEmbedder(Protocol):
    """Audio in, one vector out. `dim` is the vector's length."""

    dim: int

    def embed(self, pcm: Sequence[float], sample_rate: int) -> list[float]: ...


def available(model_dir: Path | str = "workspace/voice/models") -> tuple[bool, str]:
    import importlib.util

    if importlib.util.find_spec("sherpa_onnx") is None:
        return False, "needs sherpa-onnx (pip install sherpa-onnx)"
    model = Path(model_dir) / SPEAKER_MODEL
    if not model.is_file():
        return False, f"needs the speaker model at {model} (curl -L -o {model} {SPEAKER_MODEL_URL})"
    return True, ""


class SherpaEmbedder:
    """The real engine: sherpa-onnx's SpeakerEmbeddingExtractor over the
    WeSpeaker CAM++ model. Loaded on first use; resamples to 16 kHz."""

    def __init__(self, model_dir: Path | str = "workspace/voice/models", *, threads: int = 2) -> None:
        self._model = Path(model_dir) / SPEAKER_MODEL
        self._threads = threads
        self._ext = None
        self.dim = 512

    def _extractor(self):
        if self._ext is None:
            ok, why = available(self._model.parent)
            if not ok:
                raise RuntimeError(why)
            try:
                import sherpa_onnx
            except ImportError as exc:
                raise RuntimeError("needs sherpa-onnx (pip install sherpa-onnx)") from exc

            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self._model), num_threads=self._threads)
            self._ext = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
            self.dim = int(self._ext.dim)
        return self._ext

    def embed(self, pcm: Sequence[float], sample_rate: int) -> list[float]:
        ext = self._extractor()
        stream = ext.create_stream()
        try:
            import numpy as np

            samples = np.asarray(pcm, dtype=np.float32)
        except ImportError:  # pragma: no cover -- numpy comes with sherpa-onnx
            samples = list(map(float, pcm))
        stream.accept_waveform(sample_rate, samples)
        stream.input_finished()
        return [float(x) for x in ext.compute(stream)]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


def _mean(vectors: Sequence[Sequence[float]]) -> list[float]:
    if not vectors:
        return []
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(len(vectors[0]))]


@dataclass
class Person:
    name: str
    #: how they relate to the household, in their own words ("daughter, 9")
    relation: str = ""
    #: how Sim should say the name ("Ay-raa" for Ira): the TTS engines read
    #: an unusual name the English way otherwise
    say_as: str = ""
    embeddings: list[list[float]] = field(default_factory=list)
    enrolled_at: float = 0.0
    last_heard: float = 0.0
    heard: int = 0

    @property
    def mean(self) -> list[float]:
        return _mean(self.embeddings)

    def to_json(self) -> dict:
        return {"name": self.name, "relation": self.relation, "say_as": self.say_as, "embeddings": self.embeddings,
                "enrolled_at": self.enrolled_at, "last_heard": self.last_heard, "heard": self.heard}

    @classmethod
    def from_json(cls, data: dict) -> "Person":
        return cls(name=str(data.get("name") or ""), relation=str(data.get("relation") or ""), say_as=str(data.get("say_as") or ""),
                   embeddings=[[float(x) for x in v] for v in data.get("embeddings") or []],
                   enrolled_at=float(data.get("enrolled_at") or 0.0), last_heard=float(data.get("last_heard") or 0.0),
                   heard=int(data.get("heard") or 0))


@dataclass(frozen=True)
class Identification:
    """Who the book thinks spoke. `name` is "" for unknown; `score` is the
    best cosine, `runner_up` the second best, so a person can see why."""

    name: str
    score: float
    runner_up: str = ""
    runner_up_score: float = 0.0
    reason: str = ""

    @property
    def known(self) -> bool:
        return bool(self.name)


class SpeakerBook:
    """The household's voices: enrolment, identification, persistence."""

    def __init__(self, folder: Path | str = "workspace/voice/speakers", *, threshold: float = DEFAULT_THRESHOLD,
                 margin: float = DEFAULT_MARGIN, clock=time.time) -> None:
        self._folder = Path(folder)
        self.threshold = float(threshold)
        self.margin = float(margin)
        self._clock = clock
        self._people: dict[str, Person] = {}
        self._loaded = False

    # -- persistence

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self._folder.is_dir():
            return
        for path in sorted(self._folder.glob("*.json")):
            try:
                person = Person.from_json(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if person.name:
                self._people[person.name.lower()] = person

    def _save(self, person: Person) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        path = self._folder / f"{_safe(person.name)}.json"
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(person.to_json()), encoding="utf-8")
        tmp.replace(path)

    # -- the book

    def people(self) -> list[Person]:
        self._load()
        return sorted(self._people.values(), key=lambda p: p.name.lower())

    def get(self, name: str) -> Person | None:
        self._load()
        return self._people.get((name or "").strip().lower())

    def pronounce(self, name: str, say_as: str, *, relation: str = "") -> Person:
        """Remember how to say `name` (creating the person, voiceless, if
        they are not enrolled yet -- a name can be known before a voice)."""
        self._load()
        name = (name or "").strip()
        if not name:
            raise ValueError("a name is needed")
        person = self._people.get(name.lower())
        if person is None:
            person = Person(name=name, relation=relation, enrolled_at=self._clock())
            self._people[name.lower()] = person
        person.say_as = (say_as or "").strip()
        if relation and not person.relation:
            person.relation = relation
        self._save(person)
        return person

    def pronunciations(self) -> dict[str, str]:
        """name -> how to say it, for everyone who has one."""
        self._load()
        return {p.name: p.say_as for p in self._people.values() if p.say_as}

    def forget(self, name: str) -> bool:
        self._load()
        person = self._people.pop((name or "").strip().lower(), None)
        if person is None:
            return False
        try:
            (self._folder / f"{_safe(person.name)}.json").unlink()
        except OSError:
            pass
        return True

    def enroll(self, name: str, embedding: Sequence[float], *, relation: str = "", insist: bool = False) -> tuple[Person, str]:
        """Add one take to `name`. Returns the person and a note: "" when
        the take was accepted, else why it was refused -- only ever
        because it sounds like someone already enrolled, and not even then
        with `insist` (the person has said it was them). A take unlike the
        person's own earlier takes is kept: real voices vary that much
        across a room, and the nearest-take rule copes."""
        self._load()
        name = (name or "").strip()
        if not name:
            raise ValueError("a name is needed")
        vector = [float(x) for x in embedding]
        person = self._people.get(name.lower())
        # Does this take sound like somebody already enrolled?
        for other in self._people.values():
            if other.name.lower() == name.lower() or not other.embeddings:
                continue
            score = self.score(vector, other)
            if score >= self.threshold + self.margin and not insist:
                target = person or Person(name=name, relation=relation)
                return target, (f"refused: that take sounds like {other.name} (score {score:.2f}); "
                                f"if it was {name}, their voices are too close for me to tell apart in this room")
        if person is None:
            person = Person(name=name, relation=relation, enrolled_at=self._clock())
            self._people[name.lower()] = person
        elif relation and not person.relation:
            person.relation = relation
        person.embeddings.append(vector)
        self._save(person)
        return person, ""

    @staticmethod
    def score(embedding: Sequence[float], person: Person) -> float:
        """How alike `embedding` is to `person`: the nearest take, not the
        mean. A real person's takes vary a lot with distance and noise
        (the creator's own three: 0.28 to 0.76 to each other), so the
        mean of them sits far from every one; the nearest take is the
        fair comparison."""
        return max((cosine(embedding, v) for v in person.embeddings), default=0.0)

    def identify(self, embedding: Sequence[float]) -> Identification:
        self._load()
        scored = sorted(((self.score(embedding, p), p) for p in self._people.values() if p.embeddings),
                        key=lambda t: t[0], reverse=True)
        if not scored:
            return Identification(name="", score=0.0, reason="nobody is enrolled")
        best_score, best = scored[0]
        second_score, second = (scored[1][0], scored[1][1]) if len(scored) > 1 else (0.0, None)
        runner = second.name if second is not None else ""
        if best_score < self.threshold:
            return Identification(name="", score=best_score, runner_up=best.name, runner_up_score=best_score,
                                  reason=f"closest is {best.name} at {best_score:.2f}, under the threshold {self.threshold:.2f}")
        if second is not None and best_score - second_score < self.margin:
            return Identification(name="", score=best_score, runner_up=runner, runner_up_score=second_score,
                                  reason=f"{best.name} {best_score:.2f} and {runner} {second_score:.2f} are too close to call")
        return Identification(name=best.name, score=best_score, runner_up=runner, runner_up_score=second_score)

    def heard(self, name: str) -> None:
        person = self.get(name)
        if person is not None:
            person.heard += 1
            person.last_heard = self._clock()
            self._save(person)

    def scores(self, embedding: Sequence[float]) -> list[tuple[str, float]]:
        """Every enrolled person's score, best first -- for `voice people test`."""
        self._load()
        return sorted(((p.name, self.score(embedding, p)) for p in self._people.values() if p.embeddings),
                      key=lambda t: t[1], reverse=True)


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name.strip()).strip("_") or "person"


def seconds_of(pcm: Sequence[float], sample_rate: int) -> float:
    return len(pcm) / float(sample_rate or 16000)


__all__ = ["DEFAULT_MARGIN", "DEFAULT_THRESHOLD", "Identification", "ENROLL_MIN_SECONDS", "MIN_SECONDS", "Person", "SPEAKER_MODEL",
           "SherpaEmbedder", "SpeakerBook", "SpeakerEmbedder", "available", "cosine", "seconds_of"]
