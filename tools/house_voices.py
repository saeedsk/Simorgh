#!/usr/bin/env python3
"""Which Kokoro voices the speaker embedder can tell apart (stage 11 item 2).

    python tools/house_voices.py            # the five the household uses, measured
    python tools/house_voices.py --all      # every voice, most separable five proposed

The simulator's personas are only useful if the embedder hears them as
different people. That is a measurement, and it changes when Kokoro or
the speaker model does, so it lives in a command rather than in
somebody's memory. The first hand-picked set had two voices at 0.77.
"""
import argparse
import asyncio
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

LINE = "Has anyone seen the blue folder that was on the kitchen table yesterday?"


async def _vectors(voices):
    import numpy as np

    from simorgh.voice.config import Config
    from simorgh.voice.speakers import SherpaEmbedder
    from simorgh.voice.tts.kokoro import KokoroSynthesiser

    tts, embedder = KokoroSynthesiser(Config()), SherpaEmbedder("workspace/voice/models")
    out = {}
    for voice in voices:
        audio = await tts.synthesise(LINE, voice=voice)
        samples = np.frombuffer(audio.pcm, dtype=np.int16).astype(np.float32) / 32768.0
        out[voice] = embedder.embed(samples, audio.sample_rate)
    return out


async def main(argv: list[str]) -> int:
    from simorgh.evals.house.people import HOUSEHOLD
    from simorgh.voice.config import Config
    from simorgh.voice.speakers import cosine
    from simorgh.voice.tts.kokoro import KokoroSynthesiser

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="measure every Kokoro voice and propose a set")
    args = ap.parse_args(argv)

    if args.all:
        voices = [v for v in KokoroSynthesiser(Config()).voices() if v[:3] in ("af_", "am_", "bf_", "bm_")]
    else:
        voices = [p.voice for p in HOUSEHOLD]
    vectors = await _vectors(voices)
    worst = 0.0
    for a, b in itertools.combinations(voices, 2):
        score = cosine(vectors[a], vectors[b])
        worst = max(worst, score)
        if not args.all or score >= 0.4:
            print(f"{a:14} vs {b:14} {score:.2f}")
    print(f"\nworst pair: {worst:.2f}  (the household wants under 0.40)")
    if args.all:
        chosen = list(min(itertools.combinations(voices, 2), key=lambda p: cosine(vectors[p[0]], vectors[p[1]])))
        while len(chosen) < 5:
            chosen.append(min((v for v in voices if v not in chosen),
                              key=lambda v: max(cosine(vectors[v], vectors[c]) for c in chosen)))
        print("most separable five:", ", ".join(chosen))
    return 0 if worst < 0.4 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
