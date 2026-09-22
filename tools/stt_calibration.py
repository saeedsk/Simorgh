#!/usr/bin/env python3
"""How well does Sim hear this household? Word error rate and latency
per language, over the calibration set (`voice calibrate`).

The set is recorded once and kept (`[voice] calibration_dir`, default
`workspace/voice/calibration/<person>/`): each take is a WAV with its
script line as the reference text. This runs a speech recogniser over
every take and prints, per engine and per language, the corpus word
error rate (`voice/calibration.py::wer`: case, punctuation, Persian and
Arabic letter variants, ZWNJ and digits folded), the mean per-take WER,
and the decode latency p50/p95 -- the stage 3 item 6 measurement.

    python3 tools/stt_calibration.py                        # the configured engine, everybody
    python3 tools/stt_calibration.py --person Saeed --language fa
    python3 tools/stt_calibration.py --engine sherpa        # one engine by name
    python3 tools/stt_calibration.py --hint                 # tell the engine each take's language
    python3 tools/stt_calibration.py --show                 # every take: reference, heard, WER
    python3 tools/stt_calibration.py --json out.json        # the numbers, for a findings doc

With no `--engine`, the configured `[voice] stt` engine runs, and the
sherpa streaming engine too when it is installed with its model (it is
not in "auto" on purpose: its model is zh-en, and this measures how
much Farsi that costs). Local engines only -- nothing here calls a
paid model. Without `--hint` the engine is given `[voice] stt_language`
exactly as the live session gives it, so the number is the one a real
turn gets.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from simorgh.voice.calibration import load, wer, word_errors  # noqa: E402
from simorgh.voice.config import Config  # noqa: E402


def _config(path: str = "") -> Config:
    """`[voice]` from the simorgh.toml the Kernel would read."""
    import tomllib

    from simorgh.contracts.settings import config_path

    source = Path(path) if path else config_path()
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return Config.from_mapping(dict(data.get("voice") or {}))


def _percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    ranked = sorted(values)
    return ranked[min(len(ranked) - 1, int(round(share * (len(ranked) - 1))))]


def _engines(config: Config, wanted: str) -> list[tuple[str, object]]:
    """(label, recogniser) for each engine to run; a missing one is said and skipped."""
    from dataclasses import replace

    from simorgh.voice.stt import open_recogniser

    names = [wanted] if wanted else [config.stt]
    if not wanted and config.stt != "sherpa" and importlib.util.find_spec("sherpa_onnx") is not None:
        names.append("sherpa")
    out = []
    for name in names:
        recogniser, why = open_recogniser(replace(config, stt=name), repo_root=REPO)
        if recogniser is None:
            print(f"  {name}: not available -- {why}", file=sys.stderr)
            continue
        out.append((getattr(recogniser, "name", name) or name, recogniser))
    return out


async def _measure(label: str, recogniser, takes, *, hint: bool, language: str, show: bool) -> dict:
    from simorgh.voice.api import Audio

    warmup = getattr(recogniser, "warmup", None)
    if callable(warmup):
        await warmup()
    by_language: dict[str, dict] = {}
    for take in takes:
        audio = Audio(take.pcm, take.sample_rate)
        started = time.perf_counter()
        heard = await recogniser.transcribe(audio, language=take.language if hint else language)
        took = time.perf_counter() - started
        errors, words = word_errors(take.reference, heard.text)
        row = by_language.setdefault(take.language, {"errors": 0, "words": 0, "wers": [], "latency": [],
                                                     "audio_s": 0.0, "takes": 0})
        row["errors"] += errors
        row["words"] += words
        row["wers"].append(wer(take.reference, heard.text))
        row["latency"].append(took)
        row["audio_s"] += audio.seconds
        row["takes"] += 1
        if show:
            print(f"  [{label}] {take.person} {take.line_id} wer {row['wers'][-1]:.2f} {took:.2f}s\n"
                  f"      said:  {take.reference}\n      heard: {heard.text}")
    stop = getattr(recogniser, "stop", None)
    if callable(stop):
        try:
            await stop()
        except Exception:  # noqa: BLE001 -- the numbers are in; a stuck server is not the result
            pass
    return {code: {"takes": r["takes"], "words": r["words"],
                   "wer": round(r["errors"] / r["words"], 4) if r["words"] else 0.0,
                   "mean_take_wer": round(statistics.fmean(r["wers"]), 4),
                   "latency_p50_s": round(_percentile(r["latency"], 0.5), 3),
                   "latency_p95_s": round(_percentile(r["latency"], 0.95), 3),
                   "real_time_factor": round(sum(r["latency"]) / r["audio_s"], 3) if r["audio_s"] else 0.0}
            for code, r in sorted(by_language.items())}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--person", default="", help="one person's takes (default: everybody's)")
    parser.add_argument("--language", default="", choices=("", "en", "fa"), help="one language")
    parser.add_argument("--engine", default="", help="auto | whisper_server | faster_whisper | whisper_cli | sherpa | fake")
    parser.add_argument("--dir", default="", help="the calibration folder (default: [voice] calibration_dir)")
    parser.add_argument("--config", default="", help="a simorgh.toml other than the Kernel's")
    parser.add_argument("--hint", action="store_true", help="give the engine each take's language")
    parser.add_argument("--limit", type=int, default=0, help="at most this many takes")
    parser.add_argument("--show", action="store_true", help="print every take")
    parser.add_argument("--json", default="", help="also write the numbers here")
    args = parser.parse_args(argv)

    config = _config(args.config)
    folder = args.dir or config.calibration_dir
    takes = load(args.person or None, args.language or None, folder=folder)
    if args.limit:
        takes = takes[: args.limit]
    if not takes:
        print(f"no calibration takes in {folder} -- record them with `voice calibrate` in Sim")
        return 1
    engines = _engines(config, args.engine)
    if not engines:
        return 2
    people = sorted({t.person for t in takes})
    print(f"{len(takes)} take(s) from {', '.join(people)} in {folder}; "
          f"language given to the engine: {'each take' if args.hint else (config.stt_language or 'auto')}")
    results = {}
    for label, recogniser in engines:
        results[label] = asyncio.run(_measure(label, recogniser, takes, hint=args.hint,
                                              language=config.stt_language, show=args.show))
    print(f"\n{'engine':<28}{'lang':<6}{'takes':>6}{'WER':>8}{'mean':>8}{'p50 s':>8}{'p95 s':>8}{'RTF':>7}")
    for label, per in results.items():
        for code, r in per.items():
            print(f"{label[:27]:<28}{code:<6}{r['takes']:>6}{r['wer']:>8.1%}{r['mean_take_wer']:>8.1%}"
                  f"{r['latency_p50_s']:>8.2f}{r['latency_p95_s']:>8.2f}{r['real_time_factor']:>7.2f}")
    if args.json:
        Path(args.json).write_text(json.dumps({"at": time.time(), "folder": str(folder), "hint": args.hint,
                                               "people": people, "results": results}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
