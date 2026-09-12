"""wake -> VAD -> STT -> Sim -> TTS -> play, for one laptop.

The pipeline decides nothing. A spoken utterance becomes
`percept.text.received{channel: "voice"}` and rides the same
Orchestration/Cognition path as typed text -- one brain, one Guardian,
one ledger -- and whatever comes back as the turn's result is what gets
spoken. Every stage announces itself on the bus (`voice.listening`,
`voice.transcript`, `voice.spoken`) so the TUI, a satellite's LED or a
test can watch it without touching audio.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
import re
import time
import uuid
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event

from .api import Audio, AudioChunk, TtsRequest, Utterance, VoiceTurn
from .audio import write_wav
from .config import Config
from .vad import BargeInEndpointer, CompositeDetector, EnergyDetector, Endpointer

TURNS_STREAM = "voice:turns"

#: What Sim says when the answer is not back in time. Spoken, because a
#: silent failure is the one thing a voice interface must never do.
STILL_THINKING = "I'm still working on that. I'll tell you when I have it."
NOT_SURE = "I'm not sure I heard that right. Did you say: {text}?"

_MARKDOWN = (
    (re.compile(r"```.*?```", re.S), " "),          # code blocks: not for speaking
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),
    (re.compile(r"(?m)^\s*#+\s*"), ""),
    (re.compile(r"(?m)^\s*[-*]\s+"), ""),
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),
    (re.compile(r"[ \t]+"), " "),
)


def _aec_available() -> bool:
    from .aec import available

    return available()[0]


_WORD = re.compile(r"[a-z0-9']+")


def is_echo(heard: str, said: str, *, min_words: int = 4, overlap: float = 0.6) -> bool:
    """Whether `heard` is Sim's own reply coming back through the mic.

    The energy gate in `vad.BargeInEndpointer` is the first defence and
    it is only a level: a loud enough speaker beats it. This is the
    second, and it needs no acoustics -- Sim knows what it just said,
    and a person does not repeat Sim's reply back word for word. Most of
    the heard words appearing in the said text, in a heard utterance of
    a few words or more, is an echo. The creator's screen, 2026-09-11:
    Sim's whole benchmark reply came back as the next "you:" and Sim
    answered "You're echoing my own question back at me again."
    """
    heard_words = _WORD.findall((heard or "").lower())
    if len(heard_words) < min_words:
        return False
    said_words = set(_WORD.findall((said or "").lower()))
    if not said_words:
        return False
    hits = sum(1 for w in heard_words if w in said_words)
    return hits / len(heard_words) >= overlap


def spoken_form(text: str) -> str:
    """Markdown out, sentences in. A synthesiser reading `**bold**` and
    bullet dashes aloud is the fastest way to sound like a machine."""
    out = text or ""
    for pattern, repl in _MARKDOWN:
        out = pattern.sub(repl, out)
    lines = [line.strip() for line in out.splitlines()]
    return "\n".join(line for line in lines if line).strip()


class Pipeline:
    def __init__(self, *, bus, clock, logger, ledger, config: Config, microphone, speaker, recogniser,
                 synthesiser, detector_factory, repo_root: Path | None = None) -> None:
        self._bus = bus
        self._clock = clock
        self._logger = logger
        self._ledger = ledger
        self._config = config
        self._mic = microphone
        self._speaker = speaker
        self._stt = recogniser
        self._tts = synthesiser
        self._detector_factory = detector_factory
        self._repo_root = repo_root or Path(".")
        self._pending: dict[str, asyncio.Future] = {}
        self._subs: list = []
        # One voice at a time, whoever asks: the session's replies, the
        # short acknowledgement, `voice test`, a typed turn's reply.
        # Two players at once is two voices at once -- the creator
        # heard exactly that (2026-09-11) -- and a voice the session
        # did not start is a voice the microphone will hear as a person.
        self.speech_lock = asyncio.Lock()
        # Session ids this pipeline asked Sim about, recent first. A reply
        # to one of these is the session's own to speak; the service's
        # speak-every-reply path must leave it alone -- and cannot rely on
        # `_pending`, which is emptied the instant the reply arrives.
        self._voice_sessions: deque[str] = deque(maxlen=200)
        self.turns = 0
        self.pending_audio: Audio | None = None
        self.last_heard = ""
        self.last_said = ""
        self.speaking = False
        self.listening = False

    # ------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        # The answer to a chat turn arrives as `turn.completed{session_id,
        # text}` -- exactly what the REPL waits for (`interface/service.py::
        # _on_turn_completed`). The task events are the fallback for a
        # turn that ends without one: a chat task's id is its session id.
        self._subs.append(await self._bus.subscribe(topics.TURN_COMPLETED, self._on_turn_completed))
        for topic in (topics.TASK_FAILED, topics.TASK_BLOCKED):
            self._subs.append(await self._bus.subscribe(topic, self._on_task_event))

    async def _on_turn_completed(self, message) -> None:
        payload = message.payload
        fut = self._pending.get(str(payload.get("session_id") or ""))
        if fut is not None and not fut.done():
            fut.set_result(str(payload.get("text") or ""))

    async def stop(self) -> None:
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs = []
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def _on_task_event(self, message) -> None:
        """A chat turn's task id IS its session id (`interface/service.py`
        does the same), so the reply is the terminal task event."""
        payload = message.payload
        fut = self._pending.get(str(payload.get("task_id") or ""))
        if fut is None or fut.done():
            return
        reason = str(payload.get("reason") or payload.get("note") or "it did not work")
        fut.set_result(f"Sorry, I couldn't do that: {reason}")

    # ------------------------------------------------------------- one turn
    async def listen_once(self, *, max_seconds: float | None = None, respond: bool = True,
                          speaker_name: str = "", pending: Audio | None = None) -> tuple[Utterance | None, str]:
        """Capture one utterance, and unless `respond=False`, ask Sim and
        speak the answer. Returns `(utterance, what was said)`.

        `pending` is audio already captured -- the words that interrupted
        the previous reply (`speak`) -- and stands in for the capture."""
        self.pending_audio = None
        if pending is not None:
            audio = pending
            heard_speech = True
        else:
            endpointer = Endpointer(self._detector_factory(), silence_ms=self._config.endpoint_silence_ms,
                                    max_seconds=max_seconds or self._config.max_utterance_s)
            await self._announce("listening")
            self.listening = True
            try:
                audio = await self._mic.capture(max_seconds=max_seconds or self._config.max_utterance_s,
                                                endpointer=endpointer)
            finally:
                self.listening = False
                await self._announce("idle")
            heard_speech = endpointer.heard_speech
        if not heard_speech and audio.seconds < 0.5:
            return None, ""
        if self._config.keep_audio:
            self._keep(audio)
        heard_at = self._clock.now()
        utterance = await self._stt.transcribe(audio, language=self._config.stt_language)
        session_id = str(uuid.uuid4())
        await self._publish(topics.VOICE_TRANSCRIPT, {
            "text": utterance.text, "confidence": utterance.confidence, "seconds": utterance.seconds,
            "engine": utterance.engine, "device": self._config.device, "session_id": session_id,
        })
        if not utterance.text.strip():
            return utterance, ""
        if self.last_said and is_echo(utterance.text, self.last_said):
            # Sim's own voice, back through the microphone. Not a turn.
            await self._publish(topics.VOICE_TRANSCRIPT, {
                "text": utterance.text, "confidence": utterance.confidence, "seconds": utterance.seconds,
                "engine": utterance.engine, "device": self._config.device, "session_id": session_id, "echo": True,
            })
            if self._logger is not None:
                self._logger.info("voice.echo_ignored", words=len(utterance.text.split()))
            return utterance, ""
        self.last_heard = utterance.text
        if not respond:
            return utterance, ""
        if utterance.confidence < self._config.min_confidence:
            # The never-guess rule: ask, do not act.
            said = NOT_SURE.format(text=utterance.text)
            await self.speak(said, session_id=session_id)
            return utterance, said
        reply = await self.ask(utterance.text, session_id=session_id, speaker_name=speaker_name,
                               confidence=utterance.confidence)
        said = await self.speak(reply, session_id=session_id)
        self.turns += 1
        await self._record(VoiceTurn(
            session_id=session_id, device=self._config.device, speaker=speaker_name, heard=utterance.text,
            confidence=utterance.confidence, said=said, heard_at=heard_at, answered_at=self._clock.now(),
            engine_stt=utterance.engine,
            engine_tts=getattr(self._tts, "last_engine", None) or getattr(self._tts, "name", ""),
        ))
        return utterance, said

    async def ask(self, text: str, *, session_id: str | None = None, speaker_name: str = "",
                  confidence: float = 1.0) -> str:
        """Hand the words to Sim exactly as the REPL would, and wait."""
        session_id = session_id or str(uuid.uuid4())
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[session_id] = fut
        self._voice_sessions.append(session_id)
        payload = {"channel": "voice", "text": text, "session_id": session_id, "device": self._config.device,
                   "confidence": confidence}
        if speaker_name:
            payload["speaker"] = speaker_name
        await self._publish(topics.PERCEPT_TEXT_RECEIVED, payload)
        try:
            return await asyncio.wait_for(fut, timeout=self._config.reply_timeout_s)
        except asyncio.TimeoutError:
            if self._logger is not None:
                self._logger.warning("voice.reply_timeout", session_id=session_id, seconds=self._config.reply_timeout_s)
            return STILL_THINKING
        finally:
            self._pending.pop(session_id, None)

    async def speak(self, text: str, *, session_id: str | None = None, voice: str = "") -> str:
        """Say `text` aloud. Returns what was actually spoken (planned for
        the ear: markdown, links and code out, the answer in pieces); an
        empty reply is spoken as a short honest line.

        Spoken piece by piece as each is synthesised, so the first
        sentence plays while the rest is still being made. With
        `barge_in` on, the microphone stays open while Sim speaks. The
        creator, 2026-09-10: "I want sim to stop talking as soon as I
        start talking." `barge_in_speech_ms` of a person's speech --
        measured over the level the mic hears of Sim's own voice --
        stops playback at once, and the interrupting words are kept as
        the start of the next turn (`self.pending_audio`), not thrown
        away with the echo."""
        from .planner import SpokenResponsePlanner
        from .tts.streaming import StreamingSynthesiser

        plan = SpokenResponsePlanner(max_sentences=self._config.max_spoken_sentences,
                                     connectors=False).plan(text)
        said = plan.text
        request_id = session_id or str(uuid.uuid4())
        if not isinstance(self._tts, StreamingSynthesiser):
            self._tts = StreamingSynthesiser(self._tts, lookahead=self._config.tts_lookahead)
        request = TtsRequest(request_id=request_id, pieces=tuple((c.text, c.pause_ms) for c in plan.chunks),
                             voice=voice or self._config.tts_voice, speed=self._config.tts_speed)
        async with self.speech_lock:
            self.speaking = True
            self.pending_audio = None
            await self._announce("speaking")
            try:
                report = await self._play_stream_interruptibly(self._tts.synthesise_stream(request), request_id)
            finally:
                self.speaking = False
                await self._announce("idle")
        self.last_said = said
        await self._publish(topics.VOICE_SPOKEN, {
            "text": said, "seconds": report.seconds,
            # The engine that spoke THIS reply: a polyglot synthesiser
            # picks per language, and `name` is only its primary.
            "engine": getattr(self._tts, "last_engine", None) or getattr(self._tts, "name", ""),
            "device": self._config.device, "interrupted": report.interrupted,
            "first_audio_s": round(report.first_audio_s, 3), "underruns": report.underruns,
            **({"session_id": session_id} if session_id else {}),
        })
        return said

    def is_voice_session(self, session_id: str) -> bool:
        return session_id in self._voice_sessions

    async def _play_interruptibly(self, audio: Audio) -> bool:
        """Play one `Audio` while listening; True if a person cut in. The
        streaming path below is the real one; this wraps a whole
        utterance as a single chunk for callers that have one."""
        async def _one():
            yield AudioChunk(pcm=audio.pcm, sample_rate=audio.sample_rate, request_id="one", seq=0, final=True)

        report = await self._play_stream_interruptibly(_one(), "one", expected_seconds=audio.seconds)
        return report.interrupted

    async def _play_stream_interruptibly(self, chunks, request_id: str, *, expected_seconds: float = 0.0):
        """Play a stream of chunks; with `barge_in` and a microphone, a
        person cutting in stops the player. The interrupting utterance,
        captured to its end, is left in `self.pending_audio`."""
        from .playback import StreamingPlayer

        player = StreamingPlayer(self._speaker)
        if not (self._config.barge_in and self._mic is not None):
            return await player.play_stream(chunks, request_id=request_id)

        loop = asyncio.get_running_loop()

        def _cut_in() -> None:
            # Called from wherever the endpointer runs. With the capture
            # paths in `audio.py` that is this loop; the first version
            # ran it on PortAudio's audio thread and died with "no
            # running event loop" the first time the creator spoke over
            # Sim (2026-09-10). Thread-safe either way now.
            loop.call_soon_threadsafe(lambda: loop.create_task(player.stop()))

        voice = self._detector_factory()
        reference: list = []
        if self._config.aec and _aec_available():
            # Decide on the residual after Sim's own voice is cancelled
            # out. The reference is what is playing, appended chunk by
            # chunk as it plays, brought to the microphone's rate; a
            # frame past the end of playback is silence, which is right
            # -- once Sim stops, the residual is the person, uncancelled.
            from .aec import EchoCanceller, EchoCancellingDetector

            canceller = EchoCanceller(taps=self._config.aec_taps, mu=self._config.aec_mu)
            detector = EchoCancellingDetector(voice, canceller,
                                              residual_threshold=self._config.aec_residual_threshold)
        elif hasattr(voice, "raise_floor"):
            detector = voice
        else:
            # A voice detector (Silero) alone would fire on Sim's own
            # voice; pair it with a level gate calibrated to that echo.
            detector = CompositeDetector(voice, EnergyDetector(self._config.vad_threshold))
        horizon = (expected_seconds or 120.0) + self._config.max_utterance_s
        endpointer = BargeInEndpointer(
            detector, silence_ms=self._config.endpoint_silence_ms, max_seconds=horizon,
            speech_ms=self._config.barge_in_speech_ms, on_barge_in=_cut_in,
            calibrate_frames=max(1, self._config.barge_in_calibrate_ms // 30), ratio=self._config.barge_in_ratio,
            reference=reference,
        )

        def _feed_reference(chunk: AudioChunk) -> None:
            from .audio import FRAME_BYTES
            from .resample import to_mic_rate

            pcm = to_mic_rate(chunk.pcm, chunk.sample_rate)
            reference.extend(pcm[i:i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES))

        # The reference must be in step with the microphone from the
        # capture's first frame: a reference that starts a few frames
        # late is a delay the canceller's taps cannot reach, and the
        # echo comes through uncancelled as a person. So the first
        # piece is synthesised BEFORE the capture opens, and every later
        # piece joins the reference as it is produced, ahead of playing.
        feed = _feed_reference if (self._config.aec and _aec_available()) else (lambda chunk: None)
        iterator = chunks.__aiter__()
        try:
            first = await iterator.__anext__()
        except StopAsyncIteration:
            first = None
        if first is not None:
            feed(first)

        async def _rest():
            if first is not None:
                yield first
            async for chunk in iterator:
                feed(chunk)
                yield chunk

        capture = asyncio.create_task(self._mic.capture(max_seconds=horizon, endpointer=endpointer))
        try:
            report = await player.play_stream(_rest(), request_id=request_id)
        finally:
            if not endpointer.barged:
                capture.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await capture
        if not endpointer.barged:
            return report
        try:
            self.pending_audio = await capture
        except Exception as exc:  # noqa: BLE001 -- the interruption stands even if its tail was lost
            if self._logger is not None:
                self._logger.warning("voice.barge_in_capture_failed", error=repr(exc))
        return report

    async def run_loop(self, stop: asyncio.Event) -> None:
        """`voice on`: listen, answer, listen again, until told to stop.
        Without a wake word every capture is open; an empty one (nobody
        spoke for `max_utterance_s`) simply comes round again."""
        pending: Audio | None = None
        while not stop.is_set():
            try:
                utterance, _said = await self.listen_once(pending=pending)
                pending = self.pending_audio  # the words that cut the reply short, if any
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 -- one bad turn must not end the session
                if self._logger is not None:
                    self._logger.warning("voice.turn_failed", error=repr(exc))
                await asyncio.sleep(1.0)
                continue
            if pending is not None:
                continue  # answer the interruption before listening afresh
            if utterance is None or not utterance.text.strip():
                # Nothing heard. A real microphone spent `max_utterance_s`
                # finding that out; a fake one answers at once, and a loop
                # that never yields between empty captures starves the
                # rest of the process.
                await asyncio.sleep(0.05)

    # ------------------------------------------------------------- helpers
    async def _announce(self, state: str) -> None:
        await self._publish(topics.VOICE_LISTENING, {"state": state, "device": self._config.device})

    async def _publish(self, topic: str, payload: dict) -> None:
        await self._bus.publish(self._bus.new(topic, payload))

    async def _record(self, turn: VoiceTurn) -> None:
        if not self._config.keep_transcripts or self._ledger is None:
            return
        try:
            await self._ledger.append(TURNS_STREAM, Event(
                stream=TURNS_STREAM, type="turn", ts=turn.answered_at, trace_id=turn.session_id,
                causation_id=None, payload={
                    "session_id": turn.session_id, "device": turn.device, "speaker": turn.speaker,
                    "heard": turn.heard[:4000], "confidence": turn.confidence, "said": turn.said[:4000],
                    "heard_at": turn.heard_at, "answered_at": turn.answered_at,
                    "engine_stt": turn.engine_stt, "engine_tts": turn.engine_tts,
                    **({"metrics": dict(turn.metrics)} if turn.metrics else {}),
                }))
        except Exception as exc:  # noqa: BLE001 -- the turn happened; losing its record is a warning
            if self._logger is not None:
                self._logger.warning("voice.turn_not_recorded", error=repr(exc))

    def _keep(self, audio: Audio) -> None:
        try:
            path = self._repo_root / self._config.audio_dir / f"{int(time.time())}.wav"
            write_wav(path, audio)
        except OSError as exc:
            if self._logger is not None:
                self._logger.warning("voice.audio_not_kept", error=repr(exc))


__all__ = ["NOT_SURE", "Pipeline", "STILL_THINKING", "TURNS_STREAM", "spoken_form"]
