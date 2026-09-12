"""How a thing is said, not what: pace, loudness, and the room between
sentences, chosen from the situation.

The creator, 2026-09-12: "a real human would talk at different pace
based on different situation. When they hear something new which
doesn't have context they may reply with 'Aha' with slower pace; when
they get the context and become more sure they say 'got it' faster;
mid-speech they confirm the other party with 'uh-huh' in a lower
voice; they say 'I know' to show empathy in the proper tone. I'd like
Sim to have empathy."

Kokoro has no emotion dial. It has speed; we add gain (loudness) and
the planner's pauses, scaled. That is three knobs, and three knobs are
enough for the registers a listener actually hears:

    neutral   the ordinary answer
    warm      empathy -- slower, softer, more room; "I know."
    bright    good news, a confident answer -- a touch quicker
    unsure    hearing something new -- "Aha…", slow and soft
    brisk     the context landed -- "Got it.", quick
    hum       a listener's "uh-huh" under the other person, half loud

`register_for_reply` reads the person's words (an empathy cue like
"tired", "sorry", "died"; excitement like "great!") and the persona's
mood (valence and arousal from persona/mood.py) into a register;
`register_for_backchannel` maps the kind of turn to one. Pure functions;
the session applies the `Delivery` when it builds the TTS request.
"""

from __future__ import annotations

import array
import re
from dataclasses import dataclass

from .backchannel import EMPATHY, HEARD, QUESTION, REQUEST


@dataclass(frozen=True)
class Delivery:
    register: str = "neutral"
    speed: float = 1.0        # Kokoro's own: 1.0 = normal
    gain: float = 1.0         # loudness multiplier on the PCM
    pause_scale: float = 1.0  # the planner's pauses, stretched or tightened

    def with_base(self, speed: float, volume: float) -> "Delivery":
        """This delivery on top of the configured speed and volume."""
        return Delivery(self.register, round(self.speed * speed, 3), round(self.gain * volume, 3), self.pause_scale)


REGISTERS: dict[str, Delivery] = {
    "neutral": Delivery("neutral", 1.0, 1.0, 1.0),
    "warm": Delivery("warm", 0.92, 0.85, 1.35),
    "bright": Delivery("bright", 1.06, 1.0, 0.9),
    "unsure": Delivery("unsure", 0.88, 0.9, 1.2),
    "brisk": Delivery("brisk", 1.12, 1.0, 0.8),
    "hum": Delivery("hum", 1.0, 0.45, 1.0),
}

# Feelings, not states of the system: "the pool is exhausted", "the
# build failed" and "the link is dead" are engineering, not a hurt.
_EMPATHY = re.compile(
    r"\b(?:sorry|sad|tired|frustrat\w*|died|passed away|hard day|rough day|stressed|worried|scared|afraid|"
    r"alone|lonely|upset|angry|annoyed|can'?t take|give up|giving up|overwhelmed|depress\w*|anxious|anxiety|"
    r"grief|griev\w*|cry\w*|hopeless|unfair|awful|terrible|horrible|miss (?:him|her|them|you|my))\b"
    r"|ناراحت|خسته|متاسف|غمگین|دلم گرفته|مریض|نگران|ترسیده|تنها|عصبانی|گریه", re.I)
_BRIGHT = re.compile(
    r"\b(?:great|awesome|amazing|wonderful|excellent|perfect|love it|congrats|congratulations|yay|wow|"
    r"finally|we did it|nailed it|brilliant|fantastic|excited|exciting|happy|glad)\b|!{1,}"
    r"|عالی|فوق‌العاده|آفرین|خوشحال|هیجان|مبارک", re.I)
_QUESTION_BACK = re.compile(r"\?\s*$")


def register_for_reply(user_text: str, reply: str, *, valence: float = 0.0, arousal: float = 0.0,
                       is_error: bool = False) -> Delivery:
    """The register for answering `user_text` with `reply`.

    The person's words decide first: a hurt in them is answered warm,
    whatever the answer says; joy is answered bright. Then the reply's
    own tone, then the mood -- a low valence takes the edge off, a high
    arousal quickens -- in small steps, so the mood colours delivery
    without ever contradicting the words."""
    user_text, reply = user_text or "", reply or ""
    if _EMPATHY.search(user_text):
        base = REGISTERS["warm"]
    elif is_error:
        base = Delivery("warm", 0.95, 0.9, 1.2)
    elif _BRIGHT.search(user_text) or (_BRIGHT.search(reply) and not _EMPATHY.search(reply)):
        base = REGISTERS["bright"]
    elif _EMPATHY.search(reply):
        base = REGISTERS["warm"]
    else:
        base = REGISTERS["neutral"]
    speed = base.speed
    if valence < -0.15:
        speed -= 0.03
    if arousal > 0.3:
        speed += 0.04
    elif arousal < -0.3:
        speed -= 0.03
    return Delivery(base.register, round(max(0.8, min(1.2, speed)), 3), base.gain, base.pause_scale)


def register_for_backchannel(kind: str) -> Delivery:
    """`Aha…` slow and soft for something new; `Got it.` quick once the
    ask is clear; the empathy sound warm; a plain remark in between."""
    return {
        QUESTION: REGISTERS["unsure"],
        HEARD: Delivery("unsure", 0.94, 0.95, 1.0),
        REQUEST: REGISTERS["brisk"],
        EMPATHY: REGISTERS["warm"],
    }.get(kind, REGISTERS["neutral"])


def apply_gain(pcm: bytes, gain: float) -> bytes:
    """`pcm` (int16) scaled by `gain`, clipped; untouched at 1.0."""
    if gain == 1.0 or not pcm:
        return pcm
    samples = array.array("h", pcm[: len(pcm) - len(pcm) % 2])
    for i, s in enumerate(samples):
        v = int(s * gain)
        samples[i] = 32767 if v > 32767 else (-32768 if v < -32768 else v)
    return samples.tobytes()


__all__ = ["Delivery", "REGISTERS", "apply_gain", "register_for_backchannel", "register_for_reply"]
