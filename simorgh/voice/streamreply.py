"""Speak a reply while it is still being written (stage 3 item 4).

`SentenceStream` turns `session.delta` text into whole sentences on a queue
the synthesiser reads (`TtsRequest.live`), so the first sentence is being
said while the model writes the rest. It keeps the planner's promises for a
spoken reply: at most `max_sentences`, then "there's more on screen"; a
leading tone tag is taken off, not read out. A `reset` (the reply turned
out to be a tool call, or a failover started again) drops what was not yet
said and starts collecting afresh, so "Let me check." and, later, the
answer come out as one utterance. `finish(final)` queues whatever of the
final reply was not streamed, then ends the stream.
"""

from __future__ import annotations

import asyncio
import re
from typing import Callable

from simorgh.contracts.tone import split_tone

from .planner import MORE_ON_SCREEN

_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+")
#: A sentence shorter than this waits for the next one ("Dr." or "1.").
MIN_SENTENCE = 12
PAUSE_MS = 180


class SentenceStream:
    def __init__(self, *, max_sentences: int = 3, on_sentence: Callable[[str], None] | None = None,
                 language: str = "en", transform: Callable[[str], str] | None = None) -> None:
        # `transform`: what is queued for the synthesiser (the planner's
        # pronunciations); `spoken` and `on_sentence` keep the written text.
        self._transform = transform or (lambda text: text)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.started = asyncio.Event()      # the first sentence is on the queue
        self._max = max(1, max_sentences)
        self._on_sentence = on_sentence
        self._language = language
        self._buffer = ""
        self._since_reset = ""              # text received since the last reset
        self._queued = 0
        self._capped = False
        self._closed = False
        self.tone = ""
        self.spoken: list[str] = []

    def feed(self, text: str, *, reset: bool = False) -> None:
        if self._closed:
            return
        if reset:
            self._buffer, self._since_reset = "", ""
            return
        self._since_reset += text
        self._buffer += text
        at = 0
        while True:
            match = _SENTENCE_END.search(self._buffer, at)
            if match is None:
                return
            sentence = self._buffer[:match.end()].strip()
            if len(sentence) < MIN_SENTENCE and match.end() < len(self._buffer):
                # "Dr." or "1." on its own: look on to the next sentence end
                # and say the two together.  Putting the short one back at the
                # front of the buffer would match here again for ever (live
                # 2026-09-23: "Okay. The lights..." wedged the whole process).
                at = match.end()
                continue
            self._buffer = self._buffer[match.end():]
            self._put(sentence)
            at = 0

    def _put(self, sentence: str) -> None:
        if not sentence or self._capped:
            return
        if not self.spoken:
            tone, sentence = split_tone(sentence)
            self.tone = self.tone or tone
            if not sentence.strip():
                return
            from simorgh.contracts.settings import is_quiet_reply

            if is_quiet_reply(sentence):
                # "QUIET." streamed as a first sentence is Sim choosing
                # silence, never a word to say aloud.
                return
        if self._queued >= self._max:
            self._capped = True
            self._emit(MORE_ON_SCREEN.get(self._language, MORE_ON_SCREEN["en"]))
            return
        self._queued += 1
        self._emit(sentence)

    def _emit(self, text: str) -> None:
        self.spoken.append(text)
        if self._on_sentence is not None:
            self._on_sentence(text)
        self.queue.put_nowait((self._transform(text), PAUSE_MS))
        self.started.set()

    def finish(self, final: str) -> None:
        """The whole reply is known: say what of it was not streamed, then
        end. The streamed text since the last reset is a prefix of the
        final reply when all went well; if it is not (the answer came from
        a provider that did not stream), the reply is said whole -- unless
        something was already said, which is then left alone rather than
        repeated."""
        if self._closed:
            return
        streamed = self._since_reset
        if final.startswith(streamed):
            rest = self._buffer + final[len(streamed):]
        else:
            rest = "" if self.spoken else final
        self._buffer = ""
        for piece in _SENTENCE_END.split(rest.strip()):
            if piece.strip():
                self._put(piece.strip())
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self.queue.put_nowait(None)

    @property
    def said(self) -> str:
        return " ".join(self.spoken)


__all__ = ["SentenceStream", "MIN_SENTENCE"]
