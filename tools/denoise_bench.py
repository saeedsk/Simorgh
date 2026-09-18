#!/usr/bin/env python3
"""Does a noise filter help Sim hear, or hurt it?

GTCRN was measured first and made things worse: on English with known
text it raised the word error rate in three conditions of four and
lowered confidence in all four, deleting words outright on clean audio
("Hi seed" -> "H,"). Denoisers are tuned for human ears, and their
artifacts cost an acoustic model more than the noise did. So no filter
goes in front of the recogniser on reputation -- each is measured.

Run it over turns Sim actually heard (`voice set keep_audio on` writes
them to `workspace/voice/audio` as a wav beside a json of what was made
of it), or over a synthetic set with known text to sanity-check the
harness itself.

    python3 tools/denoise_bench.py                     # the captured turns
    python3 tools/denoise_bench.py --synthetic         # known text, added noise
    python3 tools/denoise_bench.py --dir some/folder

Real turns have no ground truth, so word error rate cannot be computed
for them: what is reported is the recogniser's own confidence and
whether the filter changed the words at all. The transcripts are printed
side by side, because a person reading them is the only labeller there
is until somebody writes the truth into the sidecars.
"""

from __future__ import annotations

import argparse
import array
import glob
import json
import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

MODELS = Path("workspace/voice/models")
AUDIO = Path("workspace/voice/audio")


