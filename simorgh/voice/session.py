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
import re
import contextlib
import time
import uuid
from collections import deque
from dataclasses import dataclass, field

from simorgh.contracts.household import HOUSEHOLD
from simorgh.contracts import topics

from .api import Audio, PlaybackState, TtsRequest, VoiceTurn
from .backchannel import GREETING, Backchannel, addressed, classify, is_quiet, strip_lead
from .commands import MUTE, OFF, STOP, spoken_command
from .delivery import REGISTERS, Delivery, register_for_backchannel, register_for_reply, register_for_tone
from .config import Config
from .lang import language_of
from .pipeline import NOT_SURE, Pipeline, is_echo
from .planner import CONNECTORS, Context, SpokenResponsePlanner
from .playback import StreamingPlayer
from .stt.streaming import IncrementalRecogniser
from .tts.streaming import StreamingSynthesiser
from .turns import AGENT_SPEAKING, Actions, LISTENING, Policy, THINKING, TurnManager, USER_SPEAKING
from .vad import CompositeDetector, EchoTracker, EnergyDetector, FrameVad, threshold_for

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


_QUESTION_WORDS = re.compile(r"^\s*(?:what|when|where|who|whom|whose|why|how|which|is|are|am|was|were|can|could|do|does|did|"
                             r"will|would|should|shall|may|might|have|has|had|چی|چه|کی|کجا|چرا|چطور|آیا)\b", re.I)


def _looks_like_question(text: str) -> bool:
    text = (text or "").strip()
    return text.endswith(("?", "؟")) or bool(_QUESTION_WORDS.match(text))


#: an unknown voice this close to an enrolled person is asked "is that you?"
#: rather than "what is your name?" (the threshold itself is 0.5)
GUESS_FLOOR = 0.22


