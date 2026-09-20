"""The room between a person and the microphone (stage 11 item 3).

A scenario that hands Sim a clean sentence tests a transcript. The
failures that actually reached the creator were acoustic: Sim answering
the television, Sim hearing its own voice come back and treating it as
a turn ("Still checking." arrived as a user turn on 2026-09-20), a
person three metres away scoring 0.37 against a 0.50 threshold. None of
those can happen to a clean sentence.

So a beat is mixed rather than handed over: the speaker's audio
attenuated for distance and smeared by a little reverb, a room bed
under it, the television or music if they are on, Sim's own last
utterance folded back at the gain the real room has, and another
person's speech overlapped if they talked at the same time. The
microphone then yields that mix frame by frame, as a microphone does.

Everything here is arithmetic on 16-bit PCM -- no libraries, because
the point is a repeatable room rather than a convincing one. What it
produces is a table (identification and word error against distance
and SNR), and three guarantees that have to hold at 3 m and 10 dB:
Sim's own echo is never a turn, the television never gets an answer,
and a person who names Sim is answered.
"""

from __future__ import annotations

import array
import math
import random
from dataclasses import dataclass, field

from simorgh.voice.audio import SAMPLE_RATE, Audio

#: Where a voice is, and how loud it therefore arrives. Roughly
#: inverse-distance: a person at the far side of the kitchen is a
#: quarter of the one leaning over the microphone.
DISTANCES: dict[str, float] = {"at the mic": 0.3, "near": 1.0, "across the room": 3.0, "far": 6.0}

#: How loud the room is under everything, as the signal-to-noise ratio
#: a speaker at 1 m would have. `clean` is a recording booth and exists
#: only to prove the harness itself is not the problem.
ROOMS: dict[str, float] = {"clean": 60.0, "quiet": 30.0, "kitchen": 20.0, "dishwasher": 10.0, "party": 5.0}

#: How much of what Sim says comes back into its own microphone. The
#: laptop's speaker is centimetres from its microphone, so this is not
#: small -- which is why the echo tests exist.
ECHO_GAIN = 0.35


def silence(seconds: float, *, sample_rate: int = SAMPLE_RATE) -> Audio:
    return Audio(b"\x00\x00" * int(seconds * sample_rate), sample_rate)


def _samples(audio: Audio) -> array.array:
    return array.array("h", audio.pcm)


def _audio(samples, *, sample_rate: int = SAMPLE_RATE) -> Audio:
    clipped = array.array("h", (max(-32768, min(32767, int(s))) for s in samples))
    return Audio(clipped.tobytes(), sample_rate)


def attenuate(audio: Audio, gain: float) -> Audio:
    """Quieter (or louder), with nothing else changed."""
    return _audio((s * gain for s in _samples(audio)), sample_rate=audio.sample_rate)


def distance_gain(metres: float) -> float:
    """What a metre costs. 1 m is unity; the curve is 1/d with a floor
    so six metres is faint rather than absent."""
    return 1.0 / max(0.5, float(metres))


def reverb(audio: Audio, metres: float) -> Audio:
    """A crude early reflection: the same sound again, quieter and a
    few milliseconds later. Enough to stop a distant voice being
    merely a quiet near one, which is the thing that would make the
    distance table lie."""
    if metres <= 1.0:
        return audio
    samples = _samples(audio)
    delay = int(audio.sample_rate * min(0.05, 0.004 * metres))
    strength = min(0.4, 0.08 * metres)
    out = array.array("h", samples)
    for i in range(delay, len(samples)):
        out[i] = max(-32768, min(32767, int(samples[i] + samples[i - delay] * strength)))
    return Audio(out.tobytes(), audio.sample_rate)


def noise(seconds: float, *, rms: float, seed: int = 0, sample_rate: int = SAMPLE_RATE) -> Audio:
    """A room bed: shaped noise at a given loudness. Seeded, so a
    scenario that failed can be run again and fail the same way."""
    rng = random.Random(seed)
    n = int(seconds * sample_rate)
    # Two poles of smoothing: white noise sounds like a fault, and a
    # room sounds like a room.
    out, last, last2 = array.array("h", [0]) * n, 0.0, 0.0
    for i in range(n):
        white = rng.gauss(0.0, rms)
        last = 0.7 * last + 0.3 * white
        last2 = 0.7 * last2 + 0.3 * last
        out[i] = max(-32768, min(32767, int(last2 * 3.0)))
    return Audio(out.tobytes(), sample_rate)


