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
from dataclasses import dataclass, field, replace

from simorgh.contracts.household import HOUSEHOLD
from simorgh.contracts import topics

from .api import Audio, PlaybackState, TtsRequest, VoiceTurn
from .backchannel import (
    GREETING, Backchannel, addressed, asks_for_something_sim_does, classify, is_quiet,
    spell_household_names, strip_lead, to_someone_else,
)
from .commands import MUTE, OFF, RESTART, STOP, opens_with_stop, spoken_command
from .delivery import REGISTERS, Delivery, register_for_backchannel, register_for_reply, register_for_tone
from .config import Config
from .lang import language_of
from .pipeline import NOT_SURE, Pipeline, echoes_recent, is_echo
from .planner import CONNECTORS, Context, SpokenResponsePlanner, asked_to_continue
from .playback import StreamingPlayer
from .stt.streaming import IncrementalRecogniser
from .tts.streaming import StreamingSynthesiser
from .turns import AGENT_SPEAKING, Actions, LISTENING, Policy, THINKING, TurnManager, USER_SPEAKING
from .vad import CompositeDetector, EchoTracker, EnergyDetector, FrameVad, threshold_for

_END = object()
# 1200 ms, not 600: what interrupts Sim is judged from this buffer, and
# speakers.MIN_SECONDS needs 800 ms of it before a voice can be placed at
# all. At 600 the check could never run (the creator, in a car, 2026-09-17:
# a crow cut Sim off at the strictest detector setting there is).
_PREROLL_FRAMES = 40


def _spoken_seconds(clock) -> float:
    """How long the person spoke for, from the VAD's own two marks.

    Every final transcript published a hard-coded `0.0` here. The
    field is not decoration: the World Model reads it to learn how
    fast somebody usually talks, which is one of the three signals
    behind a companion check-in (stage 10 item 2), and it only keeps
    a reading when `seconds > 0`. So the pace signal has never once
    fired in the live system -- found while timing the household
    simulator, where a partial carried 1.51 s and the final that
    followed it carried nothing (2026-09-20).
    """
    if clock.speech_end and clock.speech_start and clock.speech_end > clock.speech_start:
        return round(clock.speech_end - clock.speech_start, 3)
    return 0.0


@dataclass
class TurnClock:
    turn_id: int
    speech_start: float = 0.0
    speech_end: float = 0.0
    final_at: float = 0.0
    reply_at: float = 0.0
    first_audio_at: float = 0.0
    # when the reply reached the speech lock and when it got it: the gap
    # is an aside or another reply still being said (first_audio ran to
    # 4-10 s on turns beside a playing TV, 2026-09-13, cause unknown)
    lock_wait_at: float = 0.0
    lock_got_at: float = 0.0
    interrupted_at: float = 0.0
    stopped_at: float = 0.0
    text: str = ""
    confidence: float = 1.0
    engine_stt: str = ""
    language: str = ""
    # The turn's trace, minted when Sim is asked, so the percept, the think
    # and this turn's stage spans are one trace (stage 1 items 2 and 4).
    trace_id: str = ""

    def metrics(self, report=None) -> dict:
        out: dict = {}
        if self.speech_end and self.final_at:
            out["stt"] = round(self.final_at - self.speech_end, 3)
        if self.final_at and self.reply_at:
            out["llm"] = round(self.reply_at - self.final_at, 3)
        if self.reply_at and self.first_audio_at:
            out["first_audio"] = round(self.first_audio_at - self.reply_at, 3)
        if self.lock_wait_at and self.lock_got_at:
            out["lock_wait"] = round(self.lock_got_at - self.lock_wait_at, 3)
        if self.reply_at and self.lock_wait_at:
            out["before_lock"] = round(self.lock_wait_at - self.reply_at, 3)     # planning, delivery, lane
        if self.lock_got_at and self.first_audio_at:
            out["synth_first"] = round(self.first_audio_at - self.lock_got_at, 3)   # the engine's own time
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
    # Stage-budget breaches per day, "YYYY-MM-DD" -> {stage: count}
    # (stage 3 item 8); `voice status` shows today's and yesterday's.
    breaches: dict = field(default_factory=dict)


#: The time a spoken turn may spend per stage (stage 3 item 8): the final
#: transcript after the person stops, and the first audio after they stop.
STAGE_BUDGETS_S = {"stt": 2.0, "response": 2.5}


_QUESTION_WORDS = re.compile(r"^\s*(?:what|when|where|who|whom|whose|why|how|which|is|are|am|was|were|can|could|do|does|did|"
                             r"will|would|should|shall|may|might|have|has|had|چی|چه|کی|کجا|چرا|چطور|آیا)\b", re.I)


def _looks_like_question(text: str) -> bool:
    text = (text or "").strip()
    return text.endswith(("?", "؟")) or bool(_QUESTION_WORDS.match(text))


#: an unknown voice this close to an enrolled person is asked "is that you?"
#: rather than "what is your name?" (the threshold itself is 0.5)
GUESS_FLOOR = 0.22
#: "no, this is Ira" / "I'm Iris" / "it's Saeed" -- a claim of identity, taken as a take when the name is known
_I_AM = re.compile(r"\b(?:this is|it'?s|i'?m|i am|my name is)\s+([A-Z][a-z]+)\b(?!\s+(?:voice|question|game))", re.I)
#: "who is talking / speaking / am I / is this" -- answered from the identification, not the model
#: "Sim, who said I don't care?" -- answered from what was actually heard
_WHO_SAID = re.compile(r"\bwho\s+(?:just\s+)?(?:said|asked|told\s+you|was\s+saying)\s+(?:that\s+)?[\"“']?(.+?)[\"”']?\s*\??\s*$", re.I)
_WHO_IS_SPEAKING = re.compile(r"\bwho(?:'s| is| am)\s+(?:i\b|(?:this|that|it)\b|(?:talking|speaking)\b|(?:one\s+of\s+us\s+is\s+)?(?:talking|speaking))|which\s+(?:one\s+)?of\s+us\s+is\s+(?:talking|speaking)", re.I)


_TO_SIM = re.compile(r"\b(?:you|your|you're|youre|you've)\b", re.I)


def may_refine(*, segments, probable: bool, refine_on: bool, seconds: float,
               min_seconds: float, has_vector: bool) -> bool:
    """Whether this turn may be kept as a take of the speaker's voice.

    Never from a turn two people shared: the whole-turn vector holds both
    voices, so keeping it teaches one person the other's -- exactly the blend
    that put Iris's words under the creator's name ("you recognised that as my
    voice, that was a bad recognition", 2026-09-15). Never from a guess, and
    never from less speech than the book asks for."""
    return bool(has_vector and refine_on and not segments and not probable and seconds >= min_seconds)


#: Whisper answers with a code ("fa") or with a name ("persian"), and which
#: depends on the build. Cutting the first two letters served the code and
#: mangled the name: "persian" became "pe" and "spanish" became "sp", so
#: Persian -- one of this house's own two languages -- was thrown away as
#: foreign, unheard, logged as "not a language of this house" (live
#: 2026-09-17: nine turns discarded in half an hour).
_LANGUAGE_CODES = {
    "english": "en", "persian": "fa", "farsi": "fa", "arabic": "ar", "hebrew": "he",
    "spanish": "es", "french": "fr", "german": "de", "italian": "it", "dutch": "nl",
    "portuguese": "pt", "russian": "ru", "turkish": "tr", "hindi": "hi", "urdu": "ur",
    "chinese": "zh", "mandarin": "zh", "japanese": "ja", "korean": "ko", "polish": "pl",
    "swedish": "sv", "norwegian": "no", "danish": "da", "finnish": "fi", "greek": "el",
    "hungarian": "hu", "czech": "cs", "romanian": "ro", "ukrainian": "uk", "vietnamese": "vi",
    "thai": "th", "indonesian": "id", "malay": "ms", "bengali": "bn", "punjabi": "pa",
    "tamil": "ta", "telugu": "te", "armenian": "hy", "azerbaijani": "az", "kurdish": "ku",
}


def _language_code(value: str) -> str:
    """A two-letter code from whatever whisper said: a code stays as it is,
    a name becomes its code, anything unrecognised keeps the old
    truncation."""
    text = (value or "").strip().lower()
    return _LANGUAGE_CODES.get(text, text[:2])


def _speaks_to_sim(text: str) -> bool:
    """Words aimed at Sim: second person, or a question.

    Live 2026-09-15, minutes after the continuation rule landed: the creator
    was told his own turn was "more of what he was saying to someone else" and
    answered "I have a conversation with you while you're just bailing out
    mid-conversation". A fragment of somebody else's talk does not say "you"."""
    stripped = (text or "").strip()
    return bool(stripped) and (stripped.endswith("?") or bool(_TO_SIM.search(stripped)))


