"""The `voice` Subsystem: engines, probes, and the CLI's commands.

Boot is cheap and never fails for want of audio: engines are opened on
first use (`voice on`, `voice listen`, `voice test`), because loading a
recogniser is seconds and a gigabyte, and `voice status` on a machine
with no microphone should still answer. What IS done at boot is the
presence check -- which recogniser, synthesiser, capture and playback
paths this machine has -- written to the same `capabilities` ledger
stream Execution's probes use, so `capabilities` lists voice beside
Docker and Chromium and says what to install.
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sys
from dataclasses import asdict
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Context, Health

from .api import VoiceState
from .config import Config
from .pipeline import Pipeline
from .stt import open_recogniser
from .tts import open_synthesiser
from .vad import open_detector

NAME = "voice"
VERSION = "0.1.0"
CAPABILITIES_STREAM = "capabilities"

_CONSUMES = (
    topics.VOICE_STATUS_REQUEST, topics.VOICE_CONTROL_REQUEST, topics.VOICE_SPEAK_REQUEST,
    topics.VOICE_LISTEN_REQUEST, topics.VOICE_VOICES_REQUEST, topics.VOICE_DEVICES_REQUEST,
    topics.VOICE_MODELS_REQUEST, topics.VOICE_BENCH_REQUEST,
    topics.TURN_COMPLETED, topics.TASK_FAILED, topics.TASK_BLOCKED,
)
_PRODUCES = (
    topics.PERCEPT_TEXT_RECEIVED, topics.VOICE_LISTENING, topics.VOICE_TRANSCRIPT, topics.VOICE_SPOKEN,
    topics.VOICE_STATUS_REPLY, topics.VOICE_CONTROL_REPLY, topics.VOICE_SPEAK_REPLY,
    topics.VOICE_LISTEN_REPLY, topics.VOICE_VOICES_REPLY, topics.VOICE_DEVICES_REPLY,
    topics.VOICE_MODELS_REPLY, topics.VOICE_BENCH_REPLY,
)


def presence_probes() -> list[dict]:
    """What is installed, without loading any of it. Each entry is the
    shape `execution/capabilities.py` writes, so `capabilities` renders
    them the same way."""
    def spec(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    stt = []
    if spec("faster_whisper"):
        stt.append("faster-whisper")
    if shutil.which("whisper-cli") or shutil.which("whisper-cpp"):
        stt.append("whisper.cpp")
    tts = []
    if spec("kokoro_onnx"):
        tts.append("kokoro")
    if spec("piper"):
        tts.append("piper")
    if sys.platform == "darwin" and shutil.which("say"):
        tts.append("say")
    mic = []
    if spec("sounddevice"):
        mic.append("sounddevice")
    if shutil.which("ffmpeg"):
        mic.append("ffmpeg")
    out = []
    if spec("sounddevice"):
        out.append("sounddevice")
    if shutil.which("afplay") or shutil.which("ffplay"):
        out.append("afplay" if shutil.which("afplay") else "ffplay")
    return [
        {"name": "speech-to-text", "ok": bool(stt), "detail": ", ".join(stt) or "none installed",
         "cost": "free", "tools": ["voice"], "fix": "" if stt else "pip install faster-whisper  (or: brew install whisper-cpp)", "missing": [] if stt else ["faster_whisper"]},
        {"name": "text-to-speech", "ok": bool(tts), "detail": ", ".join(tts) or "none installed",
         "cost": "free", "tools": ["voice"], "fix": "" if tts else "pip install kokoro-onnx", "missing": [] if tts else ["kokoro_onnx"]},
        {"name": "microphone", "ok": bool(mic), "detail": ", ".join(mic) or "no capture path",
         "cost": "free", "tools": ["voice"], "fix": "" if mic else "pip install sounddevice  (or install ffmpeg)", "missing": [] if mic else ["sounddevice"]},
        {"name": "audio-playback", "ok": bool(out), "detail": ", ".join(out) or "no playback path",
         "cost": "free", "tools": ["voice"], "fix": "" if out else "pip install sounddevice  (or install ffmpeg)", "missing": [] if out else ["sounddevice"]},
    ]


class Service:
    name = NAME
    version = VERSION
    consumes = _CONSUMES
    produces = _PRODUCES

    def __init__(self, config: Config | None = None, *, microphone=None, speaker=None,
                 recogniser=None, synthesiser=None) -> None:
        self._config_from_caller = config
        self.config = config or Config()
        self._ctx: Context | None = None
        self._subs: list = []
        self._pipeline: Pipeline | None = None
        self._injected = {"microphone": microphone, "speaker": speaker, "recogniser": recogniser,
                          "synthesiser": synthesiser}
        self._loop_task: asyncio.Task | None = None
        self._loop_stop = asyncio.Event()
        # The streaming conversation (session.py), when the microphone
        # can stream; the older capture-then-answer loop otherwise.
        self._session = None
        self._enabled = False
        self._muted = False
        self._problems: list[str] = []
        self._engine_names = {"stt": "", "tts": "", "mic": "", "spk": "", "vad": ""}

    # ---------------------------------------------------------- lifecycle
    async def start(self, ctx: Context) -> None:
        self._ctx = ctx
        if self._config_from_caller is None and ctx.config:
            self.config = Config.from_mapping(dict(ctx.config))
        handlers = {
            topics.VOICE_STATUS_REQUEST: self._on_status,
            topics.VOICE_CONTROL_REQUEST: self._on_control,
            topics.VOICE_SPEAK_REQUEST: self._on_speak,
            topics.VOICE_LISTEN_REQUEST: self._on_listen,
            topics.VOICE_VOICES_REQUEST: self._on_voices,
            topics.VOICE_DEVICES_REQUEST: self._on_devices,
            topics.VOICE_MODELS_REQUEST: self._on_models,
            topics.VOICE_BENCH_REQUEST: self._on_bench,
        }
        for topic, handler in handlers.items():
            self._subs.append(await ctx.bus.subscribe(topic, handler))
        if self.config.speak_replies:
            self._subs.append(await ctx.bus.subscribe(topics.TURN_COMPLETED, self._on_any_reply))
        await self._write_probes()
        ctx.logger.info("voice.started", enabled=self.config.enabled, stt=self.config.stt, tts=self.config.tts)
        if self.config.enabled:
            ok, why = await self._turn_on()
            if not ok:
                ctx.logger.warning("voice.not_enabled", reason=why)

    async def stop(self) -> None:
        await self._turn_off()
        if self._pipeline is not None:
            await self._pipeline.stop()
            self._pipeline = None
        for sub in self._subs:
            await sub.unsubscribe()
        self._subs = []

    async def health(self) -> Health:
        if not self._enabled:
            return Health.ok("off" if not self._problems else "; ".join(self._problems))
        if self._problems:
            return Health("degraded", "; ".join(self._problems))
        return Health.ok("listening" if not self._muted else "muted")

    # ------------------------------------------------------------ engines
    async def _pipeline_ready(self) -> tuple[Pipeline | None, str]:
        """Open the engines on first use. A missing one is named, with
        what to install, and nothing else is opened."""
        if self._pipeline is not None:
            return self._pipeline, ""
        assert self._ctx is not None
        cfg = self.config
        repo_root = Path(".")
        problems: list[str] = []
        stt = self._injected["recogniser"]
        if stt is None:
            stt, why = await asyncio.to_thread(open_recogniser, cfg, repo_root=repo_root)
            if stt is None:
                problems.append(why)
        tts = self._injected["synthesiser"]
        if tts is None:
            tts, why = open_synthesiser(cfg)
            if tts is None:
                problems.append(why)
        mic = self._injected["microphone"]
        if mic is None:
            if cfg.microphone == "fake":
                from .fakes import FakeMicrophone
                mic = FakeMicrophone()
            else:
                from .audio import open_microphone
                mic, why = open_microphone(cfg.microphone)
                if mic is None:
                    problems.append(why)
        spk = self._injected["speaker"]
        if spk is None:
            if cfg.speaker == "fake":
                from .fakes import FakeSpeaker
                spk = FakeSpeaker()
            else:
                from .audio import open_speaker
                spk, why = open_speaker(cfg.speaker)
                if spk is None:
                    problems.append(why)
        detector_factory = lambda: open_detector(cfg.vad, threshold=cfg.vad_threshold)[0]  # noqa: E731
        vad_name = open_detector(cfg.vad, threshold=cfg.vad_threshold)[0].name
        self._problems = problems
        self._engine_names = {"stt": getattr(stt, "name", ""), "tts": getattr(tts, "name", ""),
                              "mic": getattr(mic, "name", ""), "spk": getattr(spk, "name", ""), "vad": vad_name}
        if problems:
            return None, "; ".join(problems)
        self._pipeline = Pipeline(
            bus=self._ctx.bus, clock=self._ctx.clock, logger=self._ctx.logger, ledger=self._ctx.ledger,
            config=cfg, microphone=mic, speaker=spk, recogniser=stt, synthesiser=tts,
            detector_factory=detector_factory, repo_root=repo_root,
        )
        await self._pipeline.start()
        return self._pipeline, ""

    async def _turn_on(self) -> tuple[bool, str]:
        pipeline, why = await self._pipeline_ready()
        if pipeline is None:
            return False, why
        self._enabled = True
        self._muted = False
        if self._loop_task is None or self._loop_task.done():
            self._loop_stop = asyncio.Event()
            mic = pipeline._mic  # noqa: SLF001 -- the engines the pipeline was opened with
            if hasattr(mic, "stream"):
                from .session import VoiceSession

                self._session = VoiceSession(
                    pipeline=pipeline, config=self.config, microphone=mic, speaker=pipeline._speaker,  # noqa: SLF001
                    recogniser=pipeline._stt, synthesiser=pipeline._tts,  # noqa: SLF001
                    detector_factory=pipeline._detector_factory,  # noqa: SLF001
                    clock=self._ctx.clock if self._ctx else None, logger=self._ctx.logger if self._ctx else None,
                )
                self._loop_task = asyncio.create_task(self._session.run(self._loop_stop), name="voice-session")
            else:
                self._loop_task = asyncio.create_task(pipeline.run_loop(self._loop_stop), name="voice-loop")
        return True, ""

    async def _turn_off(self) -> None:
        self._enabled = False
        self._loop_stop.set()
        if self._loop_task is not None and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 -- shutdown must not raise
                pass
        self._loop_task = None

    def _state(self) -> dict:
        p = self._pipeline
        session = self._session
        listening = bool(p and p.listening and not self._muted)
        turns = p.turns if p else 0
        if session is not None and self._enabled:
            listening = session.state in ("listening", "user_speaking") and not self._muted
            turns = session.stats.turns
        state = VoiceState(
            enabled=self._enabled, listening=listening, muted=self._muted,
            speaking=bool(p and p.speaking), stt=self._engine_names["stt"], tts=self._engine_names["tts"],
            device=self.config.device, turns=turns, last_heard=p.last_heard if p else "",
            last_said=p.last_said if p else "", problems=list(self._problems),
        )
        out = asdict(state)
        if session is not None:
            out["state"] = session.state
            out["interruptions"] = session.stats.interruptions
            out["warmup_s"] = round(session.stats.warmup_seconds, 3)
            out["last_interruption_s"] = session.stats.last_interruption_s
            out["partial"] = session.partial
            if self.config.diagnostics and session.stats.last_metrics:
                out["metrics"] = dict(session.stats.last_metrics)
        return out

    # ----------------------------------------------------------- handlers
    async def _reply(self, message, type_: str, payload: dict) -> None:
        assert self._ctx is not None
        if message.reply_to:
            await self._ctx.bus.reply(message, type=type_, payload=payload)

    async def _on_status(self, message) -> None:
        await self._reply(message, topics.VOICE_STATUS_REPLY, self._state())

    async def _on_control(self, message) -> None:
        action = str(message.payload.get("action") or "")
        ok, detail = True, ""
        if action == "on":
            ok, detail = await self._turn_on()
        elif action == "off":
            await self._turn_off()
        elif action == "mute":
            self._muted = True
            await self._turn_off()
            self._muted = True
        elif action == "unmute":
            self._muted = False
            ok, detail = await self._turn_on()
        elif action == "set":
            ok, detail = await self._set(str(message.payload.get("key") or ""), str(message.payload.get("value") or ""))
        elif action in ("barge_on", "barge_off", "aec_on", "aec_off"):
            from dataclasses import replace
            if action in ("barge_on", "barge_off"):
                want = action == "barge_on"
                self.config = replace(self.config, barge_in=want)
                detail = f"barge-in {'on -- speak to interrupt' if want else 'off -- Sim finishes before it listens'}"
            else:
                from .aec import available as _aec_available
                ok_aec, why = _aec_available()
                if action == "aec_on" and not ok_aec:
                    detail, ok = f"echo cancellation needs {why}", False
                else:
                    self.config = replace(self.config, aec=(action == "aec_on"))
                    detail = ("echo cancellation on -- Sim's own voice is subtracted before deciding you "
                              "spoke (experimental)" if action == "aec_on" else "echo cancellation off -- back to the level gate")
            if self._pipeline is not None:
                self._pipeline._config = self.config  # noqa: SLF001 -- the live pipeline reads it
        else:
            ok, detail = False, f"unknown action {action!r} (on | off | mute | unmute | set)"
        await self._reply(message, topics.VOICE_CONTROL_REPLY, {"ok": ok, "detail": detail, **self._state()})

    async def _set(self, key: str, raw: str) -> tuple[bool, str]:
        """`voice set key value`: a safe setting, applied live and written
        to the data directory's simorgh.toml so it survives a restart."""
        from . import settings

        if not key:
            rows = "; ".join(f"{k} ({t})" for k, t, _h in settings.describe())
            return True, f"settings you can change here: {rows}"
        value, problem = settings.parse(key, raw)
        if problem:
            return False, problem
        self.config = settings.apply(self.config, key, value)
        if self._pipeline is not None:
            self._pipeline._config = self.config  # noqa: SLF001 -- the live pipeline reads it
        where = ""
        if self._ctx is not None and getattr(self._ctx, "data_dir", None):
            path = Path(self._ctx.data_dir).parent / "simorgh.toml"
            try:
                settings.persist(path, key, value)
                where = f"; saved to {path}"
            except OSError as exc:
                where = f"; NOT saved ({exc})"
        restarted = ""
        if self._enabled and key not in ("keep_transcripts", "diagnostics", "speak_replies", "keep_audio"):
            # The session was built from the old config: rebuild it.
            await self._turn_off()
            if self._pipeline is not None:
                await self._pipeline.stop()
                self._pipeline = None
            ok, why = await self._turn_on()
            restarted = " (listening again with it)" if ok else f" (could not restart: {why})"
        return True, f"{key} = {value!r}{where}{restarted}"

    async def _on_bench(self, message) -> None:
        """`voice bench`: measure the configured engines on this machine."""
        from .bench import run_benchmark

        pipeline, why = await self._pipeline_ready()
        if pipeline is None:
            await self._reply(message, topics.VOICE_BENCH_REPLY, {"ok": False, "detail": why})
            return
        play = bool(message.payload.get("play", True))
        try:
            result = await run_benchmark(
                synthesiser=pipeline._tts, recogniser=pipeline._stt, speaker=pipeline._speaker,  # noqa: SLF001
                config=self.config, play=play)
        except Exception as exc:  # noqa: BLE001 -- a benchmark that fails is a result too
            await self._reply(message, topics.VOICE_BENCH_REPLY, {"ok": False, "detail": f"benchmark failed: {exc!r}"})
            return
        await self._reply(message, topics.VOICE_BENCH_REPLY, {"ok": True, "result": result})

    async def _on_speak(self, message) -> None:
        text = str(message.payload.get("text") or "").strip()
        if not text:
            await self._reply(message, topics.VOICE_SPEAK_REPLY, {"ok": False, "detail": "nothing to say"})
            return
        pipeline, why = await self._pipeline_ready()
        if pipeline is None:
            await self._reply(message, topics.VOICE_SPEAK_REPLY, {"ok": False, "detail": why})
            return
        try:
            said = await self._say(text)
        except Exception as exc:  # noqa: BLE001 -- an engine failure is an answer, not a crash
            await self._reply(message, topics.VOICE_SPEAK_REPLY, {"ok": False, "detail": f"could not speak: {exc!r}"})
            return
        await self._reply(message, topics.VOICE_SPEAK_REPLY, {
            "ok": True, "seconds": max(0.0, len(said) / 20.0), "engine": self._engine_names["tts"]})

    async def _on_listen(self, message) -> None:
        pipeline, why = await self._pipeline_ready()
        if pipeline is None:
            await self._reply(message, topics.VOICE_LISTEN_REPLY, {"ok": False, "detail": why})
            return
        seconds = float(message.payload.get("seconds") or 0) or None
        respond = bool(message.payload.get("respond", True))
        try:
            utterance, said = await pipeline.listen_once(max_seconds=seconds, respond=respond)
        except Exception as exc:  # noqa: BLE001
            await self._reply(message, topics.VOICE_LISTEN_REPLY, {"ok": False, "detail": f"could not listen: {exc!r}"})
            return
        if utterance is None:
            await self._reply(message, topics.VOICE_LISTEN_REPLY, {"ok": True, "heard": "", "detail": "heard nothing"})
            return
        await self._reply(message, topics.VOICE_LISTEN_REPLY, {
            "ok": True, "heard": utterance.text, "confidence": utterance.confidence, "seconds": utterance.seconds,
            "said": said, "engine": utterance.engine,
        })

    async def _on_voices(self, message) -> None:
        pipeline, why = await self._pipeline_ready()
        tts = self._injected["synthesiser"] or (pipeline._tts if pipeline else None)  # noqa: SLF001
        if tts is None:
            await self._reply(message, topics.VOICE_VOICES_REPLY, {"engine": "", "voices": [], "detail": why})
            return
        try:
            voices = list(tts.voices())
        except Exception as exc:  # noqa: BLE001
            voices, why = [], f"could not list voices: {exc!r}"
        await self._reply(message, topics.VOICE_VOICES_REPLY, {
            "engine": getattr(tts, "name", ""), "voices": voices, "current": self.config.tts_voice, "detail": why})

    async def _on_devices(self, message) -> None:
        await self._pipeline_ready()
        n = self._engine_names
        await self._reply(message, topics.VOICE_DEVICES_REPLY, {
            "microphone": n["mic"], "speaker": n["spk"], "stt": n["stt"], "tts": n["tts"], "vad": n["vad"],
            "problems": list(self._problems)})

    async def _on_any_reply(self, message) -> None:
        """`speak_replies`: a reply to a typed turn is spoken too. A reply
        to a SPOKEN turn is the pipeline's own to speak (it is waiting on
        this very session), so it is left alone here."""
        text = str(message.payload.get("text") or "").strip()
        session_id = str(message.payload.get("session_id") or "")
        if not text:
            return
        pipeline, why = await self._pipeline_ready()
        if pipeline is None:
            self._ctx.logger.warning("voice.cannot_speak_reply", reason=why)
            return
        if session_id in pipeline._pending or pipeline.is_voice_session(session_id):  # noqa: SLF001 -- its own turn
            return
        try:
            await self._say(text, session_id=session_id)
        except Exception as exc:  # noqa: BLE001 -- speech is best effort; the reply was already printed
            self._ctx.logger.warning("voice.reply_not_spoken", error=repr(exc))

    async def _say(self, text: str, *, session_id: str = "") -> str:
        """Speak through the running session when there is one -- so it
        knows Sim is talking and does not hear itself -- else through
        the pipeline. Both take the one speech lock."""
        session = self._session
        if session is not None and self._enabled and self._loop_task is not None and not self._loop_task.done():
            return await session.say(text)
        pipeline, why = await self._pipeline_ready()
        if pipeline is None:
            raise RuntimeError(why)
        return await pipeline.speak(text, session_id=session_id or None)

    async def _on_models(self, message) -> None:
        """`voice models [name]`: fetch a real recogniser model. The next
        `voice listen` opens it -- the engines are re-opened so a model
        that arrived after boot is not ignored until a restart."""
        from .stt.whisper_cli import KNOWN_MODELS, download_model

        from .tts.kokoro import download_kokoro
        from .tts.piper import PIPER_VOICES, download_piper

        name = str(message.payload.get("name") or "base.en").strip()
        model_dir = Path(self.config.model_dir)
        piper_names = {f"piper-{lang}": voice for lang, voice in PIPER_VOICES.items()}
        available = [*KNOWN_MODELS, "kokoro", *piper_names]
        if name == "kokoro":
            path, problem = await asyncio.to_thread(download_kokoro, model_dir)
        elif name in piper_names or name.startswith("piper-"):
            voice = piper_names.get(name) or self.config.tts_farsi_voice
            path, problem = await asyncio.to_thread(download_piper, model_dir, voice=voice)
        else:
            path, problem = await asyncio.to_thread(download_model, name, model_dir)
        if path is None:
            await self._reply(message, topics.VOICE_MODELS_REPLY, {"ok": False, "detail": problem,
                                                                   "available": available})
            return
        if self._pipeline is not None:
            await self._pipeline.stop()
            self._pipeline = None
        from dataclasses import replace
        if name == "kokoro":
            detail = "kokoro ready; it is picked over `say` from now on (`[voice] tts = \"kokoro\"` pins it)"
        elif name in piper_names or name.startswith("piper-"):
            detail = f"piper voice {path.stem} ready; replies in its language are spoken with it from now on"
        else:
            detail = f"{name} ready; `[voice] stt_model = \"{name}\"` keeps it across restarts"
            if self.config.stt_model != name:
                self.config = replace(self.config, stt_model=name)
        await self._reply(message, topics.VOICE_MODELS_REPLY, {
            "ok": True, "path": str(path), "bytes": path.stat().st_size, "detail": detail, "available": available})

    # ------------------------------------------------------------- probes
    async def _write_probes(self) -> None:
        assert self._ctx is not None
        for payload in presence_probes():
            try:
                await self._ctx.ledger.append(CAPABILITIES_STREAM, Event(
                    stream=CAPABILITIES_STREAM, type="probed", ts=self._ctx.clock.now(), trace_id="",
                    causation_id=None, payload=payload))
            except Exception as exc:  # noqa: BLE001 -- diagnostics must never break the boot they diagnose
                self._ctx.logger.warning("voice.probe_not_recorded", name=payload["name"], error=repr(exc))


__all__ = ["NAME", "Service", "VERSION", "presence_probes"]
