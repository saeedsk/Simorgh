"""StyleTTS 2: expressive, and faster than it speaks.

Suggested by Gemini via the creator, 2026-09-17, as "a strong middle
ground" between Kokoro's speed and MisoTTS's naturalness -- and unlike
most such suggestions, the measurement agreed. On the M3 Pro:

    load                 5 s
    cold   5.30 s of audio in 4.69 s  ->  0.89x real time
    warm   2.67 s of audio in 1.12 s  ->  0.42x real time

Against the rest of the field measured here -- Kokoro 0.19x, Chatterbox
~1.8x, MisoTTS ~10x -- it is the only expressive-class engine that
renders faster than it speaks, so it can carry a SPOKEN turn rather than
sitting in a slow lane behind one. Its `pace_ratio` is under the 1.15
threshold, so it needs none of the special waiting the slow lane does.

The premise worth correcting, since it shapes what to expect: this is
not a new class of engine beside Kokoro. Kokoro-82M is StyleTTS 2 +
ISTFTNet distilled -- its ONNX graph takes a `style [1, 256]` vector and
its voice bank is 54 packs of exactly those. What the distillation drops
is what this adds: a diffusion style sampler (a different style per
utterance instead of one fixed vector per voice), style taken from a
reference clip, and the emotion dial below.

`embedding_scale` is that dial, in the package's own words: "higher
scale means style is more conditional to the input text and hence more
emotional". `diffusion_steps` buys variety for time. `alpha` and `beta`
set how far timbre and prosody follow the text rather than the
reference voice.
"""

from __future__ import annotations

from pathlib import Path

from ..api import Audio
from .subproc import DEFAULT_VENV_DIR, SubprocessSynthesiser, create_venv, engine_available

#: Installed first; torch is pinned afterwards, because resolution picks
#: a torch whose `torch.load` defaults to `weights_only=True` and the
#: package's own checkpoint loader does not pass it -- the load then dies
#: on `UnpicklingError: Weights only load failed`. Measured 2026-09-17
#: with torch 2.14; 2.5.1 loads.
PACKAGES = ("styletts2",)
TORCH_PIN = ("torch==2.5.1", "torchaudio==2.5.1")

#: tone -> StyleTTS 2's own knobs. `embedding_scale` is the emotional
#: one; `diffusion_steps` is variety bought with time, and this engine
#: has time to spare at 0.42x.
TONES: dict[str, dict] = {
    "neutral": {"alpha": 0.3, "beta": 0.7, "diffusion_steps": 5, "embedding_scale": 1.0},
    "warm": {"alpha": 0.3, "beta": 0.7, "diffusion_steps": 6, "embedding_scale": 1.2},
    "bright": {"alpha": 0.4, "beta": 0.8, "diffusion_steps": 8, "embedding_scale": 1.5},
    "calm": {"alpha": 0.2, "beta": 0.6, "diffusion_steps": 5, "embedding_scale": 0.8},
    "serious": {"alpha": 0.2, "beta": 0.6, "diffusion_steps": 5, "embedding_scale": 0.9},
    "playful": {"alpha": 0.4, "beta": 0.8, "diffusion_steps": 10, "embedding_scale": 1.6},
    "sorry": {"alpha": 0.2, "beta": 0.6, "diffusion_steps": 5, "embedding_scale": 0.85},
}


def available(venv_dir: str = DEFAULT_VENV_DIR) -> tuple[bool, str]:
    """Asked about ITSELF, not about torch -- the mistake that let a
    broken MisoTTS report ready all evening (2026-09-16)."""
    return engine_available("styletts2", "styletts2", venv_dir)


def install(venv_dir: str = DEFAULT_VENV_DIR, *, log=print):
    py, problem = create_venv(venv_dir, "styletts2", python="3.10", packages=PACKAGES, log=log)
    if py is None:
        return py, problem
    # After, not with: the package install is what drags the newer torch
    # in, so pinning beside it would be undone by it.
    log("  pinning torch<2.6 (its checkpoint loader predates weights_only) ...")
    import shutil
    import subprocess

    uv = shutil.which("uv")
    cmd = ([uv, "pip", "install", "--python", str(py), *TORCH_PIN] if uv
           else [str(py), "-m", "pip", "install", "-q", *TORCH_PIN])
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if done.returncode != 0:
        return None, f"could not pin torch: {(done.stderr or done.stdout).strip()[-300:]}"
    return py, ""


class StyleTTS2Synthesiser(SubprocessSynthesiser):
    """StyleTTS 2 in its own venv, spoken through the line protocol."""

    name = "styletts2"
    module = "styletts2"
    server = "styletts2_server.py"
    #: The first run fetches the LibriTTS weights; after that it is 5 s.
    load_timeout_s = 900.0
    #: Measured cold on the M3 Pro; warm it runs 0.42x. Under 1.15, so
    #: the player keeps its ordinary floor and the fast-lane guard that
    #: stops a mute Sim is untouched.
    nominal_pace = 0.9

    def __init__(self, config) -> None:
        super().__init__(config, venv_dir=getattr(config, "venv_dir", DEFAULT_VENV_DIR),
                         reference=str(getattr(config, "styletts2_reference", "") or ""),
                         timeout_s=float(getattr(config, "expressive_timeout_s", 180.0)))
        self._config = config
        self._scale = float(getattr(config, "styletts2_embedding_scale", 0.0) or 0.0)
        self._references = Path(getattr(config, "references_dir", "workspace/voice/references")).expanduser()

    #: StyleTTS 2 cannot say a word or two. Measured 2026-09-19: "Yes." came
    #: back 2.2 s of steady loud sound at speed 1.0 and a murmur at 1.3, while
    #: "Sure thing." and longer were clean -- the creator heard it as white
    #: noise before every reply, where the aside "Yes." played. Text this
    #: short goes to Kokoro in the voice of the same name (the reference
    #: clips were made from Kokoro's af_* voices).
    SHORT_WORDS = 2

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = "") -> Audio:
        if len((text or "").split()) <= self.SHORT_WORDS:
            short = self._short_engine()
            if short is not None:
                names = set(short.voices())
                return await short.synthesise(text, voice=voice if voice in names else "", speed=speed)
        return await super().synthesise(text, voice=voice, speed=speed, tone=tone)

    def _short_engine(self):
        if not hasattr(self, "_short"):
            try:
                from .kokoro import KokoroSynthesiser

                self._short = KokoroSynthesiser(self._config)
            except Exception:  # noqa: BLE001 -- no Kokoro: StyleTTS 2 says it as best it can
                self._short = None
        return self._short

    def voices(self) -> list[str]:
        names = ["default"]
        if self._references.is_dir():
            names += sorted(p.stem for p in self._references.glob("*.wav") if not p.name.startswith("."))
        return names

    async def reference_for(self, voice: str) -> str:
        voice = (voice or "").strip()
        if not voice or voice in ("default", "styletts2"):
            return self._reference
        own = self._references / f"{voice}.wav"
        return str(own) if own.is_file() else self._reference

    def params_for(self, tone: str) -> dict:
        params = dict(TONES.get((tone or "neutral").lower(), TONES["neutral"]))
        if self._scale > 0:     # a fixed dial from the settings beats the tone table
            params["embedding_scale"] = self._scale
        return params


__all__ = ["PACKAGES", "TONES", "TORCH_PIN", "StyleTTS2Synthesiser", "available", "install"]