def rms_of(audio: Audio) -> float:
    samples = _samples(audio)
    if not samples:
        return 0.0
    return math.sqrt(sum(float(s) * s for s in samples) / len(samples))


def noise_for(audio: Audio, snr_db: float, *, seed: int = 0) -> Audio:
    """A bed as long as `audio`, at the loudness `snr_db` asks for."""
    signal = rms_of(audio) or 1000.0
    return noise(len(_samples(audio)) / audio.sample_rate,
                 rms=signal / (10.0 ** (snr_db / 20.0)), seed=seed, sample_rate=audio.sample_rate)


def mix(*layers: Audio, sample_rate: int = SAMPLE_RATE) -> Audio:
    """Everything at once, as long as the longest."""
    tracks = [_samples(a) for a in layers if a is not None]
    if not tracks:
        return silence(0.0, sample_rate=sample_rate)
    length = max(len(t) for t in tracks)
    out = [0.0] * length
    for track in tracks:
        for i, s in enumerate(track):
            out[i] += s
    return _audio(out, sample_rate=sample_rate)


def overlap(first: Audio, second: Audio, *, after: float) -> Audio:
    """`second` starting `after` seconds into `first` -- two people
    talking over each other, which is most of a kitchen."""
    pad = silence(max(0.0, after), sample_rate=second.sample_rate)
    delayed = Audio(pad.pcm + second.pcm, second.sample_rate)
    return mix(first, delayed, sample_rate=first.sample_rate)


@dataclass
class Scene:
    """What the microphone is hearing, beat by beat.

    Holds the room and whatever is playing, so a scenario sets the
    kitchen once and every later beat is in that kitchen. `hear()`
    turns one person's clean speech into what actually arrives.
    """

    room: str = "quiet"
    distance: float = 1.0
    #: The television or music, as speech/song that is NOT for Sim.
    playing: Audio | None = None
    playing_gain: float = 0.5
    #: What Sim said last, for the echo path.
    last_said: Audio | None = None
    echo_gain: float = ECHO_GAIN
    seed: int = 20260920
    _beat: int = field(default=0, repr=False)

    def snr_db(self) -> float:
        return ROOMS.get(self.room, 20.0)

    def hear(self, speech: Audio, *, distance: float | None = None,
             also: Audio | None = None, also_after: float = 0.0) -> Audio:
        """One person's voice as the microphone gets it.

        Order matters and follows the physics: attenuate for distance,
        add the room's reflection, then lay the room bed, whatever is
        playing and Sim's own echo underneath, then anybody talking at
        the same time.
        """
        self._beat += 1
        metres = self.distance if distance is None else float(distance)
        near = reverb(attenuate(speech, distance_gain(metres)), metres)
        layers = [near, noise_for(near, self.snr_db(), seed=self.seed + self._beat)]
        if self.playing is not None:
            layers.append(attenuate(_fit(self.playing, near), self.playing_gain))
        if self.last_said is not None:
            layers.append(attenuate(_fit(self.last_said, near), self.echo_gain))
        heard = mix(*layers, sample_rate=speech.sample_rate)
        if also is not None:
            heard = overlap(heard, attenuate(also, distance_gain(metres)), after=also_after)
        return heard


def _fit(bed: Audio, like: Audio) -> Audio:
    """`bed` trimmed or looped to the length of `like`."""
    want = len(_samples(like))
    have = _samples(bed)
    if not have:
        return silence(0.0, sample_rate=like.sample_rate)
    if len(have) >= want:
        return Audio(have[:want].tobytes(), bed.sample_rate)
    repeats = (want // len(have)) + 1
    grown = array.array("h")
    for _ in range(repeats):
        grown.extend(have)
    return Audio(grown[:want].tobytes(), bed.sample_rate)


__all__ = ["DISTANCES", "ECHO_GAIN", "ROOMS", "Scene", "attenuate", "distance_gain", "mix",
           "noise", "noise_for", "overlap", "reverb", "rms_of", "silence"]
