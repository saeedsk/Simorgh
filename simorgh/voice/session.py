"""The spoken conversation: microphone frames in, speech out, with the
floor changing hands the way it does between people.

    frames -> FrameVad -> TurnManager -> IncrementalRecogniser -> Sim
           -> SpokenResponsePlanner -> StreamingSynthesiser -> StreamingPlayer

Every part is replaceable behind its protocol (`api.py`) and every
decision about whose turn it is lives in `turns.py`; this file only
carries audio and events between them, keeps the clocks, and writes
the diagnostics. It reuses `Pipeline` for what has not changed: how a
question reaches Sim over the bus and how a turn is ledgered.

Timing, measured from the person's last word: `stt` is the wait for
the final transcript, `llm` the wait for Sim, `first_audio` the wait
for the first piece of the reply to play, `interruption` the time from
a person cutting in to the speaker going quiet.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from simorgh.contracts import topics

from .api import SAMPLE_RATE, SAMPLE_WIDTH, Audio, PlaybackState, TtsRequest, VoiceTurn
from .audio import FRAME_BYTES
from .config import Config
from .lang import language_of
from .pipeline import NOT_SURE, Pipeline, is_echo
from .planner import CONNECTORS, Context, SpokenResponsePlanner, choose_connector
from .playback import StreamingPlayer
from .stt.streaming import IncrementalRecogniser
from .tts.streaming import StreamingSynthesiser
from .turns import AGENT_SPEAKING, Actions, LISTENING, Policy, THINKING, TurnManager, USER_SPEAKING
from .vad import CompositeDetector, EnergyDetector, FrameVad, threshold_for

_END = object()
_PREROLL_FRAMES = 20  # 600 ms of audio kept from before speech was noticed


@dataclass
class TurnClock:
    turn_id: int
    speech_start: float = 0.0
    speech_end: float = 0.0
    final_at: float = 0.0
    reply_at: float = 0.0
    first_audio_at: float = 0.0
    interrupted_at: float = 0.0
    stopped_at: float = 0.0
    text: str = ""
    confidence: float = 1.0
    engine_stt: str = ""

    def metrics(self, report=None) -> dict:
        out: dict = {}
        if self.speech_end and self.final_at:
            out["stt"] = round(self.final_at - self.speech_end, 3)
        if self.final_at and self.reply_at:
            out["llm"] = round(self.reply_at - self.final_at, 3)
        if self.reply_at and self.first_audio_at:
            out["first_audio"] = round(self.first_audio_at - self.reply_at, 3)
        if self.speech_end and self.first_audio_at:
            out["response"] = round(self.first_audio_at - self.speech_end, 3)
        if report is not None:
            out["underruns"] = report.underruns
            out["dropped"] = report.dropped_stale
            out["interrupted"] = report.interrupted
            out["chunks"] = report.chunks
            out["spoken_seconds"] = round(report.seconds, 2)
        return out


@dataclass
class SessionStats:
    turns: int = 0
    interruptions: int = 0
    last_metrics: dict = field(default_factory=dict)
    warmup_seconds: float = 0.0
    last_interruption_s: float = -1.0


class VoiceSession:
    def __init__(self, *, pipeline: Pipeline, config: Config, microphone, speaker, recogniser, synthesiser,
                 detector_factory, clock=None, logger=None) -> None:
        self._pipeline = pipeline
        self._config = config
        self._mic = microphone
        self._detector_factory = detector_factory
        self._clock = clock
        self._logger = logger
        self._stt = IncrementalRecogniser(recogniser, partials=config.stt_partials,
                                          partial_every_ms=config.stt_partial_every_ms)
        self._tts = synthesiser if isinstance(synthesiser, StreamingSynthesiser) else StreamingSynthesiser(
            synthesiser, lookahead=config.tts_lookahead)
        self._player = StreamingPlayer(speaker, on_state=self._on_playback_state)
        self._planner = SpokenResponsePlanner(max_sentences=config.max_spoken_sentences, connectors=config.connectors)
        self.turns = TurnManager(Policy(
            end_of_turn_silence_ms=config.endpoint_silence_ms, min_speech_ms=config.min_speech_ms,
            max_turn_ms=config.max_turn_ms, semantic_silence_factor=config.semantic_silence_factor,
            interrupt_on_user_speech=config.barge_in, barge_in_speech_ms=config.barge_in_speech_ms,
        ), auto_listen=config.auto_listen)
        self.stats = SessionStats()
        self.muted = False
        self.partial = ""
        self._clocks: dict[int, TurnClock] = {}
        self._frames: asyncio.Queue | None = None
        self._stt_task: asyncio.Task | None = None
        self._ask_task: asyncio.Task | None = None
        self._speak_task: asyncio.Task | None = None
        self._preroll: deque[bytes] = deque(maxlen=_PREROLL_FRAMES)
        self._reference: deque[bytes] = deque()
        self._echo_rms = 0.0
        self._detector = None
        self._vad: FrameVad | None = None
        self._turns_since_connector = 99
        self._previous_connector = ""
        self._last_user_text = ""
        self._stop: asyncio.Event | None = None
        # Set whenever a candidate turn settles (discarded, or asked), so
        # a reply held for it can try again.
        self._settled = asyncio.Event()
        # Chat sessions still running for turns the person has moved on
        # from: turn id -> the chat's session id, cancelled when a later
        # turn is asked. On the creator's screen (2026-09-11) five such
        # chats ran at once, each exploring the codebase, and the
        # replies came back late, out of order, and stale.
        self._outstanding: dict[int, str] = {}

    # ------------------------------------------------------------- helpers
    @property
    def state(self) -> str:
        return self.turns.state

    def _now(self) -> float:
        return time.monotonic()

    def _log(self, level: str, event: str, **fields) -> None:
        if self._logger is not None:
            getattr(self._logger, level, self._logger.info)(event, **fields)

    async def _announce(self, state: str) -> None:
        await self._pipeline._publish(topics.VOICE_LISTENING, {  # noqa: SLF001 -- the same announcement
            "state": state, "device": self._config.device, "turn": self.turns.turn_id})

    def _build_vad(self) -> FrameVad:
        voice = self._detector_factory()
        threshold = threshold_for(self._config.vad_sensitivity, self._config.vad_threshold)
        if hasattr(voice, "raise_floor"):
            detector = voice
        else:
            detector = CompositeDetector(voice, EnergyDetector(threshold))
        if hasattr(detector, "set_ratio"):
            detector.set_ratio(self._config.barge_in_ratio)
        self._detector = detector
        return FrameVad(detector)

    # ------------------------------------------------------------- the loop
    async def run(self, stop: asyncio.Event) -> None:
        """`voice on`: listen, answer, listen again, until told to stop."""
        self._stop = stop
        self._vad = self._build_vad()
        self.turns.start()
        try:
            self.stats.warmup_seconds = await self._tts.warmup()
        except Exception as exc:  # noqa: BLE001 -- a cold first reply is slower, not fatal
            self._log("warning", "voice.warmup_failed", error=repr(exc))
        await self._announce(self.turns.state)
        stream = self._mic.stream()
        try:
            async for frame in stream:
                if stop.is_set():
                    break
                if self.muted:
                    continue
                await self._on_frame(frame)
        finally:
            await self._teardown()

    async def _teardown(self) -> None:
        for task in (self._stt_task, self._ask_task, self._speak_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        await self._stt.stop()
        if self._player.playing:
            await self._player.stop()
        self.turns.stop()
        await self._announce(self.turns.state)

    async def _on_frame(self, frame: bytes) -> None:
        assert self._vad is not None
        speaking = self.turns.state == AGENT_SPEAKING
        if speaking and self._detector is not None and hasattr(self._detector, "raise_floor"):
            # Sim's own voice at the microphone: the floor a person must
            # clear is its loudest moment so far (vad.BargeInEndpointer).
            rms = self._detector.rms(frame) if hasattr(self._detector, "rms") else 0.0
            self._echo_rms = max(self._echo_rms, rms)
            self._detector.raise_floor(self._echo_rms)
        event = self._vad.process(frame)
        before = self.turns.state
        actions = self.turns.handle_vad(event)
        if self.turns.state in (USER_SPEAKING,) and self._frames is not None:
            self._frames.put_nowait(frame)
        else:
            self._preroll.append(frame)
        for action in actions:
            await self._dispatch(action, frame_time=self._now())
        if before != self.turns.state:
            await self._announce(self.turns.state)

    async def _dispatch(self, action, *, frame_time: float) -> None:
        kind = action.kind
        if kind == Actions.CAPTURE_START:
            clock = TurnClock(turn_id=action.turn_id, speech_start=frame_time)
            self._clocks[action.turn_id] = clock
            self.partial = ""
            self._frames = asyncio.Queue()
            for frame in self._preroll:  # the onset, from before the VAD noticed
                self._frames.put_nowait(frame)
            self._preroll.clear()
            self._stt_task = asyncio.create_task(self._transcribe(action.turn_id, self._frames))
        elif kind == Actions.FINALISE:
            clock = self._clocks.get(action.turn_id)
            if clock is not None:
                clock.speech_end = frame_time
            if self._frames is not None:
                self._frames.put_nowait(_END)
        elif kind == Actions.DISCARD:
            if self._frames is not None:
                self._frames.put_nowait(_END)
            self._clocks.pop(action.turn_id, None)
            if self._stt_task is not None:
                self._stt_task.cancel()
                self._stt_task = None
            await self._stt.stop()
            self._settled.set()
        elif kind == Actions.STOP_PLAYBACK:
            self.stats.interruptions += 1
            clock = self._clocks.get(self.turns.turn_id)
            started = frame_time
            await self._player.stop()
            latency = self._now() - started
            self.stats.last_interruption_s = round(latency, 3)
            for c in self._clocks.values():
                if c.turn_id == self.turns.turn_id - 1 or c.turn_id == self.turns.turn_id:
                    c.interrupted_at = frame_time
                    c.stopped_at = self._now()
            self._log("info", "voice.barge_in", response=action.response_id, stop_s=round(latency, 3))
        elif kind == Actions.CANCEL_TTS:
            await self._tts.cancel(str(action.response_id))
        elif kind == Actions.ASK:
            self._settled.set()
            await self._cancel_outstanding(before=action.turn_id)
            self._ask_task = asyncio.create_task(self._guarded(self._ask_and_speak(action.turn_id, action.text)))
        elif kind == Actions.SPEAK:
            pass  # handled by `_ask_and_speak`, which minted the response
        elif kind == Actions.DROP_REPLY:
            self._log("info", "voice.reply_dropped", turn=action.turn_id, reason=action.reason)

    async def _guarded(self, coro) -> None:
        """A task's exception is nobody's unless somebody looks: a turn
        that fails while answering is logged and the floor handed back,
        not a session frozen in `thinking`."""
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "voice.turn_failed", error=repr(exc))
            if self.turns.state in (THINKING, AGENT_SPEAKING):
                self.turns.state = LISTENING
                await self._announce(self.turns.state)

    async def _cancel_outstanding(self, *, before: int) -> None:
        """Ask the Worker to stop the chats for turns older than
        `before`: their replies would be dropped as stale anyway, and a
        chat mid-investigation was holding the model for the turn the
        person actually wants answered."""
        for turn, session_id in list(self._outstanding.items()):
            if turn < before:
                self._outstanding.pop(turn, None)
                await self._pipeline._publish(topics.TASK_CANCEL, {  # noqa: SLF001
                    "task_id": session_id, "reason": "the person went on to a new turn"})
                self._log("info", "voice.ask_cancelled", turn=turn)

    # ------------------------------------------------------------- hearing
    async def _frames_until_end(self, queue: asyncio.Queue):
        while True:
            frame = await queue.get()
            if frame is _END:
                return
            yield frame

    async def _transcribe(self, turn_id: int, queue: asyncio.Queue) -> None:
        try:
            async for event in self._stt.start_stream(self._frames_until_end(queue), turn_id=turn_id,
                                                      language=self._config.stt_language):
                if event.kind == "partial":
                    self.partial = event.text
                    await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
                        "text": event.text, "partial": True, "turn": turn_id, "confidence": event.confidence,
                        "seconds": event.audio_seconds, "engine": event.engine, "device": self._config.device})
                else:
                    clock = self._clocks.get(turn_id)
                    if clock is not None:
                        clock.final_at = self._now()
                        clock.text = event.text
                        clock.confidence = event.confidence
                        clock.engine_stt = event.engine
                    self.partial = ""
                    if self._config.keep_audio:
                        pass  # the streaming path keeps no raw audio: see the privacy note in the README
                before = self.turns.state
                for action in self.turns.handle_transcript(event):
                    await self._dispatch(action, frame_time=self._now())
                if before != self.turns.state:
                    await self._announce(self.turns.state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- one failed hearing must not end the session
            self._log("warning", "voice.transcribe_failed", error=repr(exc))
            self.turns.state = LISTENING

    # ------------------------------------------------------------- answering
    async def _ask_and_speak(self, turn_id: int, text: str) -> None:
        session_id = str(uuid.uuid4())
        clock = self._clocks.get(turn_id) or TurnClock(turn_id=turn_id)
        await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
            "text": text, "confidence": clock.confidence, "seconds": 0.0, "engine": clock.engine_stt,
            "device": self._config.device, "session_id": session_id, "turn": turn_id})
        if self._pipeline.last_said and is_echo(text, self._pipeline.last_said):
            await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
                "text": text, "confidence": clock.confidence, "seconds": 0.0, "engine": clock.engine_stt,
                "device": self._config.device, "session_id": session_id, "echo": True, "turn": turn_id})
            self.turns.state = LISTENING
            await self._announce(self.turns.state)
            return
        self._pipeline.last_heard = text
        if clock.confidence < self._config.min_confidence:
            reply = NOT_SURE.format(text=text)
            clock.reply_at = self._now()
            await self._speak_reply(turn_id, reply, clock, Context(is_error=True))
            return
        language = language_of(text)
        ack = asyncio.create_task(self._ack_if_slow(turn_id, text, language))
        self._outstanding[turn_id] = session_id
        try:
            reply = await self._pipeline.ask(text, session_id=session_id, confidence=clock.confidence)
        finally:
            self._outstanding.pop(turn_id, None)
            ack.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await ack
        clock.reply_at = self._now()
        took = clock.reply_at - clock.final_at if clock.final_at else 0.0
        context = Context(user_text=text, language=language, turns=self.stats.turns,
                          turns_since_connector=self._turns_since_connector,
                          previous_connector=self._previous_connector, reply_seconds=took,
                          is_error=reply.startswith(("Sorry, I couldn't", "I'm still working")))
        await self._speak_reply(turn_id, reply, clock, context)

    async def _ack_if_slow(self, turn_id: int, text: str, language: str) -> None:
        """A request that is taking a while gets a spoken "Okay," so the
        silence is not read as not having heard. Only for a request,
        only after `ack_after_ms`, and it counts as the turn's connector
        so the reply itself gets none."""
        if not self._config.connectors or self._config.ack_after_ms <= 0:
            return
        kind = choose_connector("I'll do that.", Context(user_text=text, turns_since_connector=self._turns_since_connector,
                                                        previous_connector=self._previous_connector))
        if kind != "okay":
            return
        await asyncio.sleep(self._config.ack_after_ms / 1000)
        if self.turns.state != THINKING or self.turns.turn_id != turn_id:
            return
        word = CONNECTORS["okay"].get(language, CONNECTORS["okay"]["en"]).rstrip(",") + "."
        request = TtsRequest(request_id=f"ack-{turn_id}", pieces=((word, 0),), voice=self._config.tts_voice,
                             speed=self._config.tts_speed)
        try:
            await self._player.play_stream(self._tts.synthesise_stream(request), request_id=request.request_id)
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "voice.ack_failed", error=repr(exc))
            return
        self._turns_since_connector = 0
        self._previous_connector = "okay"

    async def _speak_reply(self, turn_id: int, reply: str, clock: TurnClock, context: Context) -> None:
        actions = self.turns.reply_ready(turn_id)
        while any(a.kind == Actions.HOLD_REPLY for a in actions):
            # The person may be starting to talk: wait for that to settle
            # -- a blip is discarded and the reply goes ahead; real
            # speech becomes the next turn and this reply is dropped.
            self._settled.clear()
            try:
                await asyncio.wait_for(self._settled.wait(), timeout=self._config.max_turn_ms / 1000 + 2.0)
            except asyncio.TimeoutError:
                break
            actions = self.turns.reply_ready(turn_id)
        speak = next((a for a in actions if a.kind == Actions.SPEAK), None)
        if speak is None:
            for action in actions:
                await self._dispatch(action, frame_time=self._now())
            return
        response_id = str(speak.response_id)
        plan = self._planner.plan(reply, context)
        if plan.connector:
            self._turns_since_connector = 0
            self._previous_connector = next((k for k, v in CONNECTORS.items() if plan.connector in v.values()), "")
        else:
            self._turns_since_connector += 1
        request = TtsRequest(request_id=response_id, pieces=tuple((c.text, c.pause_ms) for c in plan.chunks),
                             voice=self._config.tts_voice, speed=self._config.tts_speed)
        self._echo_rms = 0.0
        self._reference.clear()
        self._pipeline.speaking = True

        def _first_audio(seconds: float) -> None:
            clock.first_audio_at = self._now()

        try:
            report = await self._player.play_stream(self._tts.synthesise_stream(request), request_id=response_id,
                                                    on_first_audio=_first_audio)
        except Exception as exc:  # noqa: BLE001 -- a reply that could not be spoken is logged, not fatal
            self._log("warning", "voice.reply_not_spoken", error=repr(exc))
            self.turns.handle_playback_state(PlaybackState("finished", response_id))
            self._pipeline.speaking = False
            return
        self._pipeline.speaking = False
        said = plan.text
        self._pipeline.last_said = said
        self.stats.turns += 1
        metrics = clock.metrics(report)
        if clock.interrupted_at and clock.stopped_at:
            metrics["interruption"] = round(clock.stopped_at - clock.interrupted_at, 3)
        metrics["connector"] = bool(plan.connector)
        metrics["omitted"] = list(plan.omitted)
        self.stats.last_metrics = metrics
        engine = getattr(self._tts, "last_engine", "") or self._tts.name
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": said, "seconds": report.seconds, "engine": engine, "device": self._config.device,
            "interrupted": report.interrupted, "turn": turn_id, "response": speak.response_id,
            **({"metrics": metrics} if self._config.diagnostics else {}),
        })
        await self._pipeline._record(VoiceTurn(  # noqa: SLF001
            session_id=f"turn-{turn_id}", device=self._config.device, speaker="", heard=clock.text,
            confidence=clock.confidence, said=said,
            heard_at=(self._clock.now() if self._clock is not None else time.time()) - max(0.0, self._now() - clock.speech_end) if clock.speech_end else 0.0,
            answered_at=self._clock.now() if self._clock is not None else time.time(),
            engine_stt=clock.engine_stt, engine_tts=engine, metrics=metrics if self._config.diagnostics else {},
        ))
        self._clocks.pop(turn_id, None)

    async def _on_playback_state(self, state: PlaybackState) -> None:
        if state.request_id.startswith("ack-"):
            return
        before = self.turns.state
        for action in self.turns.handle_playback_state(state):
            await self._dispatch(action, frame_time=self._now())
        if before != self.turns.state:
            await self._announce(self.turns.state)


__all__ = ["SessionStats", "TurnClock", "VoiceSession"]
