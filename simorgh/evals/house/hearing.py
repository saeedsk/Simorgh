"""Audio into the session's own ears (stage 11 item 4).

`Director.say` drives `Pipeline.ask`, which asks Sim directly. That is
right for a scenario about what Sim *answers*, and useless for one
about what Sim *ignores*: the decisions that went wrong live -- is
this for me, was that my own echo, do I know this voice -- are made in
the listening loop, before `ask` is ever called.

So a scenario can also speak into the microphone. The persona's voice
is synthesised, put through the scene, and handed to the fake
microphone frame by frame; the session's VAD finds the utterance, the
recogniser returns the line the scenario queued for it, the real
speaker book places the voice, and the real rules decide whether Sim
answers.

The recogniser is scripted rather than real on purpose: word error is
measured separately (item 3's table) and a scenario about "did Sim
stay out of it" should not fail because whisper misheard a word. The
*audio* is still real, which is what the speaker book needs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from simorgh.voice.api import Audio, Utterance


@dataclass
class ScriptedRecogniser:
    """Returns the line the scenario queued for the utterance in flight.

    The same line for every call, not one per call: the session
    transcribes a growing buffer several times per utterance (a
    partial as the person speaks, then the final), and a recogniser
    that handed out its script one call at a time gave the first
    partial the words and the FINAL transcription nothing -- so every
    turn was heard, shown on screen, and then dropped. Found the first
    time audio went through the real listening loop (2026-09-20).

    Sound the scenario did not queue -- Sim's own echo, the television
    on its own -- comes back empty, which is what lets an echo be
    tested as a non-turn.
    """

    name: str = "scripted"
    line: str = ""
    confidence: float = 0.95
    heard: list = field(default_factory=list)
    said: list = field(default_factory=list)

    def queue(self, text: str, *, confidence: float | None = None) -> None:
        """What the next utterance says. Replaces whatever was there:
        one line is in flight at a time, as one person speaks at a
        time into one microphone."""
        self.line = text
        if confidence is not None:
            self.confidence = confidence
        self.said.append(text)

    def silence(self) -> None:
        """The next sound is not speech anybody scripted."""
        self.line = ""

    async def transcribe(self, audio: Audio, *, language: str = "") -> Utterance:
        self.heard.append(audio)
        return Utterance(text=self.line, confidence=self.confidence if self.line else 0.0,
                         seconds=audio.seconds, engine=self.name)


async def speak_into(microphone, audio: Audio, *, settle: float = 0.0) -> None:
    """Hand `audio` to the fake microphone as a person would make it."""
    microphone.feed(audio)
    if settle:
        await asyncio.sleep(settle)


__all__ = ["ScriptedRecogniser", "speak_into"]
