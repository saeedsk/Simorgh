"""Streaming synthesis over any synthesiser: a reply is spoken piece by
piece, the first piece as soon as it is ready.

`StreamingSynthesiser` takes the planner's pieces, synthesises them one
at a time in a worker thread, keeps a short lookahead (a piece or two,
never the whole reply -- a cancelled reply must stop quickly, and a
stale one must never keep synthesising), levels each piece so no piece
jumps in volume, and appends the planner's pause after it. Cancelling
a request stops the producer between pieces; the piece in flight
finishes in its thread and is dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time

from ..api import SAMPLE_WIDTH, Audio, AudioChunk, TtsRequest

#: What each piece is levelled to, as int16 RMS. Kokoro sits near this;
#: a Piper voice runs hotter and `say` quieter, and the ear hears the
#: step between pieces before it hears the words.
TARGET_RMS = 2600.0
_MIN_GAIN, _MAX_GAIN = 0.5, 3.0
_LIMIT = 32000

_SENTINEL = object()


def _rms(pcm: bytes) -> float:
    try:
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        return float(math.sqrt(np.mean(samples * samples))) if samples.size else 0.0
    except ImportError:  # pragma: no cover -- numpy is always beside kokoro-onnx
        import array

        samples = array.array("h", pcm)
        return math.sqrt(sum(x * x for x in samples) / len(samples)) if samples else 0.0


def levelled(pcm: bytes, *, target: float = TARGET_RMS) -> bytes:
    """`pcm` scaled towards `target` RMS, within a modest range and with
    a hard ceiling, so a quiet engine and a loud one meet in the middle
    without clipping. Silence and near-silence are left alone."""
    rms = _rms(pcm)
    if rms < 50.0:
        return pcm
    gain = max(_MIN_GAIN, min(_MAX_GAIN, target / rms))
    if abs(gain - 1.0) < 0.05:
        return pcm
    try:
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) * gain
        return np.clip(samples, -_LIMIT, _LIMIT).astype(np.int16).tobytes()
    except ImportError:  # pragma: no cover
        import array

        out = array.array("h", (max(-_LIMIT, min(_LIMIT, int(x * gain))) for x in array.array("h", pcm)))
        return out.tobytes()


def silence(ms: int, sample_rate: int) -> bytes:
    return b"\x00" * (int(sample_rate * ms / 1000) * SAMPLE_WIDTH)


class StreamingSynthesiser:
    """`TextToSpeechProvider` over a whole-utterance `Synthesiser`."""

    def __init__(self, inner, *, lookahead: int = 2, level: bool = True) -> None:
        self._inner = inner
        self._lookahead = max(1, lookahead)
        self._level = level
        self._cancelled: set[str] = set()
        self._producers: dict[str, asyncio.Task] = {}
        self.warm = False
        self.warmup_seconds = 0.0
        self.last_engine = getattr(inner, "name", "")

    @property
    def name(self) -> str:
        return getattr(self._inner, "name", "")

    @property
    def inner(self):
        return self._inner

    def list_voices(self) -> list[str]:
        return list(self._inner.voices())

    def voices(self) -> list[str]:  # the old protocol, for callers that still use it
        return self.list_voices()

    async def warmup(self) -> float:
        """Load the model by speaking one short phrase into nothing, so
        the first real reply does not pay for it. Returns the seconds it
        took; 0.0 when already warm."""
        if self.warm:
            return 0.0
        started = time.monotonic()
        await self._inner.synthesise("Okay.", speed=1.0)
        self.warmup_seconds = time.monotonic() - started
        self.warm = True
        return self.warmup_seconds

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0) -> Audio:
        """The whole-utterance path, kept for `voice test` and callers
        that want one `Audio`."""
        return await self._inner.synthesise(text, voice=voice, speed=speed)

    async def cancel(self, request_id: str) -> None:
        """Stop synthesising `request_id`. Returns at once: the consumer
        of the stream sees the end on its next read, and the piece in
        flight finishes in its thread and is dropped."""
        self._cancelled.add(request_id)
        task = self._producers.get(request_id)
        if task is not None and not task.done():
            task.cancel()

    async def synthesise_stream(self, request: TtsRequest):
        """Yield `AudioChunk`s for `request.pieces`, in order, as each is
        synthesised; `final` marks the last."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._lookahead)
        self._cancelled.discard(request.request_id)

        async def _produce() -> None:
            cancelled = False
            try:
                total = len(request.pieces)
                for seq, (text, pause_ms) in enumerate(request.pieces):
                    if request.request_id in self._cancelled:
                        break
                    audio = await self._inner.synthesise(text, voice=request.voice, speed=request.speed)
                    if request.request_id in self._cancelled:
                        break
                    self.last_engine = getattr(self._inner, "last_engine", None) or getattr(self._inner, "name", "")
                    pcm = levelled(audio.pcm) if self._level else audio.pcm
                    if pause_ms > 0 and seq < total - 1:
                        pcm += silence(pause_ms, audio.sample_rate)
                    await queue.put(AudioChunk(pcm=pcm, sample_rate=audio.sample_rate, request_id=request.request_id,
                                               seq=seq, final=seq == total - 1, text=text, pause_ms=pause_ms))
            except asyncio.CancelledError:
                cancelled = True
                raise
            finally:
                if cancelled:
                    # Nobody may be reading a full queue any more, and a
                    # sentinel that waits for room is a deadlock: the
                    # chunks are stale, so make room by dropping them.
                    while True:
                        try:
                            queue.put_nowait(_SENTINEL)
                            break
                        except asyncio.QueueFull:
                            with contextlib.suppress(asyncio.QueueEmpty):
                                queue.get_nowait()
                else:
                    # The end, in order, after every chunk: this waits for
                    # room the way a chunk does, never over one.
                    await queue.put(_SENTINEL)

        producer = asyncio.create_task(_produce())
        self._producers[request.request_id] = producer
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            if not producer.done():
                producer.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await producer
            self._producers.pop(request.request_id, None)
            self._cancelled.discard(request.request_id)


__all__ = ["StreamingSynthesiser", "TARGET_RMS", "levelled", "silence"]
