"""Chatterbox (Resemble AI, MIT): the expressive engine with a dial.
`exaggeration` (0-1) is how much feeling, `cfg_weight` how closely it
follows the reference pacing; a reference WAV of six seconds or more
clones a voice. Runs in its own venv (torch 2.6) as a line server --
see voice/tts/subproc.py. Measured 2026-09-13 on the M3 Pro (MPS): the
model loads in 12 s, the first sentence takes ~19 s, then 2.6 s of
speech in 4.7 s -- an expressive lane, not a fast one."""

from __future__ import annotations

from pathlib import Path

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


#: What a reference voice says, once, when it is rendered from a Kokoro
#: voice: eight seconds or so, plain, a question at the end for range.
REFERENCE_TEXT = ("Hello, this is how I sound. The pool is warm tonight, the garden lights are on, and dinner "
                  "will be ready at six. Shall we go outside for a while, or stay in and read?")


class ChatterboxSynthesiser(SubprocessSynthesiser):
    """Chatterbox has one voice of its own and clones any other from a
    few seconds of audio. So its voice list is: `default`, every WAV in
    `workspace/voice/references/`, and -- when Kokoro's model is here --
    every Kokoro voice, rendered once into a reference clip on first use
    (the creator, 2026-09-13: "I can't see the list of supported voices")."""

    name = "chatterbox"
    module = "chatterbox"
    server = "chatterbox_server.py"

    def __init__(self, config) -> None:
        super().__init__(config, venv_dir=getattr(config, "venv_dir", DEFAULT_VENV_DIR),
                         reference=str(getattr(config, "chatterbox_reference", "") or ""),
                         timeout_s=float(getattr(config, "expressive_timeout_s", 180.0)))
        self._exaggeration = float(getattr(config, "chatterbox_exaggeration", 0.0) or 0.0)
        self._config = config
        self._references = Path(getattr(config, "references_dir", "workspace/voice/references")).expanduser()
        self._kokoro = None
        self._kokoro_tried = False

    def _kokoro_engine(self):
        if self._kokoro is None and not self._kokoro_tried:
            self._kokoro_tried = True
            try:
                from .kokoro import KokoroSynthesiser

                self._kokoro = KokoroSynthesiser(self._config)
            except Exception:  # noqa: BLE001 -- no Kokoro: the list is the WAVs on disk
                self._kokoro = None
        return self._kokoro

    def voices(self) -> list[str]:
        names = ["default"]
        if self._references.is_dir():
            names += sorted(p.stem for p in self._references.glob("*.wav") if not p.name.startswith("."))
        kokoro = self._kokoro_engine()
        if kokoro is not None:
            names += [v for v in kokoro.voices() if v not in names]
        return names

    async def reference_for(self, voice: str) -> str:
        voice = (voice or "").strip()
        if not voice or voice in ("default", "chatterbox"):
            return self._reference
        own = self._references / f"{voice}.wav"
        if own.is_file():
            return str(own)
        kokoro = self._kokoro_engine()
        if kokoro is None or voice not in kokoro.voices():
            return self._reference
        # Render the Kokoro voice once into a reference clip Chatterbox can clone.
        import wave

        audio = await kokoro.synthesise(REFERENCE_TEXT, voice=voice, speed=1.0)
        self._references.mkdir(parents=True, exist_ok=True)
        tmp = own.with_suffix(".wav.part")
        with wave.open(str(tmp), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(audio.sample_rate)
            handle.writeframes(audio.pcm)
        tmp.replace(own)
        return str(own)

    def params_for(self, tone: str) -> dict:
        params = dict(TONES.get((tone or "neutral").lower(), TONES["neutral"]))
        if self._exaggeration > 0:   # a fixed dial from the settings beats the tone table
            params["exaggeration"] = self._exaggeration
        return params


__all__ = ["ChatterboxSynthesiser", "PACKAGES", "REFERENCE_TEXT", "TONES", "available", "install"]
