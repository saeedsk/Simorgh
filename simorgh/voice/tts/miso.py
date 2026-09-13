"""MisoTTS 8B (Miso Labs, open weights): a Sesame-CSM-style text-to-
dialogue model -- 8B backbone, Mimi codec, 16 GB of bfloat16 weights --
that reads feeling from the words and the context rather than from a
dial; a reference WAV clones a voice. Its repository asks for a 24 GB
GPU; here it is tried on Apple's MPS or the CPU, and the server says
which and how long it took, so the creator can decide (2026-09-13:
"let's build the system for both ... and decide later"). Runs in a
Python 3.10 venv with the MisoTTS checkout on its path."""

from __future__ import annotations

import os
from pathlib import Path

from .subproc import DEFAULT_VENV_DIR, SubprocessSynthesiser, create_venv, engine_available

REPO_URL = "https://github.com/MisoLabsAI/MisoTTS.git"
DEFAULT_REPO = "workspace/voice/engines/MisoTTS"


def available(venv_dir: str = DEFAULT_VENV_DIR, repo: str = DEFAULT_REPO) -> tuple[bool, str]:
    if not (Path(repo) / "generator.py").is_file():
        return False, f"needs the MisoTTS checkout at {repo} (`voice models miso` clones it)"
    return engine_available("miso", "torch", venv_dir)


def install(venv_dir: str = DEFAULT_VENV_DIR, repo: str = DEFAULT_REPO, *, log=print):
    import subprocess

    repo_path = Path(repo)
    if not (repo_path / "generator.py").is_file():
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        log(f"  cloning {REPO_URL} into {repo_path} ...")
        done = subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(repo_path)], capture_output=True, text=True, timeout=600)
        if done.returncode != 0:
            return None, f"could not clone MisoTTS: {(done.stderr or done.stdout).strip()[-300:]}"
    return create_venv(venv_dir, "miso", python="3.10", editable=str(repo_path), log=log)


class MisoSynthesiser(SubprocessSynthesiser):
    name = "miso"
    module = "torch"
    server = "miso_server.py"
    load_timeout_s = 1800.0   # 16 GB of weights the first time

    def __init__(self, config) -> None:
        self._repo = str(getattr(config, "miso_repo", "") or DEFAULT_REPO)
        ok, why = available(getattr(config, "venv_dir", DEFAULT_VENV_DIR), self._repo)
        if not ok:
            raise ImportError(why)
        super().__init__(config, venv_dir=getattr(config, "venv_dir", DEFAULT_VENV_DIR),
                         reference=str(getattr(config, "miso_reference", "") or ""),
                         timeout_s=float(getattr(config, "expressive_timeout_s", 180.0)) * 3)
        self._device = str(getattr(config, "miso_device", "") or "")
        os.environ["MISO_REPO"] = str(Path(self._repo).resolve())
        if self._device:
            os.environ["MISO_DEVICE"] = self._device

    def params_for(self, tone: str) -> dict:
        # Miso takes no emotion dial: the feeling is in the words. A little
        # more temperature for the lively tones, less for the calm ones.
        temperature = {"bright": 1.0, "playful": 1.0, "calm": 0.7, "sorry": 0.7, "serious": 0.75}.get((tone or "").lower(), 0.9)
        return {"speaker": 0, "temperature": temperature, "max_audio_length_ms": 30_000}


__all__ = ["DEFAULT_REPO", "MisoSynthesiser", "REPO_URL", "available", "install"]
