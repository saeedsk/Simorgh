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


EDGE_MS = 5


def edged(pcm: bytes, sample_rate: int, *, ms: int = EDGE_MS) -> bytes:
    """`pcm` with its first and last `ms` ramped from and to zero. A
    piece that starts mid-wave clicks when the player opens on it; a
    piece that ends mid-wave clicks when the next begins. The creator
    heard "weird jitter or spikes" on Chatterbox's pieces, each played
    on its own (2026-09-13); this is the seam made silent."""
    n = int(sample_rate * ms / 1000)
    if n <= 0 or len(pcm) < 2 * n * SAMPLE_WIDTH * 2:
        return pcm
    try:
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
        ramp = np.linspace(0.0, 1.0, n, endpoint=False)
        samples[:n] *= ramp
        samples[-n:] *= ramp[::-1]
        return samples.astype(np.int16).tobytes()
    except ImportError:  # pragma: no cover
        import array

        samples = array.array("h", pcm)
        for i in range(n):
            samples[i] = int(samples[i] * i / n)
            samples[-1 - i] = int(samples[-1 - i] * i / n)
        return samples.tobytes()


#: characters of text per second of speech, for guessing how long a
#: reply will take to say before any of it is rendered
CHARS_PER_SECOND = 14.0
#: the most a slow engine may make the listener wait for a gapless reply
MAX_HOLD_S = 25.0
#: A ceiling on waiting for one piece, and the slack over the estimate.
#: MisoTTS measured 10x warm and 44x cold on the M3 Pro, so a first
#: piece can be minutes; past this the engine really has stopped.
MAX_CHUNK_WAIT_S = 300.0
CHUNK_WAIT_MARGIN = 2.0


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

    async def _synth(self, text: str, *, voice: str, speed: float, tone: str, lane: str = ""):
        """The engine's synthesise, with the tone and lane when it takes them."""
        if not getattr(self._inner, "speaks_ipa", False):
            from ..pronounce import strip_marks

            text = strip_marks(text)
        kwargs: dict = {"voice": voice, "speed": speed}
        if tone and self._takes("tone"):
            kwargs["tone"] = tone
        if lane and self._takes("lane"):
            kwargs["lane"] = lane
        return await self._inner.synthesise(text, **kwargs)

    def _takes(self, name: str) -> bool:
        cache = getattr(self, "_takes_cache", None)
        if cache is None:
            cache = self._takes_cache = {}
        if name not in cache:
            import inspect

            try:
                params = inspect.signature(self._inner.synthesise).parameters
                cache[name] = name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
            except (TypeError, ValueError):
                cache[name] = False
        return cache[name]

    def _takes_tone(self) -> bool:  # kept for callers that ask
        return self._takes("tone")

    def pace_ratio(self, lane: str = "") -> float:
        """How many seconds the engine renders per second it speaks, for
        this lane: 0 when unknown or faster than real time."""
        own = getattr(self._inner, "pace_ratio", None)
        if not callable(own):
            return 0.0
        try:
            import inspect

            ratio = own(lane) if inspect.signature(own).parameters else own()
            return float(ratio or 0.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def chunk_timeout(self, request: TtsRequest) -> float:
        """How long a player should wait for one piece from this engine.

        `hold_seconds` already knows the shape of this: rendering time
        is `pace_ratio` times speaking time. A piece takes about that
        long to make, so waiting less than it guarantees silence --
        which is exactly what happened to MisoTTS at a flat 20 s.

        0 for an engine that keeps up: the caller keeps its own floor,
        and the guard that stops a mute Sim is untouched for the fast
        lane.
        """
        ratio = self.pace_ratio(request.lane)
        if ratio <= 1.15:
            return 0.0
        longest = max((len(text) for text, _pause in request.pieces), default=0) / CHARS_PER_SECOND
        return min(MAX_CHUNK_WAIT_S, ratio * longest * CHUNK_WAIT_MARGIN)

    def hold_seconds(self, request: TtsRequest) -> float:
        """How much audio to have in hand before the first piece plays,
        so a slower-than-real-time engine never leaves a gap mid-reply:
        the render time of the rest, less the time the rest takes to
        say, capped. 0 for an engine that keeps up."""
        ratio = self.pace_ratio(request.lane)
        if ratio <= 1.15:
            return 0.0
        estimate = sum(len(text) for text, _pause in request.pieces) / CHARS_PER_SECOND
        return min(MAX_HOLD_S, (ratio - 1.0) * estimate)

    async def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            await close()

    async def warmup(self) -> float:
        """Load the model by speaking one short phrase into nothing, so
        the first real reply does not pay for it. Returns the seconds it
        took; 0.0 when already warm."""
        if self.warm:
            return 0.0
        started = time.monotonic()
        own = getattr(self._inner, "warmup", None)
        if callable(own):
            await own()
        else:
            await self._inner.synthesise("Okay.", speed=1.0)
        self.warmup_seconds = time.monotonic() - started
        self.warm = True
        return self.warmup_seconds

    fell_back: tuple[str, str] | None = None   # (voice asked for, why) when the default voice stood in
    last_error: str = ""                       # why the last stream ended early, if it did
    last_hold_s: float = 0.0                   # audio banked before the last reply's first piece played

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

    async def _synthesise_or_fall_back(self, text: str, request: TtsRequest):
        """One piece, or the same piece in the engine's own default voice
        when the requested one fails, or None when nothing can be made
        of it. An exception here used to escape the producer task as
        "Unhandled exception in event loop" (the creator, 2026-09-12,
        after `voice set tts_voice af_bellae`, a voice that does not
        exist); the reply then showed on screen and was never heard."""
        lane = getattr(request, "lane", "")
        try:
            return await self._synth(text, voice=request.voice, speed=request.speed, tone=request.tone, lane=lane)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- the engine's failure, whatever it is
            first = exc
        if request.voice:
            try:
                audio = await self._synth(text, voice="", speed=request.speed, tone=request.tone, lane=lane)
                self.fell_back = (request.voice, f"{first}")
                return audio
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                first = exc
        self.last_error = f"{first}"
        return None

    async def synthesise_stream(self, request: TtsRequest):
        """Yield `AudioChunk`s for `request.pieces`, in order, as each is
        synthesised; `final` marks the last. A piece the engine could
        not make in the requested voice is made in its default voice
        (`fell_back` says so); a piece it could not make at all ends
        the stream and `last_error` says why -- never an exception out
        of the producer."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._lookahead)
        self._cancelled.discard(request.request_id)
        self.fell_back = None
        self.last_error = ""

        async def _produce() -> None:
            cancelled = False
            try:
                async for seq, text, pause_ms, last in _pieces_of(request):
                    if request.request_id in self._cancelled:
                        break
                    if not text and last:
                        # The end of a live reply: nothing more to say.
                        rate = getattr(self._inner, "sample_rate", 24_000) or 24_000
                        await queue.put(AudioChunk(pcm=silence(20, rate), sample_rate=rate,
                                                   request_id=request.request_id, seq=seq, final=True, text="",
                                                   pause_ms=0))
                        continue
                    audio = await self._synthesise_or_fall_back(text, request)
                    if audio is None:
                        break
                    if request.request_id in self._cancelled:
                        break
                    self.last_engine = getattr(self._inner, "last_engine", None) or getattr(self._inner, "name", "")
                    pcm = levelled(audio.pcm) if self._level else audio.pcm
                    pcm = edged(pcm, audio.sample_rate)
                    if getattr(request, "gain", 1.0) != 1.0:
                        from ..delivery import apply_gain

                        pcm = apply_gain(pcm, request.gain)
                    if pause_ms > 0 and not last:
                        pcm += silence(pause_ms, audio.sample_rate)
                    await queue.put(AudioChunk(pcm=pcm, sample_rate=audio.sample_rate, request_id=request.request_id,
                                               seq=seq, final=last, text=text, pause_ms=pause_ms))
            except asyncio.CancelledError:
                cancelled = True
                raise
            except Exception as exc:  # noqa: BLE001 -- levelling, silence, anything: the stream ends, nothing escapes
                self.last_error = f"{exc}"
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
        hold = self.hold_seconds(request)
        self.last_hold_s = hold
        try:
            if hold > 0:
                # A slow engine: gather enough of the reply that the rest
                # renders while this plays, then let it all go at once.
                held: list = []
                banked = 0.0
                ended = False
                while banked < hold:
                    item = await queue.get()
                    if item is _SENTINEL:
                        ended = True
                        break
                    held.append(item)
                    banked += len(item.pcm) / (SAMPLE_WIDTH * item.sample_rate)
                    if item.final:
                        break
                for item in held:
                    yield item
                if ended:
                    return
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


__all__ = ["CHARS_PER_SECOND", "EDGE_MS", "MAX_HOLD_S", "StreamingSynthesiser", "TARGET_RMS", "edged", "levelled", "silence"]


async def _pieces_of(request):
    """`(seq, text, pause_ms, last)` for every piece of a request: its
    fixed `pieces`, then -- for a reply still being written -- each piece
    from `request.live` as it arrives. A live piece goes at once (holding it
    to learn whether it is the last would hold the first sentence until the
    second exists, which is the delay streaming is for); the end of a live
    reply is marked by an empty final piece, played as a moment of silence."""
    pieces = list(request.pieces)
    live = getattr(request, "live", None)
    if live is None:
        for seq, (text, pause_ms) in enumerate(pieces):
            yield seq, text, pause_ms, seq == len(pieces) - 1
        return
    seq = 0
    for text, pause_ms in pieces:
        yield seq, text, pause_ms, False
        seq += 1
    while True:
        item = await live.get()
        if item is None:
            yield seq, "", 0, True
            return
        yield seq, item[0], item[1], False
        seq += 1