class VoiceSession:
    def __init__(self, *, pipeline: Pipeline, config: Config, microphone, speaker, recogniser, synthesiser,
                 detector_factory, clock=None, logger=None, embedder=None, speakers=None) -> None:
        self._pipeline = pipeline
        self._config = config
        self._audio: dict[int, bytearray] = {}      # a turn's frames, kept only until it is identified
        self._enrolling: dict | None = None          # {"name", "relation", "takes", "done"} while `voice enroll` runs
        self._whois = False                          # `voice whois`: the next turn reports its scores instead of asking
        # What the room said lately: (speaker, text, when, asked?) -- the
        # lines not asked of Sim go to the model as context, and two
        # people talking to each other is a reason to stay quiet.
        self._room: deque = deque(maxlen=16)
        self._last_asked_speaker = ""
        self.last_speaker = ""
        self.last_identification = None
        self._mic = microphone
        self._detector_factory = detector_factory
        self._clock = clock
        self._logger = logger
        # Who is speaking (voice/speakers.py): the embedder turns a turn's
        # audio into a vector, the book says whose it is. Both optional;
        # with neither, every turn is simply "you", as before.
        self._embedder = embedder
        self._speakers = speakers
        if self._speakers is None and str(config.speaker_id).lower() != "off":
            from .speakers import SpeakerBook

            self._speakers = SpeakerBook(config.speakers_dir, threshold=config.speaker_threshold, margin=config.speaker_margin,
                                         household=HOUSEHOLD, lean=config.speaker_lean)
        # The engine is opened only once somebody is enrolled (or enrolment
        # starts): a household that never enrolled pays nothing per turn.
        if self._embedder is None and self._speakers is not None and self._speakers.people():
            self._open_embedder()
        # Meeting someone by conversation (voice/introduce.py).
        self._intro = None
        self._unknown = None
        if self._speakers is not None:
            from .introduce import UnknownVoices

            self._unknown = UnknownVoices(threshold=config.speaker_threshold, clock=lambda: self._now())
        self._stt = IncrementalRecogniser(recogniser, partials=config.stt_partials,
                                          partial_every_ms=config.stt_partial_every_ms)
        self._tts = synthesiser if isinstance(synthesiser, StreamingSynthesiser) else StreamingSynthesiser(
            synthesiser, lookahead=config.tts_lookahead)
        self._player = StreamingPlayer(speaker, on_state=self._on_playback_state)
        self._planner = SpokenResponsePlanner(max_sentences=config.max_spoken_sentences, connectors=config.connectors,
                                              pronunciations=lambda: self._speakers.pronunciations() if self._speakers else {})
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
        # Sim's own voice at the microphone, expected frame by frame
        # from what is playing (vad.EchoTracker) -- the bar a person
        # must clear to interrupt, and the reason Sim's echo is not a
        # turn. Fed by every playback, the ack and `say` included.
        self._echo = EchoTracker(calibrate_frames=max(1, config.barge_in_calibrate_ms // 30),
                                 lag_s=config.tv_audio_lag_s if config.output in ("tv", "both") else 0.0)
        self._tv_seq = 0
        self._detector = None
        self._vad: FrameVad | None = None
        self._turns_since_connector = 99
        self._previous_connector = ""
        # The "Aha." / "Let me check." said the moment a turn ends
        # (backchannel.py), and the turns that got one -- their reply
        # must not open with another "Okay,".
        self._backchannel = Backchannel()
        self._acknowledged: set[int] = set()
        self._answered: set[int] = set()      # turns whose reply is back: too late for an aside
        self._last_aside_at = -1e9
        self._last_hum_at = -1e9
        self._hum_task: asyncio.Task | None = None
        self._sim_spoke_at = -1e9        # when Sim's voice last finished: an exchange under way, or not
        self._ack_task: asyncio.Task | None = None
        self._still_task: asyncio.Task | None = None
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
        try:
            warm_stt = getattr(self._stt, "warmup", None)
            if callable(warm_stt):
                self.stats.warmup_seconds += float(await warm_stt())
        except Exception as exc:  # noqa: BLE001 -- the first turn starts the server instead
            self._log("warning", "voice.stt_warmup_failed", error=repr(exc))
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
        for task in (self._stt_task, self._ask_task, self._speak_task, self._ack_task, self._still_task,
                     self._hum_task):
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
        now = self._now()
        set_echo = getattr(self._detector, "set_echo", None)
        if set_echo is not None:
            if self._echo.active(now):
                # Sim may be audible: the bar is what the reference says
                # the mic should hear of it now, never what the mic
                # heard -- the mic frame may be the person. Only the
                # calibration frames of a reply teach the gain.
                rms = self._detector.rms(frame) if hasattr(self._detector, "rms") else 0.0
                self._echo.observe(rms, now)
                set_echo(self._echo.expected(now))
            else:
                self._detector.clear_echo()
        event = self._vad.process(frame)
        before = self.turns.state
        if before == USER_SPEAKING and event.kind == "speech_end":
            self._maybe_hum(event.speech_ms)
        actions = self.turns.handle_vad(event)
        if self.turns.state in (USER_SPEAKING,) and self._frames is not None:
            self._frames.put_nowait(frame)
            # For the speaker's voice, only the frames the detector calls
            # speech and only while Sim is not audible: a child's take
            # captured over Sim's own prompt and the room's silence scored
            # 0.68 against her father and 0.2 against herself (2026-09-13).
            keep = self._audio.get(getattr(self, "_capturing", None))
            if keep is not None and event.kind in ("speech_start", "speech") and not self._echo.active(now) \
                    and len(keep) < int(self._config.max_utterance_s * 16000 * 2):
                keep += frame
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
            self._capturing = action.turn_id
            if self._embedder is not None and self._speakers is not None:
                self._audio[action.turn_id] = bytearray()   # the speaker's own speech frames, filled by _on_frame
            previous = self._stt_task
            if previous is not None and not previous.done():
                # A transcription still waiting on the old queue would never
                # end: nothing feeds that queue again. Left alone it is a
                # pending task garbage-collected mid-await -- "Task was
                # destroyed but it is pending" and an async generator closed
                # while running, on the terminal (2026-09-13).
                previous.cancel()
            self._stt_task = asyncio.create_task(self._transcribe(action.turn_id, self._frames))
        elif kind == Actions.FINALISE:
            clock = self._clocks.get(action.turn_id)
            if clock is not None:
                clock.speech_end = frame_time
            if self._frames is not None:
                self._frames.put_nowait(_END)
            if self._config.backchannel:
                # Heard: say so now, from what the recogniser has so far,
                # and only then wait for the final words and the answer.
                self._ack_task = asyncio.create_task(self._acknowledge(action.turn_id, self.partial))
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
            # On screen, not only in the log: the reply's text is already
            # there from the task line, and a person reading it hears
            # nothing (the creator, 2026-09-11: "I know it is talking
            # because I see text on screen but no voice").
            self._log("info", "voice.reply_dropped", turn=action.turn_id, reason=action.reason)
            await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
                "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "interrupted": False,
                "dropped": True, "reason": str(action.reason or ""), "turn": action.turn_id})

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
    async def _frames_until_end(self, queue: asyncio.Queue, turn_id: int | None = None):
        while True:
            frame = await queue.get()
            if frame is _END:
                return
            yield frame

    async def _transcribe(self, turn_id: int, queue: asyncio.Queue) -> None:
        try:
            async for event in self._stt.start_stream(self._frames_until_end(queue, turn_id), turn_id=turn_id,
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
            self._audio.pop(turn_id, None)
            raise
        except Exception as exc:  # noqa: BLE001 -- one failed hearing must not end the session
            self._audio.pop(turn_id, None)
            self._log("warning", "voice.transcribe_failed", error=repr(exc))
            self.turns.state = LISTENING

    # ------------------------------------------------------------- answering
    async def _identify(self, turn_id: int):
        """Who spoke turn `turn_id`, from its audio: an Identification, or
        None when there is nothing to judge with. The audio is dropped
        here either way -- it is kept for this and nothing else."""
        pcm = self._audio.pop(turn_id, None)
        self._last_speech_s = 0.0
        if pcm is None or self._embedder is None or self._speakers is None:
            return None, None
        from .speakers import MIN_SECONDS, seconds_of

        if len(pcm) % 2:
            pcm = pcm[:-1]
        samples = [x / 32768.0 for x in memoryview(bytes(pcm)).cast("h")]
        self._last_speech_s = seconds_of(samples, 16000)
        if self._last_speech_s < MIN_SECONDS:
            return None, None
        try:
            vector = await asyncio.to_thread(self._embedder.embed, samples, 16000)
        except Exception as exc:  # noqa: BLE001 -- a failed embedding is an unknown speaker, not a failed turn
            self._log("warning", "voice.speaker_embed_failed", error=repr(exc))
            return None, None
        return self._speakers.identify(vector), vector

    async def _enroll_take(self, turn_id: int, text: str, vector) -> None:
        """One take of `voice enroll <name>`: the turn's voice goes into
        the book instead of being asked; Sim says where the enrolment is."""
        job = self._enrolling
        if job is None:
            return
        from .speakers import ENROLL_MIN_SECONDS

        if vector is None or getattr(self, "_last_speech_s", 0.0) < ENROLL_MIN_SECONDS:
            await self._say_aside(f"say-{turn_id}", "That was short. A whole sentence, please.")
            return
        try:
            person, note = self._speakers.enroll(job["name"], vector, relation=job.get("relation", ""),
                                                 insist=job.get("refused", 0) >= 1)
        except Exception as exc:  # noqa: BLE001
            note = f"refused: {exc}"
        await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
            "text": text, "confidence": 1.0, "seconds": 0.0, "engine": "", "device": self._config.device,
            "turn": turn_id, "enrolling": job["name"], "speaker_note": note})
        if note:
            # Once: "that sounded like Saeed". Twice: take it anyway -- a
            # child kept being told she sounded like her father (2026-09-13).
            job["refused"] = job.get("refused", 0) + 1
            who = note.split("sounds like ", 1)[1].split(" (")[0] if "sounds like " in note else "someone else"
            await self._say_aside(f"say-{turn_id}", f"That sounded like {who}. Once more, {job['name']}?")
            return
        job["done"] += 1
        if job["done"] >= job["takes"]:
            self._enrolling = None
            await self._say_aside(f"say-{turn_id}", f"Thank you, {job['name']}. I will know your voice now.")
        else:
            await self._say_aside(f"say-{turn_id}", f"Take {job['done']} of {job['takes']}. Say another sentence.")
        self.turns.state = LISTENING
        await self._announce(self.turns.state)

    def _open_embedder(self) -> str:
        """Open the speaker engine if it can be; "" or why not."""
        if self._embedder is not None:
            return ""
        from .speakers import SherpaEmbedder, available as _speaker_available

        ok, why = _speaker_available(self._config.model_dir)
        if not ok:
            return why
        self._embedder = SherpaEmbedder(self._config.model_dir)
        return ""

    def enroll(self, name: str, *, relation: str = "", takes: int = 3) -> str:
        """Start `voice enroll <name>`; returns "" or why not."""
        if self._speakers is None:
            return "speaker recognition is off ([voice] speaker_id)"
        why = self._open_embedder()
        if why:
            return why
        name = (name or "").strip()
        if not name:
            return "a name is needed"
        self._enrolling = {"name": name, "relation": relation.strip(), "takes": max(1, min(10, int(takes))), "done": 0}
        return ""

    def whois_next(self) -> str:
        if self._speakers is None:
            return "speaker recognition is off ([voice] speaker_id)"
        why = self._open_embedder()
        if why:
            return why
        self._whois = True
        return ""

    async def _ask_and_speak(self, turn_id: int, text: str) -> None:
        session_id = str(uuid.uuid4())
        clock = self._clocks.get(turn_id) or TurnClock(turn_id=turn_id)
        identification, vector = await self._identify(turn_id)
        if self._enrolling is not None:
            await self._enroll_take(turn_id, text, vector)
            return
        speaker = identification.name if identification is not None else ""
        if self._intro is not None:
            await self._introduce_step(turn_id, text, vector)
            return
        if self._speakers is not None and self._embedder is not None:
            from .introduce import learn_request

            wanted = learn_request(text, speaker=speaker)
            if wanted:
                await self._begin_introduction(turn_id, text, vector, name="" if wanted == "?" else wanted)
                return
        self.last_identification = identification
        if speaker:
            self.last_speaker = speaker
            self._speakers.heard(speaker)
            from .speakers import MIN_SECONDS

            if (vector is not None and not identification.probable and self._config.speaker_refine
                    and self._last_speech_s >= MIN_SECONDS and self._speakers.refine(speaker, vector)):
                self._log("debug", "voice.speaker_refined", speaker=speaker, score=round(identification.score, 3))
        who = {"speaker": speaker}
        if identification is not None:
            who["speaker_score"] = round(identification.score, 3)
            if identification.probable:
                who["speaker_probable"] = True
            if identification.reason and (not speaker or identification.probable):
                who["speaker_note"] = identification.reason
        if self._whois:
            self._whois = False
            scores = self._speakers.scores(vector) if vector is not None else []
            line = ", ".join(f"{n} {sc:.2f}" for n, sc in scores[:4]) or "nobody is enrolled"
            await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
                "text": text, "confidence": clock.confidence, "seconds": 0.0, "engine": clock.engine_stt,
                "device": self._config.device, "turn": turn_id, **who, "speaker_note": f"scores: {line}"})
            said = f"That sounded like {speaker}." if speaker else "I do not know that voice."
            await self._say_aside(f"say-{turn_id}", f"{said} Scores: {line}.")
            self.turns.state = LISTENING
            await self._announce(self.turns.state)
            return
        await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
            "text": text, "confidence": clock.confidence, "seconds": 0.0, "engine": clock.engine_stt,
            "device": self._config.device, "session_id": session_id, "turn": turn_id, **who})
        # Two people talking to each other: Sim listens and keeps the
        # thread, but does not ask the model and does not speak, unless
        # named or mid-exchange (voice/backchannel.py::addressed).
        if await self._bystander(turn_id, speaker, text):
            return
        if self._pipeline.last_said and is_echo(text, self._pipeline.last_said):
            await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
                "text": text, "confidence": clock.confidence, "seconds": 0.0, "engine": clock.engine_stt,
                "device": self._config.device, "session_id": session_id, "echo": True, "turn": turn_id})
            self.turns.state = LISTENING
            await self._announce(self.turns.state)
            return
        self._pipeline.last_heard = text
        self._last_user_text = text
        command = spoken_command(text)
        if command is not None:
            await self._obey(turn_id, command)
            return
        text = await self._tidy(text, turn_id)
        if clock.confidence < self._config.min_confidence:
            reply = NOT_SURE.format(text=text)
            clock.reply_at = self._now()
            await self._speak_reply(turn_id, reply, clock, Context(is_error=True))
            return
        language = language_of(text)
        still = asyncio.create_task(self._still_thinking(turn_id, language))
        self._still_task = still
        self._outstanding[turn_id] = session_id
        relation = ""
        if speaker and self._speakers is not None:
            person = self._speakers.get(speaker)
            relation = person.relation if person is not None else ""
        room = self._room_lines(exclude_text=text)
        self._room.append((speaker or "someone", text, self._now(), True))
        self._last_asked_speaker = speaker or ""
        try:
            reply = await self._pipeline.ask(text, session_id=session_id, confidence=clock.confidence,
                                             speaker_name=speaker, speaker_relation=relation, room=room)
        finally:
            self._outstanding.pop(turn_id, None)
            still.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await still
        clock.reply_at = self._now()
        self._answered.add(turn_id)
        if is_quiet(reply):
            await self._stay_quiet(turn_id)
            return
        took = clock.reply_at - clock.final_at if clock.final_at else 0.0
        context = Context(user_text=text, language=language, turns=self.stats.turns,
                          turns_since_connector=self._turns_since_connector,
                          previous_connector=self._previous_connector, reply_seconds=took,
                          is_error=reply.startswith(("Sorry, I couldn't", "I'm still working")))
        reply = self._maybe_ask_who(reply, identification, vector)
        await self._speak_reply(turn_id, reply, clock, context)

    # ------------------------------------------------------------- the room
    def _room_lines(self, *, exclude_text: str = "", within_s: float = 180.0) -> str:
        now = self._now()
        lines = [f"{who}: {said}" for who, said, at, asked in self._room
                 if not asked and now - at <= within_s and said != exclude_text]
        return "\n".join(lines[-8:])

    async def _bystander(self, turn_id: int, speaker: str, text: str) -> bool:
        """True when these words were two people talking to each other and
        Sim should keep listening: Sim was not named, Sim did not speak a
        moment ago, and another known person spoke within the last little
        while. Off with `[voice] bystander = false`."""
        if not self._config.bystander or self._speakers is None or self._embedder is None:
            return False
        now = self._now()
        me = speaker or "someone"
        # Named, or a question: for Sim. The follow-up window after Sim spoke
        # belongs to the person it answered -- somebody else's statement in
        # that window is them talking to that person, not to Sim.
        if addressed(text, since_sim_spoke_s=-1.0, exchange_window_s=0.0) or _looks_like_question(text):
            return False
        in_window = 0.0 <= now - self._sim_spoke_at <= self._config.exchange_window_s
        if in_window and me == (self._last_asked_speaker or me):
            return False
        others = {who for who, _said, at, _asked in self._room
                  if now - at <= self._config.exchange_window_s * 2 and who != me and who != "someone"}
        if not others:
            return False
        self._room.append((me, text, now, False))
        partner = sorted(others)[0]
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "turn": turn_id, "quiet": True,
            "reason": f"{me} and {partner} are talking to each other"})
        self.stats.turns += 1
        self.turns.state = LISTENING
        await self._announce(self.turns.state)
        return True

    # ------------------------------------------------------------- meeting someone
    def _maybe_ask_who(self, reply: str, identification, vector) -> str:
        """An unknown voice that keeps talking gets asked its name, after
        the answer it came for (voice/introduce.py)."""
        if (self._unknown is None or vector is None or identification is None or identification.known
                or self._intro is not None or int(self._config.introduce_after_turns) <= 0):
            return reply
        if self._unknown.note(vector) < int(self._config.introduce_after_turns):
            return reply
        from .introduce import Introduction

        self._intro = Introduction()
        self._intro.vectors.append(list(vector))
        self._unknown.clear()
        guess = getattr(identification, "runner_up", "") or ""
        close = float(getattr(identification, "runner_up_score", 0.0) or 0.0)
        if guess and close >= GUESS_FLOOR and self._speakers is not None and self._speakers.get(guess) is not None:
            # Nearly someone: ask them, do not make them introduce themselves
            # to a house that knows them (the creator, 2026-09-13: "you know me").
            self._intro.stage = "confirm"
            self._intro.guess = guess
            return f"{reply.rstrip()} By the way, you sound a little like {guess}, but I am not sure. Is that you?"
        return f"{reply.rstrip()} By the way, I do not know your voice yet. What is your name?"

    async def _begin_introduction(self, turn_id: int, text: str, vector, *, name: str) -> None:
        """"Sim, learn Aran's voice": the introduction starts at the takes
        when the name is known, at the name when it is not."""
        from .introduce import Introduction

        self._intro = Introduction()
        if name:
            self._intro.name = name
            self._intro.stage = "take"
            say = f"{name}, say a sentence for me, and then two more."
        else:
            say = "Gladly. What is your name?"
        await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
            "text": text, "confidence": 1.0, "seconds": 0.0, "engine": "", "device": self._config.device,
            "turn": turn_id, "enrolling": name or "?", "speaker_note": "introduction started"})
        await self._say_aside(f"say-{turn_id}", say)
        self.turns.state = LISTENING
        await self._announce(self.turns.state)

    async def _introduce_step(self, turn_id: int, text: str, vector) -> None:
        intro = self._intro
        step = intro.feed(text, vector, self._speakers)
        await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
            "text": text, "confidence": 1.0, "seconds": 0.0, "engine": "", "device": self._config.device,
            "turn": turn_id, "enrolling": intro.name or "?", "speaker_note": step.say})
        if step.done:
            self._intro = None
            if step.enrolled:
                self.last_speaker = step.enrolled
        if step.say:
            await self._say_aside(f"say-{turn_id}", step.say)
        self.turns.state = LISTENING
        await self._announce(self.turns.state)

    async def _acknowledge(self, turn_id: int, partial: str) -> None:
        """The sound of having heard -- "Aha.", "Let me check.", "Sure,
        one sec." -- the instant the person stops, before the recogniser
        has finished and long before the model has. Picked by what the
        turn seems to be from the provisional transcript, in the
        person's language, never the same as the last few. It counts as
        the turn's connector: the reply itself then opens plainly."""
        # Wait first. A quick answer is its own acknowledgement, and a
        # person who only paused between sentences must not have a
        # sound dropped on their next word: by now the turn manager has
        # either started their next turn (then this one is over) or
        # the pause was real.
        await asyncio.sleep(self._config.backchannel_after_ms / 1000)
        if self.turns.turn_id != turn_id or self.turns.state not in (THINKING, USER_SPEAKING):
            return
        if turn_id in self._answered or turn_id in self._acknowledged:
            return
        if self._now() - self._last_aside_at < self._config.backchannel_gap_s:
            return  # one was said a moment ago; another so soon is a tic
        if not addressed(partial, since_sim_spoke_s=self._now() - self._sim_spoke_at,
                         exchange_window_s=self._config.exchange_window_s):
            return  # possibly not for Sim at all: sit quiet, let the model decide
        kind = classify(partial)
        if kind == GREETING:
            return  # answered in a breath anyway
        language = language_of(partial) if partial else language_of(self._last_user_text)
        text = self._backchannel.pick(kind, language)
        if await self._say_aside(f"ack-{turn_id}", text, delivery=register_for_backchannel(kind)):
            self._acknowledged.add(turn_id)
            self._last_aside_at = self._now()
            self._turns_since_connector = 0
            self._previous_connector = "okay"

    async def _tidy(self, text: str, turn_id: int) -> str:
        """What the recogniser wrote, as Sim should read it (cognition/
        tidy.py); a change is announced as a corrected transcript."""
        if not self._config.tidy:
            return text
        from simorgh.cognition.tidy import tidy

        tidied = await tidy(self._pipeline._bus, text,  # noqa: SLF001 -- the same bus the ask goes on
                            recent=[self._last_user_text, self._pipeline.last_said])
        if tidied.changed:
            await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
                "text": tidied.text, "confidence": 1.0, "seconds": 0.0, "engine": "tidy",
                "device": self._config.device, "corrected": True, "turn": turn_id})
            self._last_user_text = tidied.text
        return tidied.text

    async def _obey(self, turn_id: int, command: str) -> None:
        """"Stop", "be quiet", "voice off": done here and now, the model
        never hears of it. Playback is cut, the floor goes back to
        listening (or, for off/mute, to the service to close)."""
        for task in (self._ack_task, self._still_task):
            if task is not None and not task.done():
                task.cancel()
        if self._player.playing:
            await self._player.stop()
        await self._tts.cancel(str(self.turns.speaking_response))
        self.turns.state = LISTENING
        await self._announce(self.turns.state)
        self._clocks.pop(turn_id, None)
        self._log("info", "voice.command", command=command, turn=turn_id)
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "interrupted": False,
            "command": command, "turn": turn_id})
        if command in (OFF, MUTE):
            # The service owns on/off; this session is about to be closed by it.
            await self._pipeline._publish(topics.VOICE_CONTROL_REQUEST, {  # noqa: SLF001
                "action": "off" if command == OFF else "mute"})

    async def _report_synthesis(self, report) -> None:
        """A voice that could not be used, or a reply that could not be
        made at all, is said on screen once rather than swallowed."""
        fell_back = getattr(self._tts, "fell_back", None)
        error = getattr(self._tts, "last_error", "")
        if fell_back:
            voice, why = fell_back
            self._log("warning", "voice.voice_fell_back", voice=voice, why=why)
            await self._pipeline._publish(topics.UI_NOTICE, {  # noqa: SLF001
                "level": "warn", "source": "voice",
                "text": f"the voice {voice!r} could not be used ({why}); spoke with the engine's default. "
                        f"`voice voices` lists the real ones."})
        elif error and report.chunks == 0:
            self._log("warning", "voice.reply_not_synthesised", why=error)
            await self._pipeline._publish(topics.UI_NOTICE, {  # noqa: SLF001
                "level": "warn", "source": "voice", "text": f"could not synthesise the reply: {error}"})

    async def _stay_quiet(self, turn_id: int) -> None:
        """The model heard words that were not for it. Nothing is said;
        the floor goes back to listening, and the screen shows why
        there was no reply."""
        actions = self.turns.reply_ready(turn_id)
        speak = next((a for a in actions if a.kind == Actions.SPEAK), None)
        if speak is not None:
            # A response was minted; it is over before it started.
            self.turns.handle_playback_state(PlaybackState("finished", str(speak.response_id)))
        if self.turns.state == THINKING:
            self.turns.state = LISTENING if self.turns.auto_listen else self.turns.state
        await self._announce(self.turns.state)
        self._answered.discard(turn_id)
        self._acknowledged.discard(turn_id)
        self._clocks.pop(turn_id, None)
        self._log("info", "voice.stayed_quiet", turn=turn_id)
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "interrupted": False,
            "quiet": True, "turn": turn_id})

    async def _still_thinking(self, turn_id: int, language: str) -> None:
        """`still_after_s` into a wait with no answer yet: one more short
        sound, so a long think is not a dead line."""
        if self._config.still_after_s <= 0 or not self._config.backchannel:
            return
        await asyncio.sleep(self._config.still_after_s)
        if self.turns.state != THINKING or self.turns.turn_id != turn_id or turn_id in self._answered:
            return
        if await self._say_aside(f"ack-{turn_id}-still", self._backchannel.still(language)):
            self._last_aside_at = self._now()

    def _delivery_for(self, user_text: str, reply: str, *, is_error: bool = False, tone: str = "") -> Delivery:
        base = Delivery()
        if self._config.expressive:
            mood = getattr(self._pipeline, "mood", None) or {}
            valence, arousal = float(mood.get("valence", 0.0)), float(mood.get("arousal", 0.0))
            # The feeling the model named wins; the words decide otherwise.
            base = (register_for_tone(tone, valence=valence, arousal=arousal) if tone else None) or \
                register_for_reply(user_text, reply, valence=valence, arousal=arousal, is_error=is_error)
        return base.with_base(self._config.tts_speed, self._config.volume)

    def _lane_for(self, text: str, *, spoken_turn: bool, explicit: bool = False) -> str:
        """Which engine says this when two are open (tts/lanes.py). The
        quick lane for a spoken turn, an aside, and a typed turn's reply
        -- the person is already reading that one, and a voice ten
        seconds behind the text is noise (the creator's screen,
        2026-09-13). The expressive lane when asked for it (`voice
        test`), for a long spoken answer, or always/off by setting."""
        mode = str(getattr(self._config, "expressive_lane", "auto") or "auto")
        if mode == "off":
            return "fast"
        if mode == "always" or explicit:
            return "expressive"
        if not spoken_turn:
            return "fast"
        threshold = int(getattr(self._config, "expressive_min_chars", 400) or 0)
        return "expressive" if threshold and len(text) >= threshold else "fast"

    def _maybe_hum(self, spoken_ms: int) -> None:
        """The person paused mid-story: a listener's "uh-huh", half loud,
        under them -- once they have been talking a while, not at the end
        of a question, and not twice within `hum_gap_s`."""
        if not (self._config.hum and self._config.backchannel):
            return
        now = self._now()
        if spoken_ms < self._config.hum_after_ms or now - self._last_hum_at < self._config.hum_gap_s:
            return
        if self.partial.rstrip().endswith("?") or self._pipeline.speech_lock.locked():
            return
        if self._hum_task is not None and not self._hum_task.done():
            return
        self._last_hum_at = now
        language = language_of(self.partial) if self.partial else language_of(self._last_user_text)
        text = self._backchannel.hum(language)
        self._hum_task = asyncio.create_task(self._say_aside(f"hum-{self.turns.turn_id}", text,
                                                             delivery=REGISTERS["hum"]))

    async def _say_aside(self, request_id: str, text: str, *, delivery: Delivery | None = None) -> bool:
        """Say a short aside through the player -- gated by the echo
        tracker like everything else -- unless a voice is already
        speaking, when an aside over it would be noise. True if said."""
        delivery = (delivery or Delivery()) if self._config.expressive else Delivery()
        delivery = delivery.with_base(self._config.tts_speed, self._config.volume)
        request = TtsRequest(request_id=request_id, pieces=((self._planner.pronounced(text), 0),), voice=self._config.tts_voice,
                             speed=delivery.speed, gain=delivery.gain, lane="fast")
        lock = self._pipeline.speech_lock
        if lock.locked():
            return False
        try:
            async with lock:
                await self._play(self._tts.synthesise_stream(request), request_id=request.request_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "voice.aside_failed", error=repr(exc))
            return False
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": text, "seconds": 0.0, "engine": getattr(self._tts, "last_engine", "") or self._tts.name,
            "device": self._config.device, "interrupted": False, "aside": True, "turn": self.turns.turn_id,
            "register": delivery.register})
        return True

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
        self._answered.discard(turn_id)
        if turn_id in self._acknowledged:
            # "Okay." was already said aloud; "Okay, ..." again is a stutter.
            self._acknowledged.discard(turn_id)
            reply = strip_lead(reply)
        from simorgh.contracts.tone import split_tone

        tone, reply = split_tone(reply)
        plan = self._planner.plan(reply, context)
        if plan.connector:
            self._turns_since_connector = 0
            self._previous_connector = next((k for k, v in CONNECTORS.items() if plan.connector in v.values()), "")
        else:
            self._turns_since_connector += 1
        delivery = self._delivery_for(context.user_text, plan.text, is_error=context.is_error, tone=tone)
        lane = self._lane_for(plan.text, spoken_turn=True)
        request = TtsRequest(request_id=response_id,
                             pieces=tuple((c.text, int(c.pause_ms * delivery.pause_scale)) for c in plan.chunks),
                             voice=self._config.tts_voice, speed=delivery.speed, gain=delivery.gain,
                             tone=tone or (delivery.register if delivery.register in ("warm", "bright") else ""),
                             lane=lane)
        self._pipeline.speaking = True

        def _first_audio(seconds: float) -> None:
            clock.first_audio_at = self._now()

        try:
            async with self._pipeline.speech_lock:
                report = await self._play(self._tts.synthesise_stream(request), request_id=response_id,
                                          on_first_audio=_first_audio)
        except Exception as exc:  # noqa: BLE001 -- a reply that could not be spoken is logged, not fatal
            self._log("warning", "voice.reply_not_spoken", error=repr(exc))
            self.turns.handle_playback_state(PlaybackState("finished", response_id))
            if self.turns.state == THINKING:  # playback never started, so "finished" moved nothing
                self.turns.state = LISTENING
                await self._announce(self.turns.state)
            self._pipeline.speaking = False
            return
        self._pipeline.speaking = False
        self._sim_spoke_at = self._now()
        await self._report_synthesis(report)
        from .pronounce import strip_marks

        said = strip_marks(plan.text, for_voice=False)
        self._pipeline.last_said = said
        self.stats.turns += 1
        metrics = clock.metrics(report)
        if clock.interrupted_at and clock.stopped_at:
            metrics["interruption"] = round(clock.stopped_at - clock.interrupted_at, 3)
        metrics["connector"] = bool(plan.connector)
        metrics["register"] = delivery.register
        metrics["tone"] = tone
        metrics["lane"] = lane
        metrics["held"] = round(float(getattr(self._tts, "last_hold_s", 0.0)), 2)
        metrics["omitted"] = list(plan.omitted)
        self.stats.last_metrics = metrics
        engine = getattr(self._tts, "last_engine", "") or self._tts.name
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": said, "seconds": report.seconds, "engine": engine, "device": self._config.device,
            "interrupted": report.interrupted, "turn": turn_id, "response": speak.response_id,
            **({"metrics": metrics} if self._config.diagnostics else {}),
        })
        await self._pipeline._record(VoiceTurn(  # noqa: SLF001
            session_id=f"turn-{turn_id}", device=self._config.device, speaker=self.last_speaker if self.last_identification is not None and self.last_identification.name else "", heard=clock.text,
            confidence=clock.confidence, said=said,
            heard_at=(self._clock.now() if self._clock is not None else time.time()) - max(0.0, self._now() - clock.speech_end) if clock.speech_end else 0.0,
            answered_at=self._clock.now() if self._clock is not None else time.time(),
            engine_stt=clock.engine_stt, engine_tts=engine, metrics=metrics if self._config.diagnostics else {},
        ))
        self._clocks.pop(turn_id, None)

    async def say(self, text: str, *, request_id: str = "", lane: str = "") -> str:
        """Speak something that is not a reply to a spoken turn -- a typed
        turn's reply, `voice test` -- THROUGH the session, so the turn
        manager knows Sim is talking and the microphone's echo of it is
        treated as Sim, not as a person. Returns what was said."""
        plan = self._planner.plan(text, Context())
        request = TtsRequest(request_id=request_id or f"say-{uuid.uuid4().hex[:8]}",
                             pieces=tuple((c.text, c.pause_ms) for c in plan.chunks),
                             voice=self._config.tts_voice, speed=self._config.tts_speed,
                             lane=lane or self._lane_for(plan.text, spoken_turn=False, explicit=lane == "expressive"))
        entered_from = self.turns.state
        if entered_from == LISTENING:
            self.turns.state = AGENT_SPEAKING
            self.turns.speaking_response = 0
            await self._announce(self.turns.state)
        self._pipeline.speaking = True
        try:
            async with self._pipeline.speech_lock:
                report = await self._play(self._tts.synthesise_stream(request), request_id=request.request_id)
        finally:
            self._pipeline.speaking = False
            self._sim_spoke_at = self._now()
            if self.turns.state == AGENT_SPEAKING and entered_from == LISTENING:
                self.turns.state = LISTENING
                await self._announce(self.turns.state)
        from .pronounce import strip_marks

        shown = strip_marks(plan.text, for_voice=False)
        self._pipeline.last_said = shown
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": shown, "seconds": report.seconds, "engine": getattr(self._tts, "last_engine", "") or self._tts.name,
            "device": self._config.device, "interrupted": report.interrupted})
        return shown

    async def _play(self, chunks, *, request_id: str, **kw):
        """Every playback goes through here so the echo tracker is told
        what the room is about to hear -- a reply, the ack, `say` -- and
        so the TV page gets each piece the moment it goes to the speaker
        (`[voice] output` tv or both)."""
        self._echo.start()
        to_tv = self._config.output in ("tv", "both")

        async def _reference(audio: Audio) -> None:
            self._echo.play(audio, at=self._now())
            if to_tv:
                await self._ship_to_tv(audio, request_id)

        return await self._player.play_stream(chunks, request_id=request_id, on_play=_reference, **kw)

    async def _ship_to_tv(self, audio: Audio, request_id: str) -> None:
        """One run of the voice as a WAV blob in the ledger, announced on
        the bus for the TV page to fetch and play in order. Best effort:
        no ledger, or a blob that will not store, costs the TV a piece
        and nothing else."""
        ledger = getattr(self._pipeline, "_ledger", None)
        if ledger is None:
            return
        from .audio import wav_bytes

        try:
            ref = await ledger.put_blob(wav_bytes(audio), content_type="audio/wav")
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "voice.tv_speech_not_stored", error=repr(exc))
            return
        self._tv_seq += 1
        await self._pipeline._publish(topics.TV_SPEECH, {  # noqa: SLF001
            "ref": ref, "seconds": round(audio.seconds, 3), "seq": self._tv_seq, "request_id": request_id})

    async def _on_playback_state(self, state: PlaybackState) -> None:
        if state.request_id.startswith(("ack-", "say-", "hum-")):
            return
        before = self.turns.state
        for action in self.turns.handle_playback_state(state):
            await self._dispatch(action, frame_time=self._now())
        if before != self.turns.state:
            await self._announce(self.turns.state)


__all__ = ["SessionStats", "TurnClock", "VoiceSession"]
