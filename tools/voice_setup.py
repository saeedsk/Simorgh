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
OPTIONAL = (
    "faster-whisper",       # CTranslate2 Whisper, when whisper.cpp is not wanted (MIT)
)


def pip(*args: str) -> int:
    return subprocess.call([sys.executable, "-m", "pip", "install", "-q", *args])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-models", action="store_true", help="packages only")
    parser.add_argument("--model-dir", default="workspace/voice/models")
    parser.add_argument("--whisper", default="large-v3-turbo",
                        help="whisper.cpp model to fetch (large-v3-turbo hears Farsi; base.en is English only)")
    args = parser.parse_args()
    print("packages:", ", ".join(PACKAGES))
    if pip(*PACKAGES) != 0:
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
