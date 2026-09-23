"""Pocket-TTS Farsi v2 -- the Farsi voice the creator chose.

Piper's five Persian voices are VITS-medium from one training run and
share a family resemblance; MMS is a different model but speaks at 16
kHz. Pocket-TTS v2 is 24 kHz, and its voice is CLONED from a reference
clip of about five seconds -- so the voice is a choice rather than a
fixed set of five. The creator, 2026-09-22, having heard all three:
"I like pocket-farsi-v2.wav, make it as default farsi tts voice and
model."

Measured here the same evening: phonemes in 0.3 s, then 5.9 s of speech
in 0.8 s -- seven times real time.

Two things make it unlike the other engines:

  it reads PHONEMES, not Persian script, so a small T5 (`Homo-GE2PE`)
  runs in front of it inside the same server; and

  it is CC-BY-NC. Fine for a household, and it must not ship in
  anything sold -- which is why it is opt-outable rather than
  hard-wired, and why `[voice] tts_farsi = "piper"` remains a real
  answer.

Its package installs from git and pins nothing this repository's Python
has, so it lives in a venv of its own like the expressive engines, and
speaks over the JSON-lines protocol in `subproc.py`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .subproc import DEFAULT_VENV_DIR, SubprocessSynthesiser, create_venv, engine_available

#: `--system-site-packages`: torch and transformers are already here for
#: kokoro, silero and the G2P, and a second copy is 2.5 GB for nothing.
PACKAGES = ("pocket-tts @ git+https://github.com/mallahyari/pocket-tts@main",)
ENGINE = "pocket"

#: The reference clip Sim speaks Farsi in. Any WAV of about five
#: seconds works; this is the one the creator picked.
DEFAULT_REFERENCE = "workspace/voice/prompts/farsi.wav"
#: Shipped by the model's own repository, and needed by the server: the
#: normaliser that folds Arabic/Persian spelling variants before the G2P
#: sees them.
NORMALISER_URL = "https://huggingface.co/mehdi-hf/pocket-tts-farsi-v2/resolve/main/normalize_fa.py"


def available(venv_dir: str = DEFAULT_VENV_DIR) -> tuple[bool, str]:
    return engine_available(ENGINE, "pocket_tts", venv_dir)


def install(venv_dir: str = DEFAULT_VENV_DIR, *, log=print):
    """The venv, the package, and the model's own normaliser beside the
    server. The two models themselves download on first use."""
    path, problem = create_venv(venv_dir, ENGINE, packages=PACKAGES, log=log,
                                system_site_packages=True)
    if path is None:
        return None, problem
    fetched, why = fetch_normaliser(log=log)
    if not fetched:
        log(f"  note: {why}")
    return path, ""


#: Where the model's own files live. NOT inside `simorgh/`: that is this
#: project's source, and `normalize_fa.py` is somebody else's, fetched
#: at install time -- the module-boundary rule catches it the moment it
#: lands in the package, which is exactly what the rule is for.
ENGINE_DIR = "workspace/voice/engines/pocket"


def fetch_normaliser(*, servers_dir: Path | None = None, log=print) -> tuple[bool, str]:
    """`normalize_fa.py` where the server can import it, from the
    model's own repository.

    The server falls back to passing text through unchanged when it is
    missing, which still speaks -- just less consistently, since the
    same word spelt with an Arabic yeh and a Persian one becomes two
    different phoneme strings.
    """
    import urllib.request

    target = Path(servers_dir or ENGINE_DIR)
    target.mkdir(parents=True, exist_ok=True)
    target = target / "normalize_fa.py"
    if target.is_file():
        return True, ""
    try:
        with urllib.request.urlopen(NORMALISER_URL, timeout=60) as response:  # noqa: S310 -- fixed https model repo
            body = response.read()
        target.write_bytes(body)
    except Exception as exc:  # noqa: BLE001 -- a missing normaliser is a note, not a failure
        return False, f"could not fetch normalize_fa.py: {exc}"
    return True, ""


class PocketSynthesiser(SubprocessSynthesiser):
    name = ENGINE
    module = "pocket_tts"
    server = "pocket_server.py"
    rate = 24000
    load_timeout_s = 900.0      # 438 MB of weights plus the G2P, the first time

    def __init__(self, config) -> None:
        venv_dir = getattr(config, "venv_dir", DEFAULT_VENV_DIR)
        ok, why = available(venv_dir)
        if not ok:
            raise ImportError(f"{why} (run `voice models pocket-fa`)")
        reference = str(getattr(config, "tts_farsi_reference", "") or DEFAULT_REFERENCE)
        if not Path(reference).is_file():
            raise ImportError(
                f"Pocket-TTS speaks in a voice cloned from a reference clip, and {reference} is not there "
                f"-- `voice models pocket-fa` fetches one, or set [voice] tts_farsi_reference")
        super().__init__(config, venv_dir=venv_dir, reference=str(Path(reference).resolve()),
                         timeout_s=float(getattr(config, "expressive_timeout_s", 180.0)))

    def voices(self) -> list[str]:
        """Every reference clip beside the configured one: with cloning,
        a voice IS a clip."""
        here = Path(self._reference).parent
        return sorted({Path(self._reference).stem, *(p.stem for p in here.glob("*.wav"))})

    def params_for(self, tone: str) -> dict:
        """Pocket has no expressiveness knobs; the reference carries the
        manner of speaking."""
        return {}


__all__ = ["DEFAULT_REFERENCE", "PACKAGES", "PocketSynthesiser", "available", "fetch_normaliser", "install"]