# ----------------------------------------------------------------- audio
def read_wav(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path)) as handle:
        rate, frames = handle.getframerate(), handle.readframes(handle.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    return rate, [x / 32768.0 for x in samples]


def write_wav(path: Path, rate: int, samples: list[float]) -> None:
    clipped = array.array("h", (int(max(-1.0, min(1.0, x)) * 32767) for x in samples))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(clipped.tobytes())


# ----------------------------------------------------------------- filters
def filter_none(rate: int, samples: list[float]) -> list[float]:
    return samples


def _ffmpeg_filter(rate: int, samples: list[float], chain: str) -> list[float]:
    """Run one ffmpeg audio filter chain over the samples."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.wav"
        write_wav(src, rate, samples)
        done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                               "-i", str(src), "-af", chain, str(dst)],
                              capture_output=True, text=True, timeout=120)
        if done.returncode != 0 or not dst.is_file():
            raise RuntimeError((done.stderr or "ffmpeg failed").strip()[:120])
        _rate, out = read_wav(dst)
        return out


def rnnoise(model: str):
    path = MODELS / model
    return lambda rate, samples: _ffmpeg_filter(rate, samples, f"arnndn=m={path}")


def afftdn(rate: int, samples: list[float]) -> list[float]:
    """ffmpeg's spectral gate -- the classical baseline, no model."""
    return _ffmpeg_filter(rate, samples, "afftdn=nf=-25")


def gtcrn(rate: int, samples: list[float]) -> list[float]:
    import sherpa_onnx as so

    cfg = so.OnlineSpeechDenoiserConfig()
    cfg.model.gtcrn.model = str(MODELS / "gtcrn_simple.onnx")
    cfg.model.num_threads = 2
    den = so.OnlineSpeechDenoiser(cfg)
    out: list[float] = []
    step = den.frame_shift_in_samples or 256
    for at in range(0, len(samples), step):
        piece = den.run(samples[at:at + step], rate)
        if piece is not None and len(piece.samples):
            out.extend(piece.samples)
    tail = den.flush()
    if tail is not None and len(tail.samples):
        out.extend(tail.samples)
    return out


def deepfilter(rate: int, samples: list[float]) -> list[float]:
    from df.enhance import enhance, init_df           # type: ignore
    import torch                                       # type: ignore

    model, state, _ = init_df()
    want = state.sr()
    tensor = torch.tensor([samples], dtype=torch.float32)
    if rate != want:
        import torchaudio                              # type: ignore

        tensor = torchaudio.functional.resample(tensor, rate, want)
    out = enhance(model, state, tensor)
    if rate != want:
        import torchaudio                              # type: ignore

        out = torchaudio.functional.resample(out, want, rate)
    return out.squeeze(0).tolist()


FILTERS = {
    "raw": filter_none,
    "rnnoise-sh": rnnoise("sh.rnnn"),
    "rnnoise-bd": rnnoise("bd.rnnn"),
    "afftdn": afftdn,
    "gtcrn": gtcrn,
    "deepfilternet": deepfilter,
}


# ----------------------------------------------------------------- recogniser
def recogniser():
    import sherpa_onnx as so

    folder = Path(sorted(glob.glob(str(MODELS / "sherpa-onnx-x-asr-*")))[0])
    return so.OnlineRecognizer.from_transducer(
        tokens=str(folder / "tokens.txt"), encoder=str(folder / "encoder.int8.onnx"),
        decoder=str(folder / "decoder.onnx"), joiner=str(folder / "joiner.int8.onnx"),
        num_threads=2, enable_endpoint_detection=True,
        modeling_unit="cjkchar+bpe", bpe_vocab=str(folder / "bpe.model"))


def hear(rec, rate: int, samples: list[float]) -> tuple[str, float]:
    stream = rec.create_stream()
    step = int(rate * 0.48)
    for at in range(0, len(samples), step):
        stream.accept_waveform(rate, samples[at:at + step])
    stream.input_finished()
    while rec.is_ready(stream):
        rec.decode_stream(stream)
    result = rec.get_result_all(stream)
    probs = [math.exp(p) for p in (result.ys_probs or ())]
    return result.text.strip(), (sum(probs) / len(probs) if probs else 1.0)


def words_of(text: str) -> list[str]:
    return "".join(c for c in text.lower() if c.isalnum() or c.isspace()).split()


def error_rate(truth: str, heard: str) -> float:
    import difflib

    return 1.0 - difflib.SequenceMatcher(None, words_of(truth), words_of(heard)).ratio()


# ----------------------------------------------------------------- corpora
def captured(folder: Path) -> list[tuple[str, int, list[float], str]]:
    """Turns Sim really heard: (label, rate, samples, truth-or-"")."""
    out = []
    for wav in sorted(folder.glob("*.wav")):
        side = wav.with_suffix(".json")
        truth = ""
        if side.is_file():
            try:
                truth = str(json.loads(side.read_text()).get("truth") or "")
            except ValueError:
                truth = ""
        rate, samples = read_wav(wav)
        out.append((wav.name, rate, samples, truth))
    return out


def synthetic() -> list[tuple[str, int, list[float], str]]:
    """Known words, noise added: proves the harness, not the room."""
    import random

    source = Path("workspace/voice/kokoro-sample.wav")
    truth = ("hi seed i'm sim this is what i sound like now a little warmer "
             "i hope say the word")
    rate, clean = read_wav(source)
    out = [("clean", rate, clean, truth)]
    for level in (0.05, 0.12, 0.20):
        random.seed(11)
        out.append((f"noise {level:.2f}", rate,
                    [max(-1.0, min(1.0, x + random.uniform(-level, level))) for x in clean], truth))
    return out


# ----------------------------------------------------------------- report
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", default=str(AUDIO), help="folder of captured turns")
    parser.add_argument("--synthetic", action="store_true", help="known text with added noise")
    parser.add_argument("--only", default="", help="comma-separated filters to run")
    args = parser.parse_args(argv)

    clips = synthetic() if args.synthetic else captured(Path(args.dir))
    if not clips:
        print(f"no audio in {args.dir}. Turn capture on with `voice set keep_audio on`,")
        print("talk to Sim where it is noisy, then run this again.")
        return 1
    wanted = [f.strip() for f in args.only.split(",") if f.strip()] or list(FILTERS)
    rec = recogniser()

    print(f"  {len(clips)} clip(s); filters: {', '.join(wanted)}\n")
    totals: dict[str, list[float]] = {name: [] for name in wanted}
    errors: dict[str, list[float]] = {name: [] for name in wanted}
    for label, rate, samples, truth in clips:
        print(f"  == {label}  ({len(samples)/rate:.2f}s)" + (f'  truth: {truth[:46]!r}' if truth else ""))
        for name in wanted:
            fn = FILTERS.get(name)
            if fn is None:
                print(f"    {name:14} unknown filter"); continue
            try:
                heard_text, conf = hear(rec, rate, fn(rate, samples))
            except Exception as exc:  # noqa: BLE001 -- a filter that will not run is a result
                print(f"    {name:14} unavailable: {str(exc)[:70]}")
                continue
            totals[name].append(conf)
            line = f"    {name:14} conf={conf:.3f}"
            if truth:
                wer = error_rate(truth, heard_text)
                errors[name].append(wer)
                line += f"  wer={wer:.2f}"
            print(f"{line}  {heard_text[:54]!r}")
        print()

    print("  ---- mean over all clips ----")
    for name in wanted:
        if not totals[name]:
            continue
        mean_conf = sum(totals[name]) / len(totals[name])
        line = f"  {name:14} conf={mean_conf:.3f}"
        if errors[name]:
            line += f"  wer={sum(errors[name])/len(errors[name]):.3f}"
        print(line)
    if not any(errors.values()):
        print("\n  No ground truth: word error rate needs a \"truth\" field in each sidecar.")
        print("  Read the transcripts above and write what was really said into the json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