def prune_kept_audio(folder, *, days: float, max_mb: float, now: float) -> int:
    """Delete kept turns (a `.wav` and its `.json`) older than `days`,
    then the oldest until the folder is under `max_mb`. Returns how many
    turns went. Never raises: retention must not stop a turn."""
    from pathlib import Path

    try:
        wavs = sorted(Path(folder).glob("*.wav"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return 0
    removed = 0

    def _drop(wav) -> None:
        nonlocal removed
        for path in (wav, wav.with_suffix(".json")):
            try:
                path.unlink()
            except OSError:
                pass
        removed += 1

    keep = []
    for wav in wavs:
        try:
            age_days = (now - wav.stat().st_mtime) / 86400.0
        except OSError:
            continue
        if days and age_days > days:
            _drop(wav)
        else:
            keep.append(wav)
    if max_mb:
        def _size(w):
            try:
                return w.stat().st_size + (w.with_suffix(".json").stat().st_size if w.with_suffix(".json").exists() else 0)
            except OSError:
                return 0
        total = sum(_size(w) for w in keep)
        limit = max_mb * 1024 * 1024
        for wav in keep:
            if total <= limit:
                break
            total -= _size(wav)
            _drop(wav)
    return removed


class VoiceSession:
    def __init__(self, *, pipeline: Pipeline, config: Config, microphone, speaker, recogniser, synthesiser,
                 detector_factory, clock=None, logger=None, embedder=None, speakers=None) -> None:
        self._pipeline = pipeline
        self._config = config
        self._audio: dict[int, bytearray] = {}      # a turn's frames, kept only until it is identified
        self._timed: dict[int, tuple] = {}          # a turn's (audio, timed words), kept until attributed
        self._enrolling: dict | None = None          # {"name", "relation", "takes", "done"} while `voice enroll` runs
        self._whois = False                          # `voice whois`: the next turn reports its scores instead of asking
        # What the room said lately: (speaker, text, when, asked?) -- the
        # lines not asked of Sim go to the model as context, and two
        # people talking to each other is a reason to stay quiet.
        self._room: deque = deque(maxlen=16)
        # Durable counterpart: every line not said to Sim, on disk, kept
        # 48 hours (`overheard.MAX_AGE_S`) -- "what did we say in the last hour?" asked
        # hours later, after a restart, needs more than a sixteen-line deque.
        # The store is in Contracts, not here, because the tool that ANSWERS
        # that question runs in Execution and no subsystem may import
        # another: a store in Voice is one only Voice can read, which is
        # exactly how this feature failed twice (contracts/overheard.py).
        self._overheard_dir = getattr(config, "overheard_dir", "workspace/voice/overheard")
        #: when the model stayed quiet on a voice it could not place (voice/session.py::_background)
        self._quiet_unknown: deque = deque(maxlen=8)
        #: whether the last words Sim answered were properly for it: named, or from a voice it knows
        self._last_ask_addressed = False
        self._last_asked_speaker = ""
        self.last_speaker = ""
        self.last_identification = None
        # Per-turn facts from `_identify`, keyed by turn id: the speech
        # length, why the turn was never compared, and its audio for an
        # enrolment take. They were session attributes read after later
        # awaits, so an overlapping turn could overwrite them before the
        # first turn's reader got there (2026-09-18 evaluation, V8; the
        # per-turn-facts-in-session-state bug shape).
        self._turn_facts: dict[int, dict] = {}
        self._scored: dict[int, dict] = {}   # turn_id -> what the book concluded
        self._named: dict[int, str] = {}     # turn_id -> who the book said it was
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
                                         refine_above=config.speaker_refine_above,
                                         household=HOUSEHOLD, lean=config.speaker_lean)
        # The engine is opened only once somebody is enrolled (or enrolment
        # starts): a household that never enrolled pays nothing per turn.
        if self._embedder is None and self._speakers is not None and self._speakers.has_voices():
            self._open_embedder()   # a household known by name only pays nothing per turn
        # Meeting someone by conversation (voice/introduce.py).
        self._intro = None
        self._unknown = None
        if self._speakers is not None:
            from .introduce import UnknownVoices

            self._unknown = UnknownVoices(threshold=config.speaker_threshold, clock=lambda: self._now())
        # An engine that streams already gives a partial per chunk; wrapping
        # it would re-decode the whole buffer over and over, which is exactly
        # the cost it exists to remove.
        self._stt = (recogniser if getattr(recogniser, "streaming", False)
                     else IncrementalRecogniser(recogniser, partials=config.stt_partials,
                                                partial_every_ms=config.stt_partial_every_ms))
        self._tts = synthesiser if isinstance(synthesiser, StreamingSynthesiser) else StreamingSynthesiser(
            synthesiser, lookahead=config.tts_lookahead)
        self._player = StreamingPlayer(speaker, on_state=self._on_playback_state,
                                       stall_timeout_s=self._config.tts_stall_timeout_s)
        self._planner = SpokenResponsePlanner(max_sentences=config.max_spoken_sentences, connectors=config.connectors,
                                              pronunciations=lambda: self._speakers.pronunciations() if self._speakers else {})
        #: What the last reply did not say aloud, so "go on" can.
        self._unspoken = ""
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
        self._quiet_on: dict[str, float] = {}   # speaker -> when the model last stayed quiet on them
        self._talking_with: dict[str, float] = {}   # speaker -> when Sim last answered them
        self._ack_task: asyncio.Task | None = None
        self._still_task: asyncio.Task | None = None
        #: Turns that have already had a "let me look" (stage 3 item 5):
        #: one per turn, however many slow tools the turn runs.
        self._filled: set[int] = set()
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
        self._outstanding: dict[int, tuple[str, str]] = {}

    # ------------------------------------------------------------- helpers
    @property
    def state(self) -> str:
        return self.turns.state

    def _now(self) -> float:
        return time.monotonic()

    def _check_budgets(self, clock: "TurnClock") -> list[str]:
        """Count the stages of this turn that ran over `STAGE_BUDGETS_S`,
        and record each as a telemetry event in the turn's trace."""
        took = {"stt": clock.final_at - clock.speech_end if clock.speech_end and clock.final_at else None,
                "response": clock.first_audio_at - clock.speech_end if clock.speech_end and clock.first_audio_at else None}
        over = [stage for stage, seconds in took.items()
                if seconds is not None and seconds > STAGE_BUDGETS_S[stage]]
        if not over:
            return []
        day = time.strftime("%Y-%m-%d")
        counts = self.stats.breaches.setdefault(day, {})
        for stage in over:
            counts[stage] = counts.get(stage, 0) + 1
        for old in sorted(self.stats.breaches)[:-2]:
            self.stats.breaches.pop(old, None)
        telemetry = getattr(self._pipeline, "telemetry", None)
        if telemetry is not None and clock.trace_id:
            with contextlib.suppress(Exception):
                for stage in over:
                    telemetry.event("voice.budget_breach", trace_id=clock.trace_id, span_id=uuid.uuid4().hex,
                                    attrs={"stage": stage, "seconds": round(took[stage], 3),
                                           "budget_s": STAGE_BUDGETS_S[stage], "turn": clock.turn_id})
        return over

    def _record_stage_spans(self, clock: "TurnClock", report) -> None:
        """The turn's stages as timed spans in its trace (stage 1 item 4):
        stt, think (the wait for Sim), synth to first audio, and playback.
        The clock is monotonic; the store keeps wall time."""
        self._check_budgets(clock)
        telemetry = getattr(self._pipeline, "telemetry", None)
        if telemetry is None or not clock.trace_id:
            return
        to_wall = time.time() - time.monotonic()
        spoken_end = clock.first_audio_at + float(getattr(report, "seconds", 0.0) or 0.0) if clock.first_audio_at else 0.0
        stages = (("voice.stt", clock.speech_end, clock.final_at), ("voice.think", clock.final_at, clock.reply_at),
                  ("voice.first_audio", clock.reply_at, clock.first_audio_at),
                  ("voice.playback", clock.first_audio_at, spoken_end))
        try:
            for name, start, end in stages:
                if start and end and end >= start:
                    telemetry.event(name, trace_id=clock.trace_id, span_id=uuid.uuid4().hex, ts=start + to_wall,
                                    end=end + to_wall, attrs={"turn": clock.turn_id})
        except Exception:  # noqa: BLE001 -- measuring a turn must never break it
            pass

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
        # Cover a slow tool out loud while it runs (stage 3 item 5). Set
        # here and cleared in `_teardown`: the pipeline outlives one
        # session, and a stale handler would speak for a session that
        # has stopped listening.
        self._pipeline.on_tool_started = self._on_tool_started
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
        self._pipeline.on_tool_started = None
        # A chat still running for a turn nobody will hear is stopped too.
        with contextlib.suppress(Exception):
            await self._cancel_outstanding(before=10**9)
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
        if before == AGENT_SPEAKING and event.kind in ("speech_start", "speech"):
            event = await self._only_a_voice_we_know(event)
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
            earlier = self._repeat_of(action.text)
            if earlier is not None:
                await self._repeat_waits(action.turn_id, earlier, action.text)
            else:
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

    def _repeat_of(self, text: str) -> int | None:
        """The outstanding turn these words ask again, if any: the same
        question, or a nudge ("are you there?") while one is owed
        (voice/repeat.py)."""
        from .repeat import is_nudge, is_repeat

        if not self._outstanding:
            return None
        newest = max(self._outstanding)
        if is_nudge(text):
            return newest
        for turn, (_sid, asked) in sorted(self._outstanding.items(), reverse=True):
            if is_repeat(text, asked):
                return turn
        return None

    async def _repeat_waits(self, turn_id: int, earlier: int, text: str) -> None:
        """The question is already being answered: this turn is not
        asked and does not cancel the earlier one. A short "still on
        it" aloud, when backchannels are on, so the wait is not silence."""
        self.turns.withdraw_ask(turn_id)
        self._clocks.pop(turn_id, None)
        self._log("info", "voice.repeat_waiting", turn=turn_id, of=earlier)
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "turn": turn_id, "quiet": True,
            "reason": f"the same question again; the answer to turn {earlier} is on its way"})
        if self._config.backchannel and self._backchannel is not None:
            if await self._say_aside(f"ack-{turn_id}-still", self._backchannel.still(language_of(text))):
                self._last_aside_at = self._now()

    def _tv_is_playing(self) -> bool:
        state = getattr(self._pipeline, "tv_state", None) or {}
        return str(state.get("mode") or "none") in ("full", "frame")

    _COURTESY = frozenset((
        "thank", "thanks", "you", "so", "much", "very", "okay", "ok", "yeah", "yes", "yep", "no", "nope", "bye",
        "goodbye", "good", "luck", "night", "go", "wait", "sorry", "please", "oh", "wow", "cool", "nice", "right",
        "alright", "sure", "fine", "it's", "its", "that's", "great", "awesome", "hmm", "uh", "um", "huh", "hey",
        # "- I'm sorry." said to someone on a call got "No need to apologize"
        # spoken into it (live 2026-09-15). Every word must be courtesy for a
        # turn to count as an aside, so "I'm hungry" is still a turn.
        "i'm", "im", "i", "am", "my", "bad",
    ))

    def _courtesy_aside(self, text: str) -> bool:
        """A few words of courtesy or filler, not naming Sim and not an
        answer to what Sim just said."""
        words = re.findall(r"[a-z']+", (text or "").lower())
        if not words or len(words) > 6 or any(w not in self._COURTESY for w in words):
            return False
        if self._names_sim(text):
            return False
        in_exchange = 0.0 <= self._now() - self._sim_spoke_at <= self._config.exchange_window_s
        return not in_exchange

    @staticmethod
    def _names_sim(text: str) -> bool:
        # "Hey Sim" came back from whisper as "A-seam." and Sim stayed quiet,
        # then was asked "why are you not responding?"; "Hey Seym are you
        # there?" the same afternoon (live 2026-09-15).
        #
        # "team" is the same mishearing and cannot join that list bare --
        # "the team is coming over" would wake Sim in the middle of a
        # conversation about anything. It counts only where a name goes,
        # after a greeting ("I said hey sim, but you listened hey team",
        # the creator, live 2026-09-15).
        return bool(re.search(r"\b(?:sim|sima|simorgh|sam|seem|seam|seym|syme)\b"
                              r"|\b(?:hey|hi|hello|ok|okay)\s+teams?\b", text or "", re.I))

    def _other_language(self, heard: str) -> str:
        """The language code whisper heard, when it is not one of the
        house's (`[voice] stt_languages`); "" otherwise."""
        allowed = {_language_code(c) for c in (self._config.stt_languages or "").split(",") if c.strip()}
        code = _language_code(heard)
        if not allowed or not code or code in ("au", "un"):     # auto / unknown
            return ""
        return "" if code in allowed else code

    async def _cancel_outstanding(self, *, before: int) -> None:
        """Ask the Worker to stop the chats for turns older than
        `before`: a chat mid-investigation was holding the model for the
        turn the person actually wants answered. One whose answer is
        already in flight still gets spoken (turns.py, `_superseded`)."""
        for turn, (session_id, _asked) in list(self._outstanding.items()):
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
                    other = self._other_language(event.language)
                    if other and event.text.strip():
                        # Not a language of this house: whisper's guess for
                        # noise, a TV, a song. Heard as nothing.
                        self._log("info", "voice.other_language", turn=turn_id, language=other, text=event.text[:60])
                        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
                            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "turn": turn_id,
                            "quiet": True, "reason": f"heard {other}, not a language of this house "
                                                     f"({self._config.stt_languages}); probably not speech for me"})
                        event = replace(event, text="")
                    clock = self._clocks.get(turn_id)
                    if clock is not None:
                        clock.final_at = self._now()
                        clock.text = event.text
                        clock.confidence = event.confidence
                        clock.engine_stt = event.engine
                        clock.language = event.language or ""
                    if event.words and event.audio:
                        self._timed[turn_id] = (event.audio, event.words)
                    self.partial = ""
                    if self._config.keep_audio and event.audio:
                        # The streaming path kept none, so `keep_audio` was a
                        # switch that did nothing here -- and the audio a
                        # recogniser actually receives is the only honest
                        # input for calibrating its confidence or judging a
                        # noise filter. Off by default; the folder it writes
                        # to is gitignored. Beside each file, what was heard.
                        self._keep_turn(turn_id, event)
                before = self.turns.state
                for action in self.turns.handle_transcript(event):
                    await self._dispatch(action, frame_time=self._now())
                if before != self.turns.state:
                    await self._announce(self.turns.state)
        except asyncio.CancelledError:
            self._audio.pop(turn_id, None)
            self._timed.pop(turn_id, None)
            raise
        except Exception as exc:  # noqa: BLE001 -- one failed hearing must not end the session
            self._audio.pop(turn_id, None)
            self._timed.pop(turn_id, None)
            self._log("warning", "voice.transcribe_failed", error=repr(exc))
            self.turns.state = LISTENING
            self._settled.set()      # a reply held for this candidate may go ahead
            await self._announce(self.turns.state)

    # ------------------------------------------------------------- answering
    async def _only_a_voice_we_know(self, event):
        """Let a crow finish Sim's sentence for it, or not.

        The level gate asks how loud a sound is and the detector asks
        whether it is speech; neither asks *whose*. Beside a playground,
        with the detector at its strictest setting (0.70) and the loudness
        bar at 2.8, a passing car and then a crow each cut Sim off mid
        reply -- the creator, 2026-09-17: "why would the noise ambient
        noise like stop you? You should only stop ... if you hear a human,
        like my voice basically, or any family voice".

        The interrupting sound is already in hand: `_preroll` holds the
        frames from before the turn manager noticed anything. Embed those
        and ask the book. Only when the answer is a name does the event
        stay an interruption; otherwise it is downgraded to silence and
        Sim talks on.

        Fails OPEN, always. No embedder, nobody enrolled, too little
        audio, a failed embedding: the interruption stands, exactly as it
        did before this existed. A gate that failed closed would leave Sim
        impossible to interrupt, which is the worse fault of the two.
        """
        if not self._config.barge_in_known_voice:
            return event
        if int(getattr(event, "speech_ms", 0)) < int(self._config.barge_in_speech_ms):
            return event                      # not yet an interruption; nothing to judge
        if self._embedder is None or self._speakers is None or not self._speakers.has_voices():
            return event
        from dataclasses import replace

        from .speakers import MIN_SECONDS, seconds_of

        pcm = b"".join(self._preroll)
        if len(pcm) % 2:
            pcm = pcm[:-1]
        samples = [x / 32768.0 for x in memoryview(pcm).cast("h")]
        if seconds_of(samples, 16000) < MIN_SECONDS:
            return event                      # too little to place; let it through
        try:
            vector = await asyncio.to_thread(self._embedder.embed, samples, 16000)
            who = self._speakers.identify(vector)
        except Exception as exc:  # noqa: BLE001 -- an unjudged sound still interrupts
            self._log("warning", "voice.barge_in_not_judged", error=repr(exc))
            return event
        if who is not None and who.known:
            self._log("debug", "voice.barge_in_by", who=who.name, score=round(who.score, 3))
            return event
        self._log("info", "voice.barge_in_ignored",
                  score=round(getattr(who, "score", 0.0), 3),
                  closest=getattr(who, "runner_up", "") or getattr(who, "name", ""))
        return replace(event, kind="silence")

    def _facts(self, turn_id: int) -> dict:
        """This turn's facts from `_identify` (empty ones if it never ran)."""
        return self._turn_facts.get(turn_id) or {"speech_s": 0.0, "skip": "", "pcm": b""}

    async def _identify(self, turn_id: int):
        """Who spoke turn `turn_id`, from its audio: an Identification, or
        None when there is nothing to judge with. The audio is dropped
        here either way -- it is kept for this and nothing else."""
        pcm = self._audio.pop(turn_id, None)
        # Kept for the enrolment paths: they run after this and are handed
        # only the embedding, and the frames are dropped here.
        facts = {"speech_s": 0.0, "skip": "", "pcm": bytes(pcm) if pcm else b""}
        self._turn_facts[turn_id] = facts
        for stale in [t for t in self._turn_facts if t < turn_id - 32]:
            self._turn_facts.pop(stale, None)
        if pcm is None or self._embedder is None or self._speakers is None:
            facts["skip"] = "no_audio" if pcm is None else "no_model"
            return None, None
        from .speakers import MIN_SECONDS, seconds_of

        if len(pcm) % 2:
            pcm = pcm[:-1]
        samples = [x / 32768.0 for x in memoryview(bytes(pcm)).cast("h")]
        facts["speech_s"] = seconds_of(samples, 16000)
        if facts["speech_s"] < MIN_SECONDS:
            # The commonest reason a turn carries no name: it was never
            # compared at all. No threshold can recover these.
            facts["skip"] = "too_short"
            return None, None
        try:
            vector = await asyncio.to_thread(self._embedder.embed, samples, 16000)
        except Exception as exc:  # noqa: BLE001 -- a failed embedding is an unknown speaker, not a failed turn
            self._log("warning", "voice.speaker_embed_failed", error=repr(exc))
            facts["skip"] = "embed_failed"
            return None, None
        return self._speakers.identify(vector), vector

    def _note_score(self, turn_id: int, identification) -> None:
        """Keep what the book concluded about this turn, so the spoken-turn
        record can carry the number. Until 2026-09-17 the score was computed
        and thrown away: 1,275 turns, 70% of them nameless, and not one of
        them said whether it had scored 0.49 or had never been compared --
        so the threshold could only ever be argued about, never read off."""
        facts = self._facts(turn_id)
        note: dict = {"speech_s": round(float(facts["speech_s"]), 2)}
        if identification is None:
            note["speaker_scored"] = False
            note["speaker_skipped"] = facts["skip"] or "unknown"
        else:
            note["speaker_scored"] = True
            note["speaker_score"] = round(float(identification.score), 3)
            note["speaker_named"] = identification.name
            note["speaker_probable"] = bool(identification.probable)
            if identification.runner_up:
                note["speaker_runner_up"] = identification.runner_up
                note["speaker_runner_up_score"] = round(float(identification.runner_up_score), 3)
        self._scored[turn_id] = note
        if len(self._scored) > 64:      # turns that never reach a spoken reply
            for stale in sorted(self._scored)[:-32]:
                self._scored.pop(stale, None)

    def _keep_turn(self, turn_id: int, event) -> None:
        """File a turn's audio and what was made of it, for calibration.

        `min_confidence` was written against an engine that reported a flat
        1.0, so the gate had never once run; the streaming engine reports a
        real number and tripped it on correct transcripts (2026-09-17).
        Choosing a threshold, or judging whether a denoiser helps, needs
        the audio the recogniser actually heard -- not a synthesised
        approximation, which scored 0.745 where a real voice scores 0.46.
        """
        import json as _json
        import time as _time
        from pathlib import Path

        try:
            from .api import Audio
            from .audio import write_wav

            folder = Path(self._config.audio_dir)
            stamp = f"{int(_time.time() * 1000)}-{turn_id}"
            write_wav(folder / f"{stamp}.wav", Audio(bytes(event.audio)))
            (folder / f"{stamp}.json").write_text(_json.dumps({
                "at": _time.time(), "turn": turn_id, "text": event.text,
                "confidence": round(float(event.confidence), 4), "engine": event.engine,
                "language": getattr(event, "language", "") or "",
                "seconds": round(float(event.audio_seconds), 3),
                **{k: v for k, v in (self._scored.get(turn_id) or {}).items()},
            }, indent=1), encoding="utf-8")
        except (OSError, ValueError) as exc:
            self._log("warning", "voice.turn_not_kept", error=repr(exc))
            return
        prune_kept_audio(Path(self._config.audio_dir), days=self._config.keep_audio_days,
                         max_mb=self._config.keep_audio_max_mb, now=_time.time())

    async def _attribute(self, turn_id: int, identification) -> list:
        """Who said which words of the turn (voice/diarize.py), when it
        is long enough to hold two people and the book knows anyone.
        [] means: one voice, the whole-turn verdict stands."""
        kept = self._timed.pop(turn_id, None)
        if kept is None or not self._config.diarize or self._embedder is None or self._speakers is None:
            return []
        audio, words = kept
        if len(audio) / 32000.0 < float(self._config.diarize_min_s) or not self._speakers.has_voices():
            return []
        from .diarize import attribute, speakers_in

        try:
            segments = await asyncio.to_thread(attribute, audio, 16000, words, self._embedder.embed,
                                               self._speakers.identify)
        except Exception as exc:  # noqa: BLE001 -- attribution is a refinement, never the turn's failure
            self._log("warning", "voice.attribute_failed", error=repr(exc))
            return []
        names = speakers_in(segments)
        if len(names) < 2:
            return []       # one voice: the whole-turn identification is the better judge
        return segments

    async def _enroll_take(self, turn_id: int, text: str, vector) -> None:
        """One take of `voice enroll <name>`: the turn's voice goes into
        the book instead of being asked; Sim says where the enrolment is."""
        job = self._enrolling
        if job is None:
            return
        from .speakers import ENROLL_MIN_SECONDS

        facts = self._facts(turn_id)
        if vector is None or facts["speech_s"] < ENROLL_MIN_SECONDS:
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
        self._speakers.keep_take(job["name"], facts["pcm"], text=text,
                                 seconds=facts["speech_s"], source="enroll")
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
        self._note_score(turn_id, identification)
        if self._enrolling is not None or self._intro is not None:
            # "stop" / "voice off" are obeyed here too -- they became takes
            # 1 and 2 of Aran's voice once (observer, 2026-09-13).
            self._timed.pop(turn_id, None)
            command = spoken_command(text)
            if command is not None:
                self._enrolling = None
                self._intro = None
                await self._obey(turn_id, command)
                return
        if self._enrolling is not None:
            await self._enroll_take(turn_id, text, vector)
            return
        speaker = identification.name if identification is not None else ""
        if not speaker and self._tv_is_playing() and not self._names_sim(text):
            # Live 2026-09-13: a KATSEYE video's own dialogue ("my wife
            # Michelle will judge the drawings") was heard, transcribed and
            # answered. While the TV plays, a voice Sim cannot place that
            # does not name Sim is the TV.
            self._log("info", "voice.tv_audio", turn=turn_id, text=text[:60])
            await self._stay_quiet(turn_id, reason="the TV is playing and this is not a voice I know -- the TV, most likely")
            return
        if self._intro is not None:
            await self._introduce_step(turn_id, text, vector)
            return
        if self._speakers is not None and self._embedder is not None:
            from .introduce import learn_request

            wanted = learn_request(text, speaker=speaker)
            if wanted:
                self._timed.pop(turn_id, None)
                await self._begin_introduction(turn_id, text, vector, name="" if wanted == "?" else wanted)
                return
        segments = await self._attribute(turn_id, identification)
        self._last_segments = [seg.as_dict() for seg in segments]
        if segments:
            from .diarize import lines, speakers_in

            names = speakers_in(segments)
            speaker = names[-1] if names else speaker     # the last voice is the one Sim answers
            text = lines(segments)
        # Give a household name its own spelling before anything reads
        # this turn: the screen, the memory, the vocative rule and the
        # model all see the same person. The creator, out loud on
        # 2026-09-20, correcting Sim: "Ira and not Aira".
        text = spell_household_names(text, self._household_names())
        self.last_identification = identification
        if speaker:
            self.last_speaker = speaker
            self._speakers.heard(speaker)
            from .speakers import MIN_SECONDS

            if (may_refine(segments=segments, probable=identification.probable,
                           refine_on=self._config.speaker_refine, seconds=self._facts(turn_id)["speech_s"],
                           min_seconds=MIN_SECONDS, has_vector=vector is not None)
                    and self._speakers.refine(speaker, vector)):
                self._log("debug", "voice.speaker_refined", speaker=speaker, score=round(identification.score, 3))
                # Silently, until the creator asked twice whether Sim was
                # learning at all and was told no -- by a model that cannot see
                # this happen (2026-09-15). The screen says it now.
                person = self._speakers.get(speaker)
                self._learnt_note = f"learnt your voice: {speaker} now has {len(person.embeddings)} takes" if person else ""
        # This turn's answer, kept for this turn. The record is written from
        # another method, after the model and the whole spoken reply -- so
        # reading `last_speaker` there asks a session-level singleton a
        # per-turn question, and whatever turn begins meanwhile answers it.
        # 23 of 122 named turns reached `voice:turns` with speaker="" though
        # the book had named them (measured 2026-09-18); turn 468 wrote ""
        # into the record and "Soodeh" into the episodic line four lines
        # later, across one await, for the same turn.
        self._named[turn_id] = speaker
        if len(self._named) > 64:
            for stale in sorted(self._named)[:-32]:
                self._named.pop(stale, None)
        who = {"speaker": speaker}
        learnt, self._learnt_note = getattr(self, "_learnt_note", ""), ""
        if learnt:
            who["speaker_learnt"] = learnt
        if segments:
            who["segments"] = [seg.as_dict() for seg in segments]
        if identification is not None:
            who["speaker_score"] = round(identification.score, 3)
            if identification.probable:
                who["speaker_probable"] = True
            if identification.reason and (not speaker or identification.probable):
                who["speaker_note"] = identification.reason
        if clock.final_at and clock.speech_end and clock.final_at - clock.speech_end >= 8.0:
            from .health import slow_hearing_note

            note = slow_hearing_note(clock.final_at - clock.speech_end)
            if note:   # beside the speaker note, never instead of it
                who["speaker_note"] = (who["speaker_note"] + "; " if who.get("speaker_note") else "") + note
        if self._whois:
            self._whois = False
            scores = self._speakers.scores(vector) if vector is not None else []
            line = ", ".join(f"{n} {sc:.2f}" for n, sc in scores[:4]) or "nobody is enrolled"
            await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
                "text": text, "confidence": clock.confidence, "seconds": _spoken_seconds(clock), "engine": clock.engine_stt,
                "device": self._config.device, "turn": turn_id, **who, "speaker_note": f"scores: {line}"})
            said = f"That sounded like {speaker}." if speaker else "I do not know that voice."
            await self._say_aside(f"say-{turn_id}", f"{said} Scores: {line}.")
            self.turns.state = LISTENING
            await self._announce(self.turns.state)
            return
        await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
            "text": text, "confidence": clock.confidence, "seconds": _spoken_seconds(clock), "engine": clock.engine_stt,
            "device": self._config.device, "session_id": session_id, "turn": turn_id, **who})
        # Two people talking to each other: Sim listens and keeps the
        # thread, but does not ask the model and does not speak, unless
        # named or mid-exchange (voice/backchannel.py::addressed).
        if await self._bystander(turn_id, speaker, text):
            return
        if await self._named_somebody_else(turn_id, speaker, text):
            return
        # Within the exchange window, test against everything Sim said
        # recently -- a long reply returns as fragments, each too short
        # for the run matcher and each landing after `last_said` moved on.
        recents = list(self._pipeline.recent_said) or [self._pipeline.last_said]
        in_exchange_now = 0.0 <= self._now() - self._sim_spoke_at <= self._config.exchange_window_s
        if recents and (echoes_recent(text, recents) if in_exchange_now
                        else (self._pipeline.last_said and is_echo(text, self._pipeline.last_said))):
            await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
                "text": text, "confidence": clock.confidence, "seconds": _spoken_seconds(clock), "engine": clock.engine_stt,
                "device": self._config.device, "session_id": session_id, "echo": True, "turn": turn_id})
            self.turns.state = LISTENING
            await self._announce(self.turns.state)
            return
        self._pipeline.last_heard = text
        self._last_user_text = text
        if self._player.playing and opens_with_stop(text):
            # The level gate is the fast path and it can misjudge a room; the
            # words are the one that cannot. "stop stop I'm saying stop
            # multiple times" and Sim talked on (the creator, 2026-09-15).
            await self._player.stop()
            self.stats.interruptions += 1
            self._log("info", "voice.stop_word", turn=turn_id, text=text[:40])
        command = spoken_command(text)
        if command is not None:
            await self._obey(turn_id, command, speaker=speaker, clock=clock)
            return
        if _WHO_IS_SPEAKING.search(text) and self._speakers is not None and self._speakers.has_voices():
            # "Who is talking now?" is a fact the voice layer holds; the
            # model guessed "Iris" at the creator (2026-09-13).
            await self._answer_who(turn_id, text, identification, clock)
            return
        said_by = _WHO_SAID.search(text)
        if said_by and self._speakers is not None:
            # "Who said I don't care?" -- nobody had, in hours; the model
            # answered "That was Ira, a moment ago" (live 2026-09-13).
            clock.reply_at = self._now()
            await self._speak_reply(turn_id, self._who_said(said_by.group(1)), clock, Context(user_text=text))
            return
        claimed = self._identity_claim(text)
        if claimed and vector is not None and self._speakers is not None and claimed.lower() != speaker.lower():
            # "No, this is Ira. Remember the voice." A person of the house
            # saying who they are is a take for that voice, taken on their
            # word -- the model had said "I'm writing it down" and nothing
            # was written (2026-09-13). Only for a name the book knows.
            await self._take_correction(turn_id, text, claimed, vector, clock)
            return
        if self._courtesy_aside(text):
            # "Thank you", "okay", "bye", "go, go" said to someone else got
            # "You're welcome" again and again, with the voice rules already
            # asking for QUIET (2026-09-14). Small words that name nobody
            # and follow nothing Sim said are not a turn; the model is not
            # asked.
            self._room.append((speaker or "someone", text, self._now(), "aside"))
            self._log_overheard(speaker or "someone", text)
            await self._stay_quiet(turn_id, reason="a courtesy word not said to Sim")
            return
        if await self._background(turn_id, speaker, text):
            return
        if await self._continuation(turn_id, speaker, text):
            return
        if await self._unplaced(turn_id, speaker, text):
            return
        text = await self._tidy(text, turn_id)
        if clock.confidence < self._config.min_confidence:
            # Asking "did you say ...?" is for someone talking to Sim. A
            # half-heard aside -- the creator and a guest talking Farsi across
            # the room -- got the question read back to it, English and Farsi
            # in one breath, turn after turn (2026-09-14, live). Unless Sim was
            # named or an exchange is under way, a turn Sim could not hear
            # clearly is not a turn at all.
            now = self._now()
            in_exchange = (0.0 <= now - self._sim_spoke_at <= self._config.exchange_window_s
                           and self._last_ask_addressed)
            if not in_exchange and not addressed(text, since_sim_spoke_s=-1.0, exchange_window_s=0.0):
                self._room.append((speaker or "someone", text, now, "aside"))
                self._log_overheard(speaker or "someone", text)
                await self._stay_quiet(turn_id)
                return
            reply = NOT_SURE.format(text=text)
            clock.reply_at = self._now()
            await self._speak_reply(turn_id, reply, clock, Context(is_error=True))
            return
        language = language_of(text)
        still = asyncio.create_task(self._still_thinking(turn_id, language))
        self._still_task = still
        self._outstanding[turn_id] = (session_id, text)
        relation = ""
        if speaker and self._speakers is not None:
            person = self._speakers.get(speaker)
            relation = person.relation if person is not None else ""
        room = self._room_lines(exclude_text=text, speaker=speaker)
        self._room.append((speaker or "someone", text, self._now(), "asked"))
        before, self._last_asked_speaker = self._last_asked_speaker, speaker or ""
        self._last_ask_addressed = bool(speaker) or addressed(text, since_sim_spoke_s=-1.0, exchange_window_s=0.0)
        live = None
        early: asyncio.Task | None = None
        if self._config.stream_replies:
            # Stage 3 item 4: speak the first sentence while the model
            # writes the rest. The same Context the finished reply would get,
            # less what is only known at the end.
            from .streamreply import SentenceStream

            live = SentenceStream(max_sentences=self._config.max_spoken_sentences,
                                  on_sentence=self._pipeline.recent_said.append, language=language,
                                  transform=self._planner.pronounced)
            self._pipeline.delta_sinks[session_id] = live.feed
            early_context = Context(user_text=text, language=language, turns=self.stats.turns,
                                    turns_since_connector=self._turns_since_connector,
                                    previous_connector=self._previous_connector)

            async def _speak_when_started() -> None:
                await live.started.wait()
                still.cancel()
                clock.reply_at = clock.reply_at or self._now()
                await self._speak_reply(turn_id, "", clock, early_context, live=live)

            early = asyncio.create_task(_speak_when_started())
        try:
            clock.trace_id = clock.trace_id or uuid.uuid4().hex
            from .speakers import doubt_of

            ident = self.last_identification
            doubt = doubt_of(ident, threshold=self._config.speaker_threshold) \
                if ident is not None and ident.name == speaker else ""
            reply = await self._pipeline.ask(text, session_id=session_id, confidence=clock.confidence,
                                             speaker_name=speaker, speaker_relation=relation, room=room,
                                             speaker_before=before, speaker_doubt=doubt, trace_id=clock.trace_id)
        finally:
            self._outstanding.pop(turn_id, None)
            self._pipeline.delta_sinks.pop(session_id, None)
            still.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await still
        if live is not None and early is not None:
            from simorgh.contracts.tone import strip_tone as _strip

            if live.started.is_set():
                # Speaking began: the rest of the reply joins the same
                # utterance, and this turn is done when it has been said.
                live.finish(reply if _strip(reply).strip() and not is_quiet(_strip(reply)) else "")
                self._answered.add(turn_id)
                with contextlib.suppress(asyncio.CancelledError):
                    await early
                return
            early.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await early
        clock.reply_at = self._now()
        self._answered.add(turn_id)
        from simorgh.contracts.tone import strip_tone as _strip_tone

        if not _strip_tone(reply).strip() or is_quiet(_strip_tone(reply)):
            # "[warm] QUIET" is QUIET: the tag came first and the word was
            # spoken aloud, in a warm voice (2026-09-13, 17:46). And an empty
            # reply is silence too: a cancelled ask comes back "", and the
            # planner turned that into "I have nothing to say to that.",
            # said aloud to Iris eight minutes after she spoke (2026-09-14).
            if not speaker:
                self._quiet_unknown.append(self._now())
            self._quiet_on[speaker or "someone"] = self._now()
            await self._stay_quiet(turn_id)
            return
        self._room.append(("Sim", _strip_tone(reply), self._now(), "reply"))
        # Only a NAMED person starts a conversation. "someone" is not a
        # person -- it is every voice Sim cannot place, merged into one
        # key, so answering one of them claimed a live conversation with
        # all of them for `conversation_window_s`. The creator's work call,
        # 2026-09-16: one mistaken answer, then Sim answered his colleagues
        # for the next forty minutes, each turn renewing the window.
        if speaker:
            self._talking_with[speaker] = self._now()
        took = clock.reply_at - clock.final_at if clock.final_at else 0.0
        context = Context(user_text=text, language=language, turns=self.stats.turns,
                          turns_since_connector=self._turns_since_connector,
                          previous_connector=self._previous_connector, reply_seconds=took,
                          is_error=reply.startswith(("Sorry, I couldn't", "I'm still working")))
        reply = self._maybe_ask_who(reply, identification, vector)
        await self._speak_reply(turn_id, reply, clock, context)

    # ------------------------------------------------------------- the room
    def _log_overheard(self, speaker: str, text: str, *, kind: str = "overheard") -> None:
        """Persist a line that was not said to Sim (contracts/overheard.py)."""
        from simorgh.contracts import overheard

        try:
            # Wall clock, NOT `self._now()` -- that is `time.monotonic()`.
            # This store outlives the process, so a monotonic stamp renders as
            # a nonsense time of day and makes every line unrecallable: a
            # `since_s` filter measured against `time.time()` matches none of
            # them. Shipped that way on 2026-09-16 and caught only by reading
            # the live file; every test passed because each supplied its own
            # `at` and so never met the real clock.
            at = self._clock.now() if self._clock is not None else time.time()
            overheard.record(text, speaker=speaker, kind=kind, at=at,
                             folder=self._overheard_dir)
        except Exception:  # never let the log break the voice loop
            pass

    def _room_lines(self, *, exclude_text: str = "", within_s: float = 180.0, speaker: str = "") -> str:
        """What the model is told of the room: asides that were not for
        Sim, and -- for a voice other than the one Sim just answered, or
        one it could not place -- the last exchange, so "fix for what?"
        from a new voice has something to refer to (live 2026-09-13: Sim
        invented an answer)."""
        now = self._now()
        lines = [f"{who}: {said}" for who, said, at, kind in self._room
                 if kind == "aside" and now - at <= within_s and said != exclude_text][-8:]
        if not speaker or speaker != (self._last_asked_speaker or ""):
            exchange = []
            for who, said, at, kind in reversed(self._room):
                if now - at > 120.0 or said == exclude_text:
                    continue
                if kind == "reply" and not exchange:
                    exchange.append(f"you: {said}")
                elif kind == "asked" and exchange:
                    exchange.append(f"{who} (to you): {said}")
                    break
            lines = list(reversed(exchange)) + lines
        if speaker and self._in_conversation(speaker):
            since = int(self._now() - self._talking_with.get(speaker, self._now()))
            lines = [f"You are mid-conversation with {speaker}; you answered them {since}s ago. "
                     f"Their next words are for you unless they are plainly for someone else."] + lines
        tv = getattr(self._pipeline, "tv_line", lambda: "")()
        if tv:
            lines = [tv] + lines
        return "\n".join(lines)

    async def _bystander(self, turn_id: int, speaker: str, text: str) -> bool:
        """True when these words were two people talking to each other and
        Sim should keep listening: Sim was not named, Sim did not speak a
        moment ago, and another known person spoke within the last little
        while. Off with `[voice] bystander = false`."""
        if not self._config.bystander or self._speakers is None or self._embedder is None:
            return False
        if self._in_conversation(speaker):
            return False
        now = self._now()
        me = speaker or "someone"
        # Named, or a question: for Sim. The follow-up window after Sim spoke
        # belongs to the person it answered -- somebody else's statement in
        # that window is them talking to that person, not to Sim.
        if addressed(text, since_sim_spoke_s=-1.0, exchange_window_s=0.0) or _looks_like_question(text):
            return False
        # Asking for something only Sim does. The creator, 2026-09-20: his
        # daughter sang in the kitchen, he said "tell me a story from the
        # Arabian Nights book" a moment later, and this rule filed it as the
        # two of them talking. Nobody asks a five-year-old to set a timer.
        if asks_for_something_sim_does(text, names=self._household_names()):
            return False
        in_window = 0.0 <= now - self._sim_spoke_at <= self._config.exchange_window_s
        if in_window and me == (self._last_asked_speaker or me):
            return False
        others = {who for who, _said, at, _asked in self._room
                  if now - at <= self._config.exchange_window_s * 2 and who != me and who != "someone"}
        if not others:
            return False
        self._quiet_on[me] = now      # so `_continuation` covers the second half
        self._room.append((me, text, now, "aside"))
        self._log_overheard(me, text)
        partner = sorted(others)[0]
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "turn": turn_id, "quiet": True,
            "reason": f"{me} and {partner} are talking to each other"})
        self.stats.turns += 1
        self.turns.state = LISTENING
        await self._announce(self.turns.state)
        return True

    async def _named_somebody_else(self, turn_id: int, speaker: str, text: str) -> bool:
        """True when the words name who they are for, and it is not Sim.

        `_bystander` needs another known voice to have spoken recently
        before it will call anything an aside; a parent turning to a
        child at the start of an evening has no such history, and
        every one of those went to the model to judge. With a real
        provider "Can you try a bit harder next time, honey." came
        back as "Sorry, Devin -- tell me what I got wrong and I'll fix
        it": Sim taking a parent's word to their child personally.
        The creator's log, 2026-09-20, and reproduced by the household
        simulator against the paid provider the same day
        (`live/an-aside-is-not-for-sim`).

        A sentence that says who it is for has said who it is for, and
        no amount of question-shape argues with that. Deliberately not
        applied inside a conversation Sim is already in: "thanks, love"
        to Sim mid-exchange is for Sim, and `_in_conversation` is the
        rule that has settled that question twice already.
        """
        if not self._config.bystander or self._in_conversation(speaker):
            return False
        other = to_someone_else(text, names=self._household_names())
        if not other:
            return False
        me = speaker or "someone"
        now = self._now()
        # `_continuation` reads this: whisper cuts one sentence into
        # two turns, and the second half used to be answered after
        # the first was rightly ignored. It was stamped only when the
        # MODEL answered QUIET, so every deterministic quiet rule --
        # this one and `_bystander` -- left the follow-up unprotected
        # (found with the paid provider, 2026-09-20: "Can you try a
        # bit harder next time, honey." went quiet and "I said we are
        # leaving in five minutes." was answered).
        self._quiet_on[me] = now
        self._room.append((me, text, now, "aside"))
        self._log_overheard(me, text)
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "turn": turn_id,
            "quiet": True, "reason": f"{me} was talking to {other}"})
        self.stats.turns += 1
        self.turns.state = LISTENING
        await self._announce(self.turns.state)
        return True

    def _household_names(self) -> tuple[str, ...]:
        """Who else lives here, so their name in a vocative counts too.

        From the speaker book, which is the list this process actually
        has: the People store is another subsystem and a query per
        turn on the listening path is the wrong trade for a name.
        """
        if self._speakers is None:
            return ()
        try:
            return tuple(person.name for person in self._speakers.people())
        except Exception:  # noqa: BLE001 -- a name list is never worth a dropped turn
            return ()

    def _in_conversation(self, speaker: str) -> bool:
        """Sim answered this person within `conversation_window_s`.

        A conversation under way is the answer to "why did you bail out in the
        middle of it" (the creator, 2026-09-15): while it is live, none of the
        quiet rules apply to that person -- they are talking to Sim, and the
        pace of the exchange says so more reliably than any wording test."""
        window = float(getattr(self._config, "conversation_window_s", 180.0) or 0.0)
        if window <= 0 or not speaker:
            # An unplaceable voice is never "mid-conversation": the quiet
            # rules are exactly what it needs, and this check is what
            # turned them all off (see `_speak_reply`).
            return False
        last = self._talking_with.get(speaker)
        return last is not None and 0.0 <= self._now() - last <= window

    async def _continuation(self, turn_id: int, speaker: str, text: str) -> bool:
        """True when these words carry on an aside the model just stayed
        quiet on: the same voice, within `continuation_quiet_s`, not naming
        Sim, and Sim has not spoken since. Whisper cuts one sentence into two
        turns; the second half was answered after the first was rightly
        ignored (Ira to Bobby about pizza, 2026-09-15). A voice Sim knows
        only: an unknown voice has `_background`, which waits for two quiet
        turns before it stops asking."""
        if self._in_conversation(speaker):
            return False
        window = float(self._config.continuation_quiet_s or 0.0)
        me = speaker
        at = self._quiet_on.get(me) if me else None
        now = self._now()
        if window <= 0 or at is None or now - at > window or self._sim_spoke_at >= at:
            return False
        if addressed(text, since_sim_spoke_s=-1.0, exchange_window_s=0.0) or _speaks_to_sim(text):
            return False
        self._quiet_on[me] = now
        self._room.append((me, text, now, "aside"))
        self._log_overheard(me, text)
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "turn": turn_id, "quiet": True,
            "reason": f"more of what {me} was saying to someone else"})
        self.stats.turns += 1
        self.turns.state = LISTENING
        await self._announce(self.turns.state)
        return True

    async def _unplaced(self, turn_id: int, speaker: str, text: str) -> bool:
        """True when a voice Sim cannot place said something that does not
        name Sim and does not answer what Sim just asked.

        The scaffold has forbidden this for weeks and the model keeps
        answering anyway: on 2026-09-15 a parent's "try harder, honey", a
        child's "What is this game?", "Who did that?", "You're in my heart"
        and two fragments of the creator's call with a colleague were all
        answered aloud. The creator: an unplaced voice gets no reply unless
        it names Sim. A question missed this way costs one repeat with the
        name in it; an answer into someone's meeting costs more.

        Only with speaker recognition on -- without it every voice is
        unplaced and Sim would answer nobody. Off with
        `[voice] unplaced_needs_name = false`."""
        if not self._config.unplaced_needs_name or speaker:
            return False
        if self._in_conversation(speaker):
            return False
        if self._speakers is None or self._embedder is None:
            return False
        if not self._speakers.has_voices():
            # Nobody is enrolled, so nobody can ever be placed: the rule would
            # silence the whole house. Live 2026-09-15, minutes after it was
            # written -- the creator deleted his own voice while clearing a
            # bogus "Myself" entry, and every turn became unplaced.
            return False
        if int(self._config.introduce_after_turns) > 0:
            # Asking a new voice its name counts its turns on the reply path
            # (`_maybe_ask_who`), so a house that has switched that on must
            # still hear those turns. Off by default since 2026-09-13.
            return False
        now = self._now()
        if addressed(text, since_sim_spoke_s=-1.0, exchange_window_s=0.0):
            return False
        # Sim asked something a moment ago and this may be the answer to it.
        if 0.0 <= now - self._sim_spoke_at <= self._config.exchange_window_s and self._last_ask_addressed:
            return False
        # Recognition flickers, and this rule then silences the person who
        # IS talking to Sim, mid-sentence. A voice whose closest match is
        # someone Sim is already mid-conversation with -- scoring high
        # enough that only the margin kept it unnamed -- is that person on
        # a bad frame, not a stranger.
        #
        # Deliberately four conditions, because the failure it must not
        # re-open is the work call. The closest voice must be NAMED; Sim
        # must have answered that name inside `conversation_window_s`
        # (which, since "someone" stopped being a person, answering a
        # stranger can no longer establish); the score must reach the
        # book's `lean`, so a colleague at 0.18 never qualifies; and Sim
        # must have spoken within `exchange_window_s`, so this lasts
        # seconds rather than the conversation window's three minutes.
        if getattr(self._config, "unplaced_follows_conversation", True):
            ident = self.last_identification
            closest = str(getattr(ident, "runner_up", "") or "") if ident is not None else ""
            lean = float(getattr(self._speakers, "lean", 0.45) or 0.45)
            score = float(getattr(ident, "runner_up_score", 0.0) or 0.0) if ident is not None else 0.0
            if (closest and score >= lean and self._in_conversation(closest)
                    and 0.0 <= now - self._sim_spoke_at <= self._config.exchange_window_s):
                self._log("debug", "voice.unplaced_is_who_sim_is_talking_to",
                          closest=closest, score=round(score, 3))
                return False
        self._quiet_on["someone"] = now
        self._room.append(("someone", text, now, "aside"))
        self._log_overheard("someone", text)
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "turn": turn_id, "quiet": True,
            "reason": "a voice Sim cannot place, not naming Sim: say \"Sim\" and it will answer"})
        self.stats.turns += 1
        self.turns.state = LISTENING
        await self._announce(self.turns.state)
        return True

    async def _background(self, turn_id: int, speaker: str, text: str) -> bool:
        """True when these words are more of the background: a voice Sim
        cannot place, not naming Sim and not answering it, after the model
        has already stayed quiet on such a voice at least
        `background_after_quiet` times in `background_window_s`. The TV
        interview it had rightly ignored twice got an answer on its third
        fragment (2026-09-14). Off with `[voice] background_quiet = false`."""
        if not self._config.background_quiet or speaker:
            return False
        now = self._now()
        if addressed(text, since_sim_spoke_s=-1.0, exchange_window_s=0.0):
            return False
        # A follow-up counts only when the exchange began properly: Sim
        # answering a stray fragment of the TV must not make the next
        # fragment "an exchange under way" -- that is how one mistaken
        # answer turned into answering every fragment after it.
        in_exchange = 0.0 <= now - self._sim_spoke_at <= self._config.exchange_window_s
        if in_exchange and self._last_ask_addressed:
            return False
        recent = [at for at in self._quiet_unknown if now - at <= self._config.background_window_s]
        if len(recent) < int(self._config.background_after_quiet):
            return False
        self._quiet_unknown.append(now)
        self._room.append(("someone", text, now, "aside"))
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "turn": turn_id, "quiet": True,
            "reason": "an unknown voice keeps talking without naming Sim: the TV, a podcast or the radio"})
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
        # Takes gathered by meeting someone are takes all the same; filing
        # only `voice enroll` would lose every one of these.
        if vector is not None and intro.name:
            facts = self._facts(turn_id)
            self._speakers.keep_take(intro.name, facts["pcm"], text=text,
                                     seconds=facts["speech_s"], source="introduce")
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
        from simorgh.contracts.tidy import tidy

        tidied = await tidy(self._pipeline._bus, text,  # noqa: SLF001 -- the same bus the ask goes on
                            recent=[self._last_user_text, self._pipeline.last_said])
        if tidied.changed:
            await self._pipeline._publish(topics.VOICE_TRANSCRIPT, {  # noqa: SLF001
                "text": tidied.text, "confidence": 1.0, "seconds": 0.0, "engine": "tidy",
                "device": self._config.device, "corrected": True, "turn": turn_id})
            self._last_user_text = tidied.text
        return tidied.text

    def _identity_claim(self, text: str) -> str:
        """The name in "no, this is Ira" / "I'm Iris" / "it's Saeed", when the
        book knows it; "" otherwise."""
        m = _I_AM.search(text or "")
        if not m or self._speakers is None:
            return ""
        name = m.group(1)
        person = self._speakers.get(name)
        return person.name if person is not None else ""

    async def _take_correction(self, turn_id: int, text: str, name: str, vector, clock: TurnClock) -> None:
        try:
            _person, note = self._speakers.enroll(name, vector, insist=True)
        except Exception as exc:  # noqa: BLE001
            note = f"refused: {exc}"
        self.last_speaker = name
        self._speakers.heard(name)
        self._log("info", "voice.identity_corrected", name=name, note=note)
        said = f"Got it, {name}. I'll know your voice better now." if not note else f"Got it, {name}."
        clock.reply_at = self._now()
        await self._speak_reply(turn_id, said, clock, Context(user_text=text))

    def _who_said(self, words: str, *, within_s: float = 600.0) -> str:
        """Who said `words` lately, from the room's own record: a name, a
        voice nobody could place, or nobody."""
        import difflib

        wanted = re.sub(r"[^\w\s']", " ", (words or "").lower()).split()
        wanted_text = " ".join(wanted)
        if not wanted_text:
            return "Who said what? Say the words."
        now = self._now()
        best: tuple[float, str] | None = None
        for who, said, at, kind in reversed(self._room):
            if kind == "reply" or now - at > within_s or who == "Sim":
                continue
            heard = re.sub(r"[^\w\s']", " ", said.lower())
            if wanted_text in heard:
                score = 1.0
            elif set(wanted) <= set(heard.split()):
                score = 0.95      # "I don't care" in "I honestly don't care about that"
            else:
                score = difflib.SequenceMatcher(None, wanted_text, heard).ratio()
            if score >= 0.6 and (best is None or score > best[0]):
                best = (score, who)
        if best is None:
            return f"I didn't catch anyone saying \"{words.strip()}\" lately."
        who = best[1]
        if who == "someone":
            return f"I heard \"{words.strip()}\" but couldn't place the voice."
        return f"That was {who}."

    async def _answer_who(self, turn_id: int, text: str, identification, clock: TurnClock) -> None:
        """The identification, said plainly, without a model call."""
        if identification is not None and identification.name:
            who = identification.name
            said = (f"That sounds like {who}, though I'm not certain." if identification.probable
                    else f"That's {who}.")
        else:
            reason = getattr(identification, "reason", "") if identification is not None else ""
            said = "I don't recognise this voice." + (" Nobody is enrolled yet." if "nobody" in reason else "")
        clock.reply_at = self._now()
        await self._speak_reply(turn_id, said, clock, Context(user_text=text))

    async def _obey(self, turn_id: int, command: str, *, speaker: str = "", clock=None) -> None:
        """"Stop", "be quiet", "voice off", "restart": done here and now,
        the model never hears of it. Playback is cut, the floor goes back
        to listening (or, for off/mute, to the service to close).

        `restart` (the creator, by voice, 2026-09-15: "it should be able to
        restart itself") publishes the same `system.restart` the typed
        command does, and only for a voice the house knows: an advert
        saying "restart" must not take Sim down, the same reason as
        `unplaced_voice_refusal`. Refused aloud when this process was not
        started by `simloader.py` -- nothing would bring Sim back, and the
        person asking is not at a keyboard."""
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
        if command == RESTART:
            await self._restart(turn_id, speaker=speaker, clock=clock)
            return
        if command in (OFF, MUTE):
            # The service owns on/off; this session is about to be closed by it.
            await self._pipeline._publish(topics.VOICE_CONTROL_REQUEST, {  # noqa: SLF001
                "action": "off" if command == OFF else "mute"})

    async def _restart(self, turn_id: int, *, speaker: str, clock=None) -> None:
        """Say one line, then publish `system.restart` -- what
        `interface/dispatch.py` does for the typed command.
        `self_check_passed=True` because the loader's own gate is what
        verifies the source before it runs."""
        import os

        clock = clock or self._clocks.get(turn_id) or TurnClock(turn_id=turn_id)
        if not speaker:
            clock.reply_at = self._now()
            await self._speak_reply(turn_id, "A restart is only for a voice I know. Say it again "
                                             "and I'll hear who you are.", clock, Context(is_error=True))
            return
        if not os.environ.get("SIMORGH_LOADER_NOTES"):
            clock.reply_at = self._now()
            await self._speak_reply(turn_id, "I wasn't started through the loader, so a restart would stop me "
                                             "for good. Run sim.sh and I'll come back.", clock, Context(is_error=True))
            return
        clock.reply_at = self._now()
        await self._speak_reply(turn_id, "Restarting now.", clock, Context())
        self._log("info", "voice.restart", speaker=speaker, turn=turn_id)
        # Interface runs it, not voice: `system.restart` may only be published
        # by interface, kernel or execution (contracts/topics.py), so doing it
        # here failed with "policy: voice may not publish system.restart" and
        # the restart never happened (live 2026-09-15). The typed `restart`
        # command is exactly what this asks for.
        await self._pipeline._publish(topics.UI_COMMAND_REQUEST, {  # noqa: SLF001
            "line": "restart", "requested_by": f"{speaker} by voice"})

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

    async def _stay_quiet(self, turn_id: int, reason: str = "") -> None:
        """The model heard words that were not for it. Nothing is said;
        the floor goes back to listening, and the screen shows why
        there was no reply."""
        actions = self.turns.reply_ready(turn_id)
        speak = next((a for a in actions if a.kind == Actions.SPEAK), None)
        if speak is not None:
            # A response was minted; it is over before it started.
            self.turns.handle_playback_state(PlaybackState("finished", str(speak.response_id)))
        # Only the turn still owed an answer may hand the floor back. A
        # superseded turn staying quiet used to flip THINKING to LISTENING
        # while a NEWER turn was the one being thought about, and that
        # turn's real answer was then refused as "the session is
        # listening" (2026-09-18 evaluation, V1).
        if self.turns.state == THINKING and self.turns.asked_turn in (0, turn_id):
            self.turns.state = LISTENING if self.turns.auto_listen else self.turns.state
        await self._announce(self.turns.state)
        self._answered.discard(turn_id)
        self._acknowledged.discard(turn_id)
        self._clocks.pop(turn_id, None)
        self._log("info", "voice.stayed_quiet", turn=turn_id, reason=reason)
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": "", "seconds": 0.0, "engine": "", "device": self._config.device, "interrupted": False,
            "quiet": True, "turn": turn_id, **({"reason": reason} if reason else {})})

    async def _on_tool_started(self, tool: str, recent_p95_ms: int) -> None:
        """A tool that is known to be slow has started (stage 3 item 5).

        The wait a person in the kitchen sits through is usually the
        tool, not the model: a `web_fetch` or a `run_tests` is seconds
        of silence after Sim has already said "okay". So it says what it
        is doing, once per turn -- twice would be the tic the creator
        objected to, and a tool nobody has timed yet says nothing,
        because an unknown duration is not evidence of a slow one.
        """
        # The typed field, not a `getattr` with its own fallback: the
        # fallback here said 0 -- never fill -- while the default has
        # said 2000 since the twenty-second silences of 2026-09-20, so
        # a config object without the attribute would have silently
        # switched the fillers back off. `test_config_is_read_typed`
        # exists for exactly this and caught it in the full suite.
        over = int(self._config.filler_over_ms or 0)
        if over <= 0 or recent_p95_ms < over or not self._config.backchannel:
            return
        turn_id = self.turns.turn_id
        if self.turns.state != THINKING or turn_id in self._answered or turn_id in self._filled:
            return
        self._filled.add(turn_id)
        language = language_of(self._last_user_text or "")
        if await self._say_aside(f"tool-{turn_id}-{tool}", self._backchannel.looking(language)):
            self._last_aside_at = self._now()

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
        mode = str(self._config.expressive_lane or "auto")
        if mode == "off":
            return "fast"
        if mode == "always" or explicit:
            return "expressive"
        if not spoken_turn:
            return "fast"
        # `expressive_min_chars` is 0 unless someone sets it: the one long
        # spoken reply that took the slow lane held the speech lock for
        # 78 s and every reply behind it waited or was dropped (the
        # creator, 2026-09-13: "I didn't hear anything from you").
        threshold = int(self._config.expressive_min_chars or 0)
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
                # Before playing, for the same reason as a reply: an aside
                # is short, and its echo can be transcribed and judged
                # while the speaker is still saying it.
                self._pipeline.recent_said.append(text)
                await self._play(self._tts.synthesise_stream(request), request_id=request.request_id,
                                 chunk_timeout=self._tts.chunk_timeout(request))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log("warning", "voice.aside_failed", error=repr(exc))
            return False
        # An aside is a thing Sim said, and Sim must remember saying it.
        # It did not: "One more second." came back through the mic as the
        # next turn, took the floor, and the real answer -- 28 seconds in
        # the making -- was dropped as stale (live 2026-09-17, the
        # creator: "sim skipped audio response"). `last_said` is left
        # alone: that is the last real reply, which `repeat` and the
        # model's context both read.
        self._sim_spoke_at = self._now()
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": text, "seconds": 0.0, "engine": getattr(self._tts, "last_engine", "") or self._tts.name,
            "device": self._config.device, "interrupted": False, "aside": True, "turn": self.turns.turn_id,
            "register": delivery.register})
        return True

    async def _speak_live(self, turn_id: int, speak, live, first: str, clock: TurnClock, context: Context) -> None:
        """`_speak_reply` for a reply being written (stage 3 item 4): the
        request reads its pieces from `live.queue`; what was said is known
        only when the stream ends."""
        response_id = str(speak.response_id)
        self._answered.discard(turn_id)
        delivery = self._delivery_for(context.user_text, first, is_error=False, tone=live.tone)
        lane = self._lane_for(first, spoken_turn=True)
        request = TtsRequest(request_id=response_id, pieces=(), live=live.queue, voice=self._config.tts_voice,
                             speed=delivery.speed, gain=delivery.gain,
                             tone=live.tone or (delivery.register if delivery.register in ("warm", "bright") else ""),
                             lane=lane)
        self._pipeline.speaking = True

        def _first_audio(seconds: float) -> None:
            clock.first_audio_at = self._now()

        try:
            clock.lock_wait_at = self._now()
            async with self._pipeline.speech_lock:
                clock.lock_got_at = self._now()
                report = await self._play(self._tts.synthesise_stream(request), request_id=response_id,
                                          on_first_audio=_first_audio)
        except Exception as exc:  # noqa: BLE001 -- a reply that could not be spoken is logged, not fatal
            self._log("warning", "voice.reply_not_spoken", error=repr(exc))
            self.turns.handle_playback_state(PlaybackState("finished", response_id))
            if self.turns.state == THINKING:
                self.turns.state = LISTENING
                await self._announce(self.turns.state)
            self._pipeline.speaking = False
            live.close()
            return
        live.close()
        self._pipeline.speaking = False
        self._sim_spoke_at = self._now()
        await self._report_synthesis(report)
        said = live.said
        self._pipeline.last_said = said
        self.stats.turns += 1
        metrics = clock.metrics(report)
        metrics["streamed"] = True
        metrics["lane"] = lane
        self.stats.last_metrics = metrics
        self._record_stage_spans(clock, report)
        engine = getattr(self._tts, "last_engine", "") or self._tts.name
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": said, "seconds": report.seconds, "engine": engine, "device": self._config.device,
            "interrupted": report.interrupted, "turn": turn_id, "response": speak.response_id,
            **({"metrics": metrics} if self._config.diagnostics else {}),
        })

    async def _speak_reply(self, turn_id: int, reply: str, clock: TurnClock, context: Context,
                           live=None) -> None:
        actions = self.turns.reply_ready(turn_id)
        while any(a.kind == Actions.HOLD_REPLY for a in actions):
            # The person may be starting to talk: wait for that to settle
            # -- a blip is discarded and the reply goes ahead; real
            # speech becomes the next turn and this reply is dropped.
            hold = next(a for a in actions if a.kind == Actions.HOLD_REPLY)
            self._settled.clear()
            if "late reply" in hold.reason:
                # An older answer is being said first; this one follows
                # when it ends (playback finished sets `_settled`).
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._settled.wait(), timeout=120.0)
                actions = self.turns.reply_ready(turn_id)
                continue
            try:
                await asyncio.wait_for(self._settled.wait(),
                                       timeout=float(getattr(self._config, "hold_reply_max_s", 1.5) or 1.5))
            except asyncio.TimeoutError:
                # Nothing settled the hold: the candidate turn is neither a
                # turn nor a blip yet. Ask once more; if it still holds,
                # speak anyway -- a late answer beats one lost in silence
                # (observer, 2026-09-13: THINKING for 36 s, nothing said).
                actions = self.turns.reply_ready(turn_id)
                if any(a.kind == Actions.HOLD_REPLY for a in actions):
                    self._log("info", "voice.hold_expired", turn=turn_id)
                    self.turns.handle_playback_state(PlaybackState("started", "0"))  # no-op nudge; the manager may ignore it
                    actions = [a for a in actions if a.kind != Actions.HOLD_REPLY] or actions
                    if not any(a.kind == Actions.SPEAK for a in actions):
                        self.turns.state = THINKING
                        actions = self.turns.reply_ready(turn_id)
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

        if live is not None:
            # A reply still being written: the sentences come from the
            # stream, which already applies the spoken-length cap; delivery
            # is chosen from the first of them.
            first = live.spoken[0] if live.spoken else ""
            await self._speak_live(turn_id, speak, live, first, clock, context)
            return
        tone, reply = split_tone(reply)
        # "Go on" reads the part the last reply cut, rather than
        # asking the model to produce it again -- which would give a
        # different continuation and lose the thread of the story
        # (the creator, 2026-09-20: Sim read one line of the Arabian
        # Nights and pointed at the screen).
        if asked_to_continue(context.user_text) and self._unspoken:
            reply, self._unspoken = self._unspoken, ""
            context = replace(context, user_text="read me the rest")
        plan = self._planner.plan(reply, context)
        self._unspoken = self._planner.unspoken
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
        from .pronounce import strip_marks

        said = strip_marks(plan.text, for_voice=False)
        # Remembered BEFORE the audio goes out, not after. The microphone
        # hears the opening words while playback is still running, and the
        # echo guard runs on whatever `recent_said` holds at that moment.
        # Live turn 82, 2026-09-17: 2.10 s transcribed, 1.45 s of it Sim's
        # own reply, and its guard ran 0.27 s before this append used to be
        # reached -- so the ring was asked about a reply it had not yet
        # been told about. "Nice counting, Iris" came back as Iris's turn,
        # was answered ("Hey, that's my line!"), and the speaker book
        # named her from the 0.87 s of clean frames beside the echo.
        self._pipeline.recent_said.append(said)
        self._pipeline.speaking = True

        def _first_audio(seconds: float) -> None:
            clock.first_audio_at = self._now()

        try:
            clock.lock_wait_at = self._now()
            async with self._pipeline.speech_lock:
                clock.lock_got_at = self._now()
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
        metrics.update(self._scored.pop(turn_id, {}))
        named = self._named.pop(turn_id, None)
        if named is None:      # a turn that never went through _ask_and_speak
            named = (self.last_speaker if self.last_identification is not None
                     and self.last_identification.name else "")
        self.stats.last_metrics = metrics
        self._record_stage_spans(clock, report)
        engine = getattr(self._tts, "last_engine", "") or self._tts.name
        await self._pipeline._publish(topics.VOICE_SPOKEN, {  # noqa: SLF001
            "text": said, "seconds": report.seconds, "engine": engine, "device": self._config.device,
            "interrupted": report.interrupted, "turn": turn_id, "response": speak.response_id,
            **({"metrics": metrics} if self._config.diagnostics else {}),
        })
        await self._pipeline._record(VoiceTurn(  # noqa: SLF001
            session_id=f"turn-{turn_id}", device=self._config.device, speaker=named, heard=clock.text,
            confidence=clock.confidence, said=said,
            heard_at=(self._clock.now() if self._clock is not None else time.time()) - max(0.0, self._now() - clock.speech_end) if clock.speech_end else 0.0,
            answered_at=self._clock.now() if self._clock is not None else time.time(),
            engine_stt=clock.engine_stt, engine_tts=engine, language=clock.language,
            metrics=metrics if self._config.diagnostics else {},
            segments=list(getattr(self, "_last_segments", []) or []),
        ))
        # A turn addressed to Sim belongs in the record too. Without it the
        # store held only asides, so "summarize what Iris said in the last
        # hour" found nothing while the words sat in `voice:turns` -- a
        # different stream, owned by Voice, that Execution's tool may not
        # read (the creator asked three times, 2026-09-16). The person's
        # words only: Sim's own replies are recoverable elsewhere and would
        # double a store that keeps a family's conversation.
        if clock.text:
            self._log_overheard(named or "someone", clock.text, kind="said")
        self._last_segments = []
        self._clocks.pop(turn_id, None)

    async def _wait_for_the_floor(self) -> bool:
        """Wait, briefly, for somebody who is mid-sentence to finish.

        `say()` is how everything Sim decided to say on its own
        reaches the room -- a check-in, a camera, a reminder, a share
        -- and it took the speech lock and talked, whatever the state
        of the room. A person mid-sentence was talked over by a
        machine that had been waiting all evening for something to
        mention (stage 6 item 6, the HOLD this plan has asked for
        since it was written).

        Bounded by `hold_unprompted_max_s`, and then it speaks
        anyway: a safety alert that waits for a quiet room is a
        safety alert nobody hears. A reply to a spoken turn does not
        come through here -- it has `HOLD_REPLY` and a much shorter
        patience, because somebody is waiting for that one.
        """
        limit = float(self._config.hold_unprompted_max_s or 0.0)
        if limit <= 0.0 or self.turns.state not in (USER_SPEAKING, THINKING):
            return True
        deadline = self._now() + limit
        while self._now() < deadline:
            await asyncio.sleep(0.1)
            if self.turns.state not in (USER_SPEAKING, THINKING):
                return True
        self._log("info", "voice.spoke_over_the_floor", state=self.turns.state, waited_s=round(limit, 1))
        return False

    async def say(self, text: str, *, request_id: str = "", lane: str = "") -> str:
        """Speak something that is not a reply to a spoken turn -- a typed
        turn's reply, `voice test` -- THROUGH the session, so the turn
        manager knows Sim is talking and the microphone's echo of it is
        treated as Sim, not as a person. Returns what was said."""
        plan = self._planner.plan(text, Context())
        request = TtsRequest(request_id=request_id or f"say-{uuid.uuid4().hex[:8]}",
                             pieces=tuple((c.text, c.pause_ms) for c in plan.chunks),
                             voice=self._config.tts_voice, speed=self._config.tts_speed,
                             lane=self._lane_for(plan.text, spoken_turn=False, explicit=lane == "expressive"))
        await self._wait_for_the_floor()
        entered_from = self.turns.state
        if entered_from == LISTENING:
            self.turns.state = AGENT_SPEAKING
            self.turns.speaking_response = 0
            await self._announce(self.turns.state)
        from .pronounce import strip_marks

        shown = strip_marks(plan.text, for_voice=False)
        self._pipeline.recent_said.append(shown)   # before playing; see the reply path
        self._pipeline.speaking = True
        try:
            async with self._pipeline.speech_lock:
                report = await self._play(self._tts.synthesise_stream(request), request_id=request.request_id,
                                 chunk_timeout=self._tts.chunk_timeout(request))
        finally:
            self._pipeline.speaking = False
            self._sim_spoke_at = self._now()
            if self.turns.state == AGENT_SPEAKING and entered_from == LISTENING:
                self.turns.state = LISTENING
                await self._announce(self.turns.state)
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

        try:
            return await self._player.play_stream(chunks, request_id=request_id, on_play=_reference, **kw)
        finally:
            # Keep whatever gain this reply managed to measure, even a
            # short one's few frames: an unlearnt gain means an
            # infinite bar at the start of the NEXT reply, and Sim is
            # asked to answer briefly.
            self._echo.settle()

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
        if state.state in ("finished", "stopped"):
            self._settled.set()      # a reply held behind a late one may go ahead
        if before != self.turns.state:
            await self._announce(self.turns.state)


__all__ = ["SessionStats", "TurnClock", "VoiceSession"]
