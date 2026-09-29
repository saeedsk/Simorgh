"""Chatterbox Persian -- the Farsi voice the creator chose over Pocket by
ear (2026-09-29): Chatterbox's multilingual model with its text-to-speech
half swapped for Thomcles/Chatterbox-TTS-Persian-Farsi (CC-BY-NC-4.0,
gated; fetched with a Hugging Face login into
`workspace/voice/engines/chatterbox-fa/`).

It reads Persian letters (and the short-vowel marks) directly, and clones
the voice of `[voice] tts_farsi_reference` -- a native speaker's clip: a
voice's accent comes with it (the ElevenLabs "Hope" clip cloned with a
foreign accent, "Roya", a Tehrani narrator, without).

Slower than Pocket, and the creator took that trade: on the M3 Pro's GPU
about 2.3 s to make each second of speech after a 10 s load. Runs in the
Chatterbox venv as a line server (voice/tts/subproc.py).
"""

from __future__ import annotations

from pathlib import Path

from .pocket import trim_silence
from .subproc import DEFAULT_VENV_DIR, SubprocessSynthesiser, engine_available

ENGINE = "chatterbox_fa"
DEFAULT_WEIGHTS = "workspace/voice/engines/chatterbox-fa/t3_fa.safetensors"
#: The fine-tune author's own settings (his inference notebook); lower
#: cfg_weight or top_p 1.0 cut sentences short or wandered in the tests.
PARAMS = {"temperature": 0.7, "cfg_weight": 0.5, "top_p": 0.5, "exaggeration": 0.6}


def available(venv_dir: str = DEFAULT_VENV_DIR) -> tuple[bool, str]:
    return engine_available("chatterbox", "chatterbox", venv_dir)


class ChatterboxFarsiSynthesiser(SubprocessSynthesiser):
    name = ENGINE
    venv_name = "chatterbox"
    module = "chatterbox"
    server = "chatterbox_fa_server.py"
    rate = 24000
    load_timeout_s = 900.0

    def __init__(self, config) -> None:
        weights = Path(str(config.tts_farsi_chatterbox_weights or DEFAULT_WEIGHTS)).expanduser()
        if not weights.is_file():
            raise ImportError(f"Chatterbox Persian needs its weights at {weights} -- fetch "
                              "Thomcles/Chatterbox-TTS-Persian-Farsi (gated; `hf auth login` first)")
        reference = str(config.tts_farsi_reference or "")
        super().__init__(config, venv_dir=getattr(config, "venv_dir", DEFAULT_VENV_DIR),
                         reference=str(Path(reference).resolve()) if reference and Path(reference).is_file() else "",
                         timeout_s=float(config.expressive_timeout_s))
        self.extra_env = {"CHATTERBOX_FA_WEIGHTS": str(weights.resolve()), "PYTORCH_ENABLE_MPS_FALLBACK": "1"}

    def voices(self) -> list[str]:
        return [Path(self._reference).stem] if self._reference else ["default"]

    def params_for(self, tone: str) -> dict:
        return dict(PARAMS)

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = ""):
        return trim_silence(await super().synthesise(text, voice=voice, speed=speed, tone=tone))


__all__ = ["ChatterboxFarsiSynthesiser", "DEFAULT_WEIGHTS", "ENGINE", "PARAMS", "available"]
