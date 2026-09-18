"""Streaming recognition over a whole-utterance recogniser.

Whisper decodes an utterance, not a stream. What a listener needs while
a person is still talking is a provisional reading of what has been
said so far -- for the screen, and for the turn manager's semantic cue
-- and that is what this makes: every `partial_every_ms` of new audio
the whole buffer so far is decoded again in a thread, and the result
is a `partial` that replaces the last one. When the frames end (the
turn manager finalised the turn), one last decode of the whole buffer
is the `final`, and it replaces every partial cleanly. A partial decode
still in flight when the turn ends is abandoned, never waited for.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from ..api import SAMPLE_RATE, SAMPLE_WIDTH, Audio, TranscriptEvent, Utterance

_BYTES_PER_MS = SAMPLE_RATE * SAMPLE_WIDTH // 1000


class IncrementalRecogniser:
    """`SpeechToTextProvider` over a `Recogniser`."""

    def __init__(self, inner, *, partials: bool = True, partial_every_ms: int = 1500,
                 min_partial_ms: int = 900) -> None:
        self._inner = inner
        self._partials = partials
        self._every = max(200, partial_every_ms) * _BYTES_PER_MS
        self._min = max(100, min_partial_ms) * _BYTES_PER_MS
        self._inflight: asyncio.Task | None = None
        self.partials_made = 0
        #: partials stop when the engine cannot make them faster than they
        #: are asked for -- see `start_stream`.
        self.partials_outpaced = 0

    async def warmup(self) -> float:
        """Start an engine that runs a server (whisper-server) now."""
        own = getattr(self._inner, "warmup", None)
        return float(await own()) if callable(own) else 0.0

    @property
    def name(self) -> str:
        return f"incremental:{getattr(self._inner, 'name', '')}"

    @property
    def inner(self):
        return self._inner

    async def transcribe(self, audio: Audio, *, language: str = "") -> Utterance:
        return await self._inner.transcribe(audio, language=language)

    async def stop(self) -> None:
        if self._inflight is not None and not self._inflight.done():
            self._inflight.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._inflight
        self._inflight = None

    async def start_stream(self, frames, *, turn_id: int, language: str = ""):
        buffer = bytearray()
        decoded_upto = 0
        last_text = ""
        outpaced = False
        started_at: float | None = None
        every_s = self._every / (_BYTES_PER_MS * 1000.0)
        engine = getattr(self._inner, "name", "")
        async for frame in frames:
            buffer += frame
            if self._inflight is not None and self._inflight.done():
                task, self._inflight = self._inflight, None
                # A partial is only worth having if the engine can produce it
                # faster than the cadence asks for one. For a streaming
                # engine that is free; for whisper a "partial" is a FULL
                # decode -- it pads every input to a 30 s window, so it costs
                # 2-3.5 s whatever the length -- and whisper-server decodes
                # serially. Several of those per turn queue ahead of the
                # final decode on the one thing the answer is waiting for,
                # and a superseded one still runs because `asyncio.to_thread`
                # cannot be cancelled. Live 2026-09-17: stt held 1.8-3.7 s
                # for twenty minutes, then 46 s, then 174 s for one word.
                # So: when a partial takes longer than the cadence, this turn
                # asks for no more of them.
                if started_at is not None and (time.monotonic() - started_at) > every_s:
                    outpaced = True
                    self.partials_outpaced += 1
                started_at = None
                try:
                    utterance = task.result()
                except Exception:  # noqa: BLE001 -- a failed partial is no partial
                    utterance = None
                if utterance is not None and utterance.text.strip() and utterance.text != last_text:
                    last_text = utterance.text
                    self.partials_made += 1
                    yield TranscriptEvent("partial", utterance.text, turn_id, confidence=utterance.confidence,
                                          language=utterance.language, audio_seconds=utterance.seconds,
                                          engine=utterance.engine or engine)
            if (self._partials and not outpaced and self._inflight is None and len(buffer) >= self._min
                    and len(buffer) - decoded_upto >= self._every):
                decoded_upto = len(buffer)
                snapshot = Audio(bytes(buffer))
                started_at = time.monotonic()
                self._inflight = asyncio.create_task(self._inner.transcribe(snapshot, language=language))
        await self.stop()
        if not buffer:
            yield TranscriptEvent("final", "", turn_id, confidence=0.0, engine=engine)
            return
        final = await self._inner.transcribe(Audio(bytes(buffer)), language=language)
        yield TranscriptEvent("final", final.text, turn_id, confidence=final.confidence, language=final.language,
                              audio_seconds=final.seconds, engine=final.engine or engine,
                              words=tuple(getattr(final, "words", ()) or ()), audio=bytes(buffer))


__all__ = ["IncrementalRecogniser"]
