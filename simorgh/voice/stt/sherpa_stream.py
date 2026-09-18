"""Streaming recognition, word by word (sherpa-onnx).

Whisper decodes an utterance, not a stream. On this machine a decode
costs 2-3.5 s whatever the length -- it pads every input to its 30 s
window -- so a turn got one provisional reading and then a *second*
full decode once the person stopped (measured 2026-09-17 over 1120
turns: `stt` median 2.23 s, one partial per turn).

A streaming transducer decodes each chunk as it arrives and revises
what it has, so the sentence assembles while it is being spoken -- the
creator, having watched it elsewhere: "they are recognizing my voice
word by word and gradually building the sentence ... they may correct
the sentence and heard word mid way". Measured here on the same clip
whisper needed 2 s for: 6.29 s of speech decoded in 0.20 s, 0.03x real
time, punctuation included.

The model is zh-en and this house speaks en,fa, so this engine is
never what `auto` picks: `voice set stt sherpa` chooses it
deliberately, and whisper stays for Farsi.
"""

from __future__ import annotations

import array
import asyncio
import math
from pathlib import Path

from ..api import SAMPLE_RATE, Audio, TranscriptEvent, Utterance, Word

#: Unpacked beside the speaker model in `model_dir`. int8, 480 ms chunks,
#: with punctuation -- the transcript the model reads is better formed.
STREAM_MODEL = "sherpa-onnx-x-asr-480ms-streaming-zipformer-transducer-zh-en-punct-int8-2026-06-05"
STREAM_MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
                    + STREAM_MODEL + ".tar.bz2")
#: The pieces `OnlineRecognizer.from_transducer` needs, as the archive names them.
_FILES = ("encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt", "bpe.model")


def model_dir_for(config, *, repo_root=None) -> Path:
    base = Path(getattr(config, "model_dir", "workspace/voice/models"))
    if repo_root is not None and not base.is_absolute():
        base = Path(repo_root) / base
    # `base / ""` is `base`, and a Path is always truthy: the obvious
    # one-liner returned the parent folder and found no model in it.
    named = str(getattr(config, "stt_stream_model", "") or "").strip()
    return base / (named or STREAM_MODEL)


def _floats(pcm: bytes) -> list[float]:
    """Little-endian int16 bytes to the floats sherpa wants."""
    if len(pcm) % 2:
        pcm = pcm[:-1]
    samples = array.array("h")
    samples.frombytes(pcm)
    return [x / 32768.0 for x in samples]


def timed_words(tokens, timestamps) -> tuple:
    """BPE pieces into timed words, for voice/diarize.py.

    sherpa's own `words` comes back empty for this model -- it is a
    subword model -- but every token carries a timestamp, and a piece
    that opens with a space starts a new word. A word ends where the
    next one starts; the last ends at its own last piece.
    """
    out: list[Word] = []
    text, start, last = "", 0.0, 0.0
    for token, at in zip(list(tokens or ()), list(timestamps or ())):
        at = float(at)
        if token.startswith(" ") and text:
            out.append(Word(text, start, at))
            text, start = token.strip(), at
        else:
            if not text:
                start = at
            text += token.strip() if not text else token
        last = at
    if text:
        out.append(Word(text, start, max(last, start)))
    return tuple(out)


def confidence_of(ys_probs) -> float:
    """Log-probabilities folded to 0..1, as faster_whisper.py does.

    whisper_server reports a flat 1.0 and always has, so a morning of
    mangled transcripts looked exactly like a clean one (2026-09-17:
    24 turns, confidence 1.00 every one, "Go on level the cold one").
    """
    probs = [math.exp(float(p)) for p in (ys_probs or ())]
    if not probs:
        return 1.0
    return max(0.0, min(1.0, sum(probs) / len(probs)))


class SherpaStreamRecogniser:
    """A `SpeechToTextProvider` that streams: it needs no wrapping by
    `IncrementalRecogniser`, and must not get any -- that one re-decodes
    the whole buffer over and over, which is the cost this engine exists
    to remove."""

    name = "sherpa"
    streaming = True        # session.py asks for this before wrapping

    def __init__(self, config, *, repo_root=None, threads: int = 2) -> None:
        try:
            import sherpa_onnx  # type: ignore
        except ImportError as exc:
            raise ImportError("sherpa-onnx is not installed (pip install sherpa-onnx)") from exc
        folder = model_dir_for(config, repo_root=repo_root)
        missing = [f for f in _FILES if not (folder / f).is_file()]
        if missing:
            raise ImportError(
                f"no streaming model at {folder} (missing {', '.join(missing)}) -- "
                f"curl -L {STREAM_MODEL_URL} | tar -xj -C {folder.parent}")
        self._folder = folder
        self._recogniser = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(folder / "tokens.txt"), encoder=str(folder / "encoder.int8.onnx"),
            decoder=str(folder / "decoder.onnx"), joiner=str(folder / "joiner.int8.onnx"),
            num_threads=int(threads), enable_endpoint_detection=True,
            modeling_unit="cjkchar+bpe", bpe_vocab=str(folder / "bpe.model"))
        self.problems: list[str] = []
        self.last_took_s = 0.0
        self.name = f"sherpa:{folder.name.split('-streaming-')[0].replace('sherpa-onnx-', '')}"

    async def warmup(self) -> float:
        return 0.0      # the model is loaded in __init__, like faster-whisper's

    async def stop(self) -> None:
        return None

    def _drain(self, stream) -> None:
        while self._recogniser.is_ready(stream):
            self._recogniser.decode_stream(stream)

    async def transcribe(self, audio: Audio, *, language: str = "") -> Utterance:
        """One whole utterance, for callers that are not streaming
        (`voice test`, health). The streaming path is `start_stream`."""
        stream = self._recogniser.create_stream()
        stream.accept_waveform(audio.sample_rate, _floats(audio.pcm))
        stream.input_finished()
        await asyncio.to_thread(self._drain, stream)
        result = self._recogniser.get_result_all(stream)
        return Utterance(text=(result.text or "").strip(), confidence=confidence_of(result.ys_probs),
                         seconds=audio.seconds, engine=self.name, language="",
                         words=timed_words(result.tokens, result.timestamps))

    async def start_stream(self, frames, *, turn_id: int, language: str = ""):
        """Every chunk decoded as it lands: a `partial` whenever the
        words change, then one `final` carrying the whole turn's audio --
        speaker identification reads that PCM, and a turn without it is
        a turn nobody can be recognised in."""
        stream = self._recogniser.create_stream()
        buffer = bytearray()
        said = ""
        async for frame in frames:
            buffer += frame
            stream.accept_waveform(SAMPLE_RATE, _floats(frame))
            await asyncio.to_thread(self._drain, stream)
            text = (self._recogniser.get_result(stream) or "").strip()
            if text and text != said:
                said = text
                yield TranscriptEvent("partial", text, turn_id, confidence=1.0, language="",
                                      audio_seconds=len(buffer) / (2 * SAMPLE_RATE), engine=self.name)
        stream.input_finished()
        await asyncio.to_thread(self._drain, stream)
        result = self._recogniser.get_result_all(stream)
        audio = Audio(bytes(buffer))
        yield TranscriptEvent("final", (result.text or "").strip(), turn_id,
                              confidence=confidence_of(result.ys_probs), language="",
                              audio_seconds=audio.seconds, engine=self.name,
                              words=timed_words(result.tokens, result.timestamps), audio=bytes(buffer))


__all__ = ["STREAM_MODEL", "STREAM_MODEL_URL", "SherpaStreamRecogniser", "confidence_of", "timed_words"]
