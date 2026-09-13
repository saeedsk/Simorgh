"""Chatterbox (Resemble AI, MIT): the expressive engine with a dial.
`exaggeration` (0-1) is how much feeling, `cfg_weight` how closely it
follows the reference pacing; a reference WAV of six seconds or more
clones a voice. Runs in its own venv (torch 2.6) as a line server --
see voice/tts/subproc.py. Measured 2026-09-13 on the M3 Pro (MPS): the
model loads in 12 s, the first sentence takes ~19 s, then 2.6 s of
speech in 4.7 s -- an expressive lane, not a fast one."""

from __future__ import annotations

from .subproc import DEFAULT_VENV_DIR, SubprocessSynthesiser, create_venv, engine_available

PACKAGES = ("setuptools", "wheel", "chatterbox-tts")
#: tone -> Chatterbox's own knobs
TONES: dict[str, dict] = {
    "neutral": {"exaggeration": 0.45, "cfg_weight": 0.5},
    "warm": {"exaggeration": 0.5, "cfg_weight": 0.55},
    "bright": {"exaggeration": 0.75, "cfg_weight": 0.35},
    "calm": {"exaggeration": 0.3, "cfg_weight": 0.6},
    "serious": {"exaggeration": 0.4, "cfg_weight": 0.6},
    "playful": {"exaggeration": 0.8, "cfg_weight": 0.3},
    "sorry": {"exaggeration": 0.4, "cfg_weight": 0.6},
}


def available(venv_dir: str = DEFAULT_VENV_DIR) -> tuple[bool, str]:
    return engine_available("chatterbox", "chatterbox", venv_dir)


def install(venv_dir: str = DEFAULT_VENV_DIR, *, log=print):
    return create_venv(venv_dir, "chatterbox", packages=PACKAGES, log=log)


class ChatterboxSynthesiser(SubprocessSynthesiser):
    name = "chatterbox"
    module = "chatterbox"
    server = "chatterbox_server.py"

    def __init__(self, config) -> None:
        super().__init__(config, venv_dir=getattr(config, "venv_dir", DEFAULT_VENV_DIR),
                         reference=str(getattr(config, "chatterbox_reference", "") or ""),
                         timeout_s=float(getattr(config, "expressive_timeout_s", 180.0)))
        self._exaggeration = float(getattr(config, "chatterbox_exaggeration", 0.0) or 0.0)

    def params_for(self, tone: str) -> dict:
        params = dict(TONES.get((tone or "neutral").lower(), TONES["neutral"]))
        if self._exaggeration > 0:   # a fixed dial from the settings beats the tone table
            params["exaggeration"] = self._exaggeration
        return params


__all__ = ["ChatterboxSynthesiser", "PACKAGES", "TONES", "available", "install"]
