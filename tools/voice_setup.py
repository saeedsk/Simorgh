#!/usr/bin/env python3
"""Install the local voice stack: pinned packages, then the models.

    python tools/voice_setup.py            # everything below
    python tools/voice_setup.py --no-models

Every engine is optional at runtime and refused by name when absent;
this is the one-time step that makes them present. Network is needed
here and nowhere else in the voice path. Versions are the ones this
was built and measured against (2026-09-11, Apple M3 Pro, macOS 26.5,
Python 3.12); see THIRD_PARTY_NOTICES.md for what each one is and its
licence.
"""

from __future__ import annotations

import argparse
import importlib
import re
import subprocess
import sys
from pathlib import Path

PACKAGES = (
    "kokoro-onnx==0.6.1",   # Kokoro-82M through onnxruntime: the primary voice (MIT; weights Apache-2.0)
    "piper-tts==1.8.0",     # Piper, the lightweight fallback and the Farsi voice (GPL-3.0; see notices)
    "silero-vad==6.2.1",    # voice activity detection (MIT)
    "sounddevice==0.5.6",   # microphone and playback through PortAudio (MIT)
    "soundfile==0.14.0",    # WAV reading/writing (BSD-3)
    "numpy>=1.26",
)
#: Pure-Python packages whose Requires-Python cap is older than the wheels
#: they need. kokoro-onnx 0.6.1 says `<3.14` because onnxruntime had no
#: 3.14 build when it was released; onnxruntime, numpy, espeakng-loader
#: and phonemizer all do now (PyPI, 2026-10-29). On a newer Python it is
#: installed with the cap ignored and its dependencies resolved normally.
CAP_IGNORABLE = ("kokoro-onnx",)
OPTIONAL = (
    "faster-whisper",       # CTranslate2 Whisper, when whisper.cpp is not wanted (MIT)
)


def pip(*args: str) -> int:
    return subprocess.call([sys.executable, "-m", "pip", "install", "-q", *args])


def _name(requirement: str) -> str:
    return re.split(r"[<>=!~\[ ;]", requirement, maxsplit=1)[0]


def install(packages: tuple[str, ...] = PACKAGES, *, pip=pip) -> int:
    """Install `packages`; 0 when every one is in. When the batch fails,
    the rest go in without the CAP_IGNORABLE ones, and those go in with
    their Requires-Python cap ignored but not their dependencies' caps
    (`--no-deps`, then the dependencies they declare, normally)."""
    if pip(*packages) == 0:
        return 0
    capped = [p for p in packages if _name(p) in CAP_IGNORABLE]
    rest = [p for p in packages if p not in capped]
    if not capped or pip(*rest) != 0:
        return 1
    print(f"retrying {', '.join(capped)} past its Python cap ({sys.version.split()[0]}); see CAP_IGNORABLE")
    if pip("--ignore-requires-python", "--no-deps", *capped) != 0:
        return 1
    from importlib import metadata

    importlib.invalidate_caches()
    deps = [r.split(";")[0].strip() for p in capped for r in (metadata.requires(_name(p)) or [])
            if "extra ==" not in r]
    return pip(*deps) if deps else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-models", action="store_true", help="packages only")
    parser.add_argument("--model-dir", default="workspace/voice/models")
    parser.add_argument("--whisper", default="large-v3-turbo",
                        help="whisper.cpp model to fetch (large-v3-turbo hears Farsi; base.en is English only)")
    args = parser.parse_args()
    print("packages:", ", ".join(PACKAGES))
    if install() != 0:
        print("pip failed; see above", file=sys.stderr)
        return 1
    if args.no_models:
        return 0
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from simorgh.voice.stt.whisper_cli import download_model
    from simorgh.voice.tts.kokoro import download_kokoro
    from simorgh.voice.tts.piper import PIPER_VOICES, download_piper

    model_dir = Path(args.model_dir)
    print("kokoro ...", end=" ", flush=True)
    path, problem = download_kokoro(model_dir)
    print(path or problem)
    for lang, voice in PIPER_VOICES.items():
        print(f"piper {lang} ({voice}) ...", end=" ", flush=True)
        path, problem = download_piper(model_dir, voice=voice)
        print(path or problem)
    print(f"whisper.cpp {args.whisper} ...", end=" ", flush=True)
    path, problem = download_model(args.whisper, model_dir)
    print(path or problem)
    print("done. `./sim.sh` then `voice bench` measures it on this machine; `voice on` starts listening.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
