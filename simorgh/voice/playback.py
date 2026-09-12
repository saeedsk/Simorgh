"""Interruptible streaming playback over any `Speaker`.

Chunks arrive as they are synthesised and play back to back. When the
next chunk is already waiting it is joined onto the one about to play,
so a speaker that opens a process per call (`afplay`) still plays a
whole run of ready chunks gaplessly; only a chunk that is not ready yet
costs a seam, and that is counted as an underrun. `stop()` cuts the
current chunk short and drops the rest. A chunk from any request but
the current one is dropped on sight: audio from an old turn can never
play in a new one.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from .api import Audio, AudioChunk, PlaybackState


@dataclass
class PlaybackReport:
    request_id: str
    started_at: float = 0.0        # monotonic, first audio out
    finished_at: float = 0.0
    first_audio_s: float = -1.0    # from `play_stream` entry to the first chunk playing
    chunks: int = 0
    seconds: float = 0.0
    interrupted: bool = False
    underruns: int = 0
    dropped_stale: int = 0
    states: list[PlaybackState] = field(default_factory=list)


class StreamingPlayer:
    def __init__(self, speaker, *, on_state=None) -> None:
        self._speaker = speaker
        self._on_state = on_state
        self._current: str = ""
        self._stop = False
        self._playing: asyncio.Task | None = None
        self.last_report: PlaybackReport | None = None

    @property
    def playing(self) -> bool:
        return self._playing is not None and not self._playing.done()

    @property
    def current_request(self) -> str:
        return self._current

    async def _emit(self, report: PlaybackReport, state: str, seq: int = -1) -> None:
        event = PlaybackState(state=state, request_id=report.request_id, seq=seq)
        report.states.append(event)
        if self._on_state is not None:
            result = self._on_state(event)
            if asyncio.iscoroutine(result):
                await result

    async def play_stream(self, chunks, *, request_id: str, on_first_audio=None,
                          on_chunk=None) -> PlaybackReport:
        """Play `chunks` (an async iterable of `AudioChunk`) for
        `request_id` until they end or `stop()` is called."""
        report = PlaybackReport(request_id=request_id)
        self.last_report = report
        self._current = request_id
        self._stop = False
        entered = time.monotonic()
        queue: asyncio.Queue = asyncio.Queue()
        done = object()

        async def _pull() -> None:
            try:
                async for chunk in chunks:
                    if self._stop:
                        break
                    if chunk.request_id != request_id:
                        report.dropped_stale += 1
                        continue
                    await queue.put(chunk)
            finally:
                await queue.put(done)

        puller = asyncio.create_task(_pull())
        started = False
        try:
            while not self._stop:
                first = await queue.get()
                if first is done:
                    break
                run = [first]
                while not queue.empty():
                    nxt = queue.get_nowait()
                    if nxt is done:
                        await queue.put(done)
                        break
                    run.append(nxt)
                if started and len(run) == 1 and queue.empty() and not first.final:
                    # We had nothing ready when the last run ended, and
                    # nothing is ready behind this one: the seam is audible.
                    report.underruns += 1
                pcm = b"".join(c.pcm for c in run)
                audio = Audio(pcm=pcm, sample_rate=run[0].sample_rate)
                if not started:
                    started = True
                    report.started_at = time.monotonic()
                    report.first_audio_s = report.started_at - entered
                    await self._emit(report, "started", run[0].seq)
                    if on_first_audio is not None:
                        result = on_first_audio(report.first_audio_s)
                        if asyncio.iscoroutine(result):
                            await result
                if on_chunk is not None:
                    for c in run:
                        result = on_chunk(c)
                        if asyncio.iscoroutine(result):
                            await result
                self._playing = asyncio.create_task(self._speaker.play(audio))
                try:
                    await self._playing
                finally:
                    self._playing = None
                report.chunks += len(run)
                report.seconds += audio.seconds
                await self._emit(report, "chunk", run[-1].seq)
        finally:
            if not puller.done():
                puller.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await puller
            report.finished_at = time.monotonic()
            report.interrupted = self._stop
            await self._emit(report, "stopped" if self._stop else "finished")
            self._current = ""
        return report

    async def stop(self) -> None:
        """Cut playback now. `play_stream` returns once the speaker has."""
        self._stop = True
        stopper = getattr(self._speaker, "stop", None)
        if stopper is not None:
            await stopper()


__all__ = ["PlaybackReport", "StreamingPlayer"]
