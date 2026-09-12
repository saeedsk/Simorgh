"""`voice bench`: the numbers the design asks for, measured on this
machine with the engines actually configured.

    load / warm-up      first synthesis, model files to memory
    time to first audio the planner's first piece, synthesised (per sample)
    real-time factor    synthesis seconds / audio seconds
    peak memory         the process's high-water mark
    transcription       a synthesised sample heard back
    interruption        barge-in threshold + how long the speaker took to stop

The samples are the design's four short conversational lines. `stop`
latency is measured by playing the second sample and stopping it a
moment in, so this makes a sound. Everything else is silent.
"""

from __future__ import annotations

import asyncio
import resource
import sys
import time

from .api import TtsRequest
from .planner import SpokenResponsePlanner
from .playback import StreamingPlayer
from .resample import to_mic_rate
from .tts.streaming import StreamingSynthesiser

SAMPLES = (
    "Okay, I found it.",
    "Yeah, that makes sense. Let's try the simpler option first.",
    "Hmm, I'm not fully certain, but here's what I'd check.",
    "I can do that. What should we call the project?",
)


def peak_memory_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(usage / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)


async def run_benchmark(*, synthesiser, recogniser, speaker, config, samples: tuple[str, ...] = SAMPLES,
                        play: bool = True) -> dict:
    tts = synthesiser if isinstance(synthesiser, StreamingSynthesiser) else StreamingSynthesiser(
        synthesiser, lookahead=config.tts_lookahead)
    planner = SpokenResponsePlanner(max_sentences=config.max_spoken_sentences, connectors=False)
    out: dict = {"engine_tts": tts.name, "engine_stt": getattr(recogniser, "name", ""), "samples": []}
    started = time.monotonic()
    out["warmup_s"] = round(await tts.warmup() or (time.monotonic() - started), 3)

    audio_for_stt = None
    for sample in samples:
        plan = planner.plan(sample)
        request = TtsRequest(request_id=f"bench-{len(out['samples'])}",
                             pieces=tuple((c.text, c.pause_ms) for c in plan.chunks),
                             voice=config.tts_voice, speed=config.tts_speed)
        t0 = time.monotonic()
        first = None
        total_audio = 0.0
        pcm, rate = b"", 0
        async for chunk in tts.synthesise_stream(request):
            if first is None:
                first = time.monotonic() - t0
            total_audio += chunk.seconds
            pcm += chunk.pcm
            rate = chunk.sample_rate
        elapsed = time.monotonic() - t0
        out["samples"].append({
            "text": sample, "pieces": len(plan.chunks), "first_audio_s": round(first or elapsed, 3),
            "synthesis_s": round(elapsed, 3), "audio_s": round(total_audio, 2),
            "rtf": round(elapsed / total_audio, 3) if total_audio else None,
            "engine": tts.last_engine,
        })
        if audio_for_stt is None and len(plan.chunks) >= 1 and sample.startswith("Yeah"):
            audio_for_stt = (pcm, rate)
    firsts = [s["first_audio_s"] for s in out["samples"]]
    out["first_audio_s_median"] = round(sorted(firsts)[len(firsts) // 2], 3) if firsts else None
    rtfs = [s["rtf"] for s in out["samples"] if s["rtf"]]
    out["rtf_median"] = round(sorted(rtfs)[len(rtfs) // 2], 3) if rtfs else None

    if recogniser is not None and audio_for_stt is not None:
        from .api import Audio

        pcm, rate = audio_for_stt
        heard_audio = Audio(pcm=to_mic_rate(pcm, rate), sample_rate=16_000)
        t0 = time.monotonic()
        try:
            utterance = await recogniser.transcribe(heard_audio, language=config.stt_language)
            out["transcription"] = {"latency_s": round(time.monotonic() - t0, 3), "audio_s": round(heard_audio.seconds, 2),
                                    "heard": utterance.text, "engine": utterance.engine,
                                    "rtf": round((time.monotonic() - t0) / max(heard_audio.seconds, 0.01), 3)}
        except Exception as exc:  # noqa: BLE001 -- a recogniser that fails is a number too
            out["transcription"] = {"error": repr(exc)}

    out["interruption"] = {"detect_ms": config.barge_in_speech_ms + 30}
    if play and speaker is not None and audio_for_stt is not None:
        from .api import Audio

        pcm, rate = audio_for_stt
        player = StreamingPlayer(speaker)

        async def _one():
            from .api import AudioChunk
            yield AudioChunk(pcm=pcm, sample_rate=rate, request_id="bench-stop", seq=0, final=True)

        task = asyncio.create_task(player.play_stream(_one(), request_id="bench-stop"))
        await asyncio.sleep(0.4)
        t0 = time.monotonic()
        await player.stop()
        report = await task
        out["interruption"]["stop_s"] = round(time.monotonic() - t0, 3)
        out["interruption"]["played_s"] = round(report.seconds, 2)
    out["peak_memory_mb"] = peak_memory_mb()
    return out


def render(result: dict) -> str:
    lines = [f"voice bench · tts {result.get('engine_tts') or '-'} · stt {result.get('engine_stt') or '-'}",
             f"  warm-up {result.get('warmup_s', 0):.2f}s · peak memory {result.get('peak_memory_mb', 0):.0f} MB"]
    for s in result.get("samples", []):
        rtf = f"{s['rtf']:.2f}x" if s.get("rtf") else "-"
        lines.append(f"  first audio {s['first_audio_s']:.2f}s · rtf {rtf} · {s['audio_s']:.1f}s of audio "
                     f"({s['engine']})  \"{s['text']}\"")
    if result.get("first_audio_s_median") is not None:
        lines.append(f"  median: first audio {result['first_audio_s_median']:.2f}s · rtf {result.get('rtf_median')}x")
    t = result.get("transcription")
    if t:
        if "error" in t:
            lines.append(f"  transcription: {t['error']}")
        else:
            lines.append(f"  transcription {t['latency_s']:.2f}s for {t['audio_s']:.1f}s of audio (rtf {t['rtf']}) "
                         f"[{t['engine']}]: \"{t['heard']}\"")
    i = result.get("interruption") or {}
    if i:
        stop = f", speaker stopped in {i['stop_s'] * 1000:.0f} ms" if "stop_s" in i else ""
        lines.append(f"  interruption: a person is noticed after {i['detect_ms']} ms of speech{stop}")
    return "\n".join(lines)


__all__ = ["SAMPLES", "peak_memory_mb", "render", "run_benchmark"]
