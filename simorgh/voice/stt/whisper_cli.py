"""whisper.cpp through its `whisper-cli` binary -- what this Mac has.

Models: `stt_model` may be an absolute path, a file under `model_dir`,
or a bare name (`base.en`) looked up as `ggml-<name>.bin` in `model_dir`
and then in Homebrew's share directory. The only model Homebrew ships
is `for-tests-ggml-tiny.bin`, which is good enough to prove the path
works and bad enough that `name` says so; `voice models <name>`
downloads a real one.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..api import Audio, Utterance
from ..audio import write_wav

_BREW_SHARES = (Path("/opt/homebrew/share/whisper-cpp"), Path("/usr/local/share/whisper-cpp"))
_TEST_MODEL = "for-tests-ggml-tiny.bin"


def find_model(name: str, model_dir: Path) -> Path | None:
    # `base.en` is a bare model name, not a file with an `.en` suffix --
    # `Path.suffix` said otherwise, the lookup skipped `ggml-base.en.bin`
    # and fell through to Homebrew's test fixture, which hears silence
    # (2026-09-10: the freshly downloaded model was never opened).
    candidates = [Path(name).expanduser()]
    if name.endswith(".bin"):
        candidates.append(model_dir / name)
    else:
        candidates += [model_dir / f"ggml-{name}.bin", model_dir / f"{name}.bin"]
    for share in _BREW_SHARES:
        candidates.append(share / f"ggml-{name}.bin")
    # Any real model already downloaded beats the fixture, whatever the
    # configured name says: `stt_model` defaults to faster-whisper's
    # `large-v3-turbo`, which whisper.cpp spells differently, and a
    # person who ran `voice models base.en` meant to use it.
    if model_dir.is_dir():
        candidates += sorted(model_dir.glob("ggml-*.bin"))
    for share in _BREW_SHARES:
        candidates.append(share / _TEST_MODEL)
    for c in candidates:
        if c.is_file():
            return c
    return None


#: ggerganov's own model files, the ones whisper.cpp documents.
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
KNOWN_MODELS = ("tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en",
                "large-v3", "large-v3-turbo")


def download_model(name: str, model_dir: Path, *, timeout: float = 600.0) -> tuple[Path | None, str]:
    """Fetch `ggml-<name>.bin` into `model_dir`. `(path, problem)`.

    Homebrew ships only `for-tests-ggml-tiny.bin`, a fixture that reads
    every audio file as silence (measured on the JFK sample it ships
    beside, 2026-09-10) -- so `voice listen` on a fresh Mac transcribed
    nothing and could not have said why. A real model is one download;
    this is the download. Streamed to a temp file and renamed, so a
    half-fetched model never passes for one."""
    import urllib.error
    import urllib.request

    if name not in KNOWN_MODELS:
        return None, f"unknown whisper.cpp model {name!r}; one of: {', '.join(KNOWN_MODELS)}"
    model_dir.mkdir(parents=True, exist_ok=True)
    target = model_dir / f"ggml-{name}.bin"
    if target.is_file() and target.stat().st_size > 1_000_000:
        return target, ""
    tmp = target.with_suffix(".bin.part")
    try:
        with urllib.request.urlopen(MODEL_URL.format(name=name), timeout=timeout) as resp, tmp.open("wb") as out:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(target)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        tmp.unlink(missing_ok=True)
        return None, f"could not download {name}: {exc!r}"
    return target, ""


#: whisper.cpp writes these for audio with no speech in it: `[BLANK_AUDIO]`,
#: `[MUSIC]`, `(silence)`, `[inaudible]`, `*laughs*`. They are annotations,
#: not words, and the pipeline used to hand `[BLANK_AUDIO]` to Sim as a
#: question -- which Sim answered, aloud (the creator's screen, 2026-09-11).
#: Bracketed and SHOUTED (`[BLANK_AUDIO]`, `[MUSIC]`), or a known
#: non-speech word in parentheses or asterisks. A real parenthetical a
#: person spoke -- "call foo (the old one)" -- is left alone.
_SHOUTED = re.compile(r"\[[A-Z0-9_ ]{2,40}\]")
_KNOWN = re.compile(r"[\[(*](?:silence|inaudible|laughs|laughter|laughing|applause|music|noise|blank(?:_audio)?|"
                    r"unintelligible|crosstalk|sighs|coughs|coughing|breathing)[\])*]", re.I)


def clean_transcript(text: str) -> str:
    """The words, with whisper's non-speech annotations removed."""
    cleaned = _KNOWN.sub(" ", _SHOUTED.sub(" ", text or ""))
    return re.sub(r"\s+", " ", cleaned).strip()


class WhisperCliRecogniser:
    name = "whisper_cli"

    def __init__(self, config, *, repo_root=None) -> None:
        self._bin = shutil.which("whisper-cli") or shutil.which("whisper-cpp")
        if not self._bin:
            raise ImportError("whisper-cli (whisper.cpp) is not installed")
        model_dir = Path(config.model_dir)
        if repo_root is not None and not model_dir.is_absolute():
            model_dir = Path(repo_root) / model_dir
        model = find_model(config.stt_model, model_dir)
        if model is None:
            raise ImportError(f"no whisper.cpp model for {config.stt_model!r} under {model_dir} "
                              f"(run `voice models base.en` to download one)")
        self._model = model
        self._language = config.stt_language or "auto"
        tag = model.name.replace("ggml-", "").replace(".bin", "")
        self.name = f"whisper_cli:{tag}" + (" (test model -- run `voice models base.en`)" if model.name == _TEST_MODEL else "")

    async def transcribe(self, audio: Audio, *, language: str = "") -> Utterance:
        with tempfile.TemporaryDirectory(prefix="simorgh-stt-") as raw:
            wav = Path(raw) / "in.wav"
            write_wav(wav, audio)
            out = Path(raw) / "out"
            args = [self._bin, "-m", str(self._model), "-f", str(wav), "-l", language or self._language,
                    "-oj", "-of", str(out), "-np", "-nt"]
            done = await asyncio.to_thread(
                subprocess.run, args, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
            if done.returncode != 0:
                raise RuntimeError(f"whisper-cli failed: {(done.stderr or done.stdout).strip()[:300]}")
            text, confidence = "", 1.0
            report = out.with_suffix(".json")
            if report.is_file():
                data = json.loads(report.read_text())
                segs = data.get("transcription") or []
                text = " ".join((s.get("text") or "").strip() for s in segs).strip()
                # whisper.cpp reports per-token probabilities under `tokens`
                # when asked; without them there is no confidence to report,
                # and 1.0 with the engine named is the honest reading.
                probs = [float(t["p"]) for s in segs for t in (s.get("tokens") or []) if "p" in t]
                if probs:
                    confidence = min(1.0, sum(probs) / len(probs))
            else:
                text = re.sub(r"\s+", " ", done.stdout).strip()
        return Utterance(text=clean_transcript(text), confidence=confidence, seconds=audio.seconds,
                         engine=self.name, language=language or self._language)
