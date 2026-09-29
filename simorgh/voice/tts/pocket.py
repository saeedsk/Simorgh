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
        venv_dir = config.venv_dir or DEFAULT_VENV_DIR
        ok, why = available(venv_dir)
        if not ok:
            raise ImportError(f"{why} (run `voice models pocket-fa`)")
        # Read as typed. A `getattr` fallback here would be a second
        # source of truth for the same key, which is what
        # `test_config_is_read_typed` exists to stop (caught 2026-09-23,
        # by a drill whose lab could not pass the suite because of it).
        reference = str(config.tts_farsi_reference or DEFAULT_REFERENCE)
        if not Path(reference).is_file():
            raise ImportError(
                f"Pocket-TTS speaks in a voice cloned from a reference clip, and {reference} is not there "
                f"-- `voice models pocket-fa` fetches one, or set [voice] tts_farsi_reference")
        super().__init__(config, venv_dir=venv_dir, reference=str(Path(reference).resolve()),
                         timeout_s=float(config.expressive_timeout_s))
        self._lexicon = parse_lexicon(str(config.tts_farsi_lexicon or ""))

    def voices(self) -> list[str]:
        """Every reference clip beside the configured one: with cloning,
        a voice IS a clip."""
        here = Path(self._reference).parent
        return sorted({Path(self._reference).stem, *(p.stem for p in here.glob("*.wav"))})

    async def synthesise(self, text: str, *, voice: str = "", speed: float = 1.0, tone: str = ""):
        return trim_silence(await super().synthesise(text, voice=voice, speed=speed, tone=tone))

    def params_for(self, tone: str) -> dict:
        """Pocket has no expressiveness knobs; the reference carries the
        manner of speaking. What it does take is the house's word list
        (`tts_farsi_lexicon`): sounds for words its G2P gets wrong."""
        return {"lexicon": dict(self._lexicon)} if self._lexicon else {}


#: The silence a piece keeps at each end once trimmed: a breath, not a gap.
KEEP_LEAD_S = 0.06
KEEP_TAIL_S = 0.12


def trim_silence(audio):
    """`audio` without Pocket's dead air at each end. Every piece came with
    about 0.2 s of silence before and 0.35-0.7 s after, and a reply is said
    a sentence at a time: on the satellite, with the board fetching each
    sentence, that was one to one and a half seconds of nothing between
    sentences -- "hop hop" (the creator, 2026-09-28)."""
    import audioop

    from ..api import Audio

    pcm, rate = audio.pcm, audio.sample_rate
    frame = max(2, int(rate * 0.02)) * 2
    levels = [audioop.rms(pcm[i:i + frame], 2) for i in range(0, max(0, len(pcm) - frame + 1), frame)]
    if not levels or max(levels) == 0:
        return audio
    bar = max(levels) * 0.05
    first = next(i for i, level in enumerate(levels) if level > bar)
    last = len(levels) - 1 - next(i for i, level in enumerate(reversed(levels)) if level > bar)
    start = max(0, first * frame - int(KEEP_LEAD_S * rate) * 2)
    end = min(len(pcm), (last + 1) * frame + int(KEEP_TAIL_S * rate) * 2)
    return Audio(pcm=pcm[start:end], sample_rate=rate)


def parse_lexicon(text: str) -> dict[str, str]:
    """`"سعید=s/id; آران=aran"` -> {"سعید": "s/id", "آران": "aran"}; a
    malformed entry is skipped, never a failed voice."""
    out: dict[str, str] = {}
    for entry in text.replace("\n", ";").split(";"):
        word, sep, sounds = entry.partition("=")
        if sep and word.strip() and sounds.strip():
            out[word.strip()] = sounds.strip()
    return out


__all__ = ["DEFAULT_REFERENCE", "parse_lexicon", "trim_silence", "PACKAGES", "PocketSynthesiser", "available", "fetch_normaliser", "install"]
