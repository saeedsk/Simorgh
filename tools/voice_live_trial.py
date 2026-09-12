"""A live trial of the spoken conversation on THIS machine: the real
microphone, detector and whisper, macOS `say` speaking a question into
the room, and -- with --real-tts -- Sim's own Kokoro reply through the
speakers before a second question. Prints every state change with the
level gate's floor and echo bar beside it.

    PYTHONPATH=. python tools/voice_live_trial.py [--real-tts]

This is how "it can't hear anything" (2026-09-11) was found: unit tests
with fake microphones passed, the real path failed after Sim had
spoken. Run it from a quiet room; it takes about thirty seconds.
"""

import asyncio
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "simorgh", "voice"))
from simorgh.voice.config import Config
from simorgh.voice.stt import open_recogniser
from simorgh.voice.tts import open_synthesiser
from simorgh.voice.audio import open_microphone, open_speaker
from simorgh.voice.vad import open_detector, threshold_for
from simorgh.voice.fakes import FakeSpeaker, FakeSynthesiser
from simorgh.voice.pipeline import Pipeline
from simorgh.voice.session import VoiceSession
from simorgh.contracts import topics
import test_session as T
REAL_TTS = "--real-tts" in sys.argv

class Logger:
    def _p(self, level, event, **f): print(f"  LOG {level} {event} {f}", flush=True)
    def info(self, e, **f): self._p("info", e, **f)
    def warning(self, e, **f): self._p("WARN", e, **f)
    def debug(self, e, **f): pass
    def error(self, e, **f): self._p("ERROR", e, **f)

async def main():
    cfg = Config(tts_voice="af_jessica")
    stt, why = await asyncio.to_thread(open_recogniser, cfg, repo_root="."); print("stt", stt.name, why)
    mic, why = open_microphone("auto"); print("mic", mic.name, why)
    if REAL_TTS:
        tts, why = open_synthesiser(cfg); print("tts", getattr(tts, "name", tts), why)
        speaker, why = open_speaker("auto"); print("speaker", speaker.name, why)
    else:
        tts, speaker = FakeSynthesiser(), FakeSpeaker(realtime=True)
    thr = threshold_for(cfg.vad_sensitivity, cfg.vad_threshold)
    factory = lambda: open_detector("auto", threshold=thr)[0]
    bus = T._Bus()
    pipeline = Pipeline(bus=bus, clock=None, logger=Logger(), ledger=None, config=cfg, microphone=mic, speaker=speaker, recogniser=stt, synthesiser=tts, detector_factory=factory)
    async def ask(text, **kw): print("  ASKED:", repr(text), flush=True); return "It is twelve o'clock, and the sky is clear."
    pipeline.ask = ask
    session = VoiceSession(pipeline=pipeline, config=cfg, microphone=mic, speaker=speaker, recogniser=stt, synthesiser=tts, detector_factory=factory, logger=Logger())
    stop = asyncio.Event(); task = asyncio.create_task(session.run(stop))
    t0 = time.time()
    def stamp(): return f"{time.time()-t0:5.1f}s"
    async def watch(seconds):
        last = None; end = time.time() + seconds; tick = 0
        while time.time() < end:
            det = session._detector
            if det is None:
                await asyncio.sleep(0.05); continue
            lvl = det._level if hasattr(det, "_level") else det
            if session.state != last:
                print(f"  {stamp()} state={session.state} floor={round(lvl._floor or 0)} echo={lvl._echo} gain={round(session._echo.gain,3)}", flush=True); last = session.state
            tick += 1
            if tick % 20 == 0:
                print(f"  {stamp()} .. state={session.state} floor={round(lvl._floor or 0)} echo={lvl._echo} calibrating={session._echo.calibrating} active={session._echo.active(session._now())}", flush=True)
            await asyncio.sleep(0.05)
    await watch(2.0)
    print(stamp(), "SAY #1", flush=True); subprocess.Popen(["say", "-v", "Daniel", "Hello Sim, can you hear me? What time is it?"])
    await watch(14.0 if REAL_TTS else 9.0)
    print(stamp(), "SAY #2", flush=True); subprocess.Popen(["say", "-v", "Daniel", "Sim, are you still listening to me right now?"])
    await watch(12.0)
    stop.set(); await task
    for t, p in bus.published:
        if t in (topics.VOICE_TRANSCRIPT, topics.VOICE_SPOKEN, topics.VOICE_CONTROL_REQUEST): print("  EVENT", t, {k: v for k, v in p.items() if k in ("text", "partial", "echo", "quiet", "aside", "command", "dropped", "turn")})
    print("transitions", session.turns.transitions)
asyncio.run(main())
