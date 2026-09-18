"""Where Sim's settings live, and the one-time hand-off of a secret from
the terminal to a tool.

A password typed on a command line becomes a tool proposal, and every
proposal is ledgered -- so `cameras setup <host> <user> <password>` had
been writing the NVR's password into the ledger (the creator,
2026-09-12: "the password may leak to sim logs"). The terminal now asks
for the password hidden (`getpass`), writes it to a hand-off file only
the owner can read, and the tool reads and deletes that file; the
proposal carries no password at all.

`settings_home()` mirrors the Kernel's search order for `simorgh.toml`
(`$SIMORGH_CONFIG`, `./simorgh.toml`, `~/.simorgh/`) without importing
the Kernel, so both the interface and execution agree on the directory.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path


def settings_home(home: Path | None = None) -> Path:
    if home is not None:
        return Path(home)
    env = os.environ.get("SIMORGH_CONFIG")
    if env:
        return Path(env).expanduser().parent
    if Path("simorgh.toml").is_file():
        return Path.cwd()
    return Path("~/.simorgh").expanduser()


def handoff_path(name: str, home: Path | None = None) -> Path:
    safe = "".join(ch for ch in name.lower() if ch.isalnum() or ch in "-_") or "secret"
    return settings_home(home) / f"handoff-{safe}.json"


def write_handoff(name: str, values: dict[str, str], home: Path | None = None) -> Path:
    """Write `values` for one tool to read once; owner-only, atomic."""
    path = handoff_path(name, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(values), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    path.chmod(0o600)
    return path


def read_handoff(name: str, home: Path | None = None) -> dict[str, str]:
    """The values handed off, deleting the file; {} when there is none."""
    path = handoff_path(name, home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


# `voice set`'s keys live here, not in voice/, because the prompt's completion
# (interface) reads them too and one subsystem does not import another.
#: key -> (type, allowed values or (low, high) range, help)
VOICE_SAFE_KEYS: dict[str, tuple[type, object, str]] = {
    "enabled": (bool, None, "listen on boot"),
    "tts_voice": (str, None, "the voice id (Kokoro: af_heart, af_jessica, ...; `voice voices` lists them)"),
    "tts_farsi_voice": (str, None, "the Piper voice for Farsi"),
    "stt_language": (str, None, "\"\" to detect, or a code such as en, fa"),
    "stt_languages": (str, None, "the languages the house speaks, e.g. en,fa -- a turn heard in another is not answered; \"\" for any"),
    "tts_speed": (float, (0.5, 2.0), "speaking rate, 1.0 = normal"),
    "speaker_id": (str, ("auto", "on", "off"), "auto | on | off -- recognise who is speaking (needs `voice enroll`)"),
    "speaker_threshold": (float, (0.2, 0.95), "how alike a voice must be to count as an enrolled person (cosine)"),
    "speaker_margin": (float, (0.0, 0.5), "how far the best match must beat the second before it counts"),
    "speaker_lean": (float, (0.0, 0.95), "under the threshold but at least this close, a voice is 'probably' that person; 0 = never lean"),
    "speaker_refine": (bool, None, "a turn Sim is sure about quietly becomes another take for that person"),
    "diarize": (bool, None, "a long turn's words are attributed to who said them, voice by voice"),
    "diarize_words": (bool, None, "time every word for finer attribution (about half a second slower a turn)"),
    "introduce_after_turns": (int, (0, 10), "turns from an unknown voice before Sim asks who it is (0 = never ask; enrol with `voice enroll` or 'Sim, learn my voice')"),
    "bystander": (bool, None, "stay quiet while two known people talk to each other, unless named"),
    "tone_blend": (float, (0.0, 2.0), "how much a feeling colours the voice (Kokoro blends voices); 0 = plain, 1 = normal"),
    "volume": (float, (0.2, 2.0), "playback gain"),
    "output": (str, ("laptop", "tv", "both"), "where the voice comes out: this machine, the TV page, or both"),
    "auto_listen": (bool, None, "listen again after each reply"),
    "barge_in": (bool, None, "interrupt Sim by talking"),
    "endpoint_silence_ms": (int, (200, 3000), "silence that ends your turn"),
    "min_speech_ms": (int, (50, 2000), "shorter than this is not a turn"),
    "vad_sensitivity": (str, ("low", "balanced", "high"), "how sure the detector must be"),
    "tts": (str, ("auto", "kokoro", "piper", "say", "chatterbox", "styletts2", "miso", "fake"),
            "the voice engine: kokoro (fast), styletts2 (expressive AND fast), chatterbox / miso "
            "(expressive but slower than speech); the last three live in their own venvs, `voice models <name>` first"),
    "chatterbox_exaggeration": (float, (0.0, 1.0), "Chatterbox's feeling dial; 0 lets the tone table choose"),
    "chatterbox_reference": (str, None, "a WAV (6 s or more) whose voice Chatterbox clones; \"\" for its own"),
    "miso_reference": (str, None, "a WAV whose voice MisoTTS follows; \"\" for its default speaker"),
    "miso_device": (str, ("", "mps", "cpu", "cuda"), "where MisoTTS runs; \"\" picks the best available"),
    "styletts2_reference": (str, None, "a WAV whose voice StyleTTS 2 follows; \"\" for its own"),
    "styletts2_embedding_scale": (float, (0.0, 3.0), "StyleTTS 2's emotion dial; 0 lets the tone table choose"),
    "stt": (str, ("auto", "faster_whisper", "whisper_server", "whisper_cli", "sherpa", "fake"),
            "the recogniser: sherpa streams the words as you say them (English), whisper_server keeps the "
            "model loaded, whisper_cli reloads it every turn"),
    "expressive_lane": (str, ("auto", "always", "off"),
                        "when Chatterbox/Miso speaks: auto = typed replies, tests and long answers only (spoken turns stay quick); always; off"),
    "expressive_min_chars": (int, (0, 5000), "0 = never (default); else a spoken reply at least this long goes to the slow engine -- it can hold the floor a minute"),
    "stt_partials": (bool, None, "show what is heard while you are still talking"),
    "connectors": (bool, None, "the rare Okay / Yeah lead-ins"),
    "backchannel": (bool, None, "say Aha / Let me check the moment your turn ends, before thinking"),
    "max_spoken_sentences": (int, (1, 30), "longer answers are cut and say there is more on screen"),
    "diagnostics": (bool, None, "per-turn latencies in voice status"),
    "keep_audio": (bool, None, "keep raw recordings under workspace/voice/audio (off by default)"),
    "keep_transcripts": (bool, None, "ledger the transcripts"),
    "speak_replies": (bool, None, "speak replies to typed turns too"),
}


#: The whole reply when the model heard words that were not for it
#: (orchestration/scaffolds.py tells it so in those words). Voice does not
#: speak it; Memory must not remember it. Here because both read it and
#: neither may import the other.
QUIET_REPLY = "QUIET"


def is_quiet_reply(text: str) -> bool:
    """`QUIET` alone, however wrapped or punctuated.

    446 of the creator's 2,422 episodic records ended "Sim: QUIET"
    (2026-09-16) -- turns Sim judged were not for it, stayed silent on,
    and wrote down anyway. Among them a work meeting: colleagues' names
    and business talk, kept because the turn was not empty.
    """
    return bool(_QUIET_ONLY.match((text or "").strip()))


_QUIET_ONLY = re.compile(r"^\W*quiet\W*$", re.I)


def config_path() -> Path:
    """The `simorgh.toml` the Kernel reads: `$SIMORGH_CONFIG`, then
    `./simorgh.toml`, then `~/.simorgh/simorgh.toml` -- kernel/config.py's
    `find_config_path` order, without importing the Kernel."""
    env = os.environ.get("SIMORGH_CONFIG")
    if env:
        return Path(env).expanduser()
    if Path("simorgh.toml").is_file():
        return Path("simorgh.toml")
    return Path("~/.simorgh").expanduser() / "simorgh.toml"


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def _dump(data: dict) -> str:
    """A small TOML writer for what `simorgh.toml` holds: scalars first,
    then a `[header]` per table, nested to any depth.

    It stopped at two levels, and `persist` rewrites the WHOLE file to
    change one key. So every `voice set` turned
    `[cognition.providers.ollama]` -- three deep -- into a Python dict
    inside a quoted string, because a dict that reached `_toml_value`
    fell through to `str(value)`. The provider then vanished from the
    order, and the cameras had nothing that could look at a picture.
    Live twice: 2026-09-15, and again at 09:07 the next morning after
    the first repair (the creator's screen: "nothing here can look at a
    picture ... tried: together, claude_code_cli, gemini, floor").

    A settings writer that silently drops part of the settings is worse
    than one that refuses, because nothing says so until something
    downstream is mysteriously off.
    """
    def table(value: dict, path: tuple[str, ...]) -> list[str]:
        lines: list[str] = []
        if path:
            lines.append("")
            lines.append("[" + ".".join(path) + "]")
        lines += [f"{k} = {_toml_value(v)}" for k, v in value.items() if not isinstance(v, dict)]
        for k, v in value.items():
            if isinstance(v, dict):
                lines += table(v, (*path, k))
        return lines

    return "\n".join(table(data, ())).strip() + "\n"


def persist(path: Path, key: str, value: object, *, section: str = "voice") -> None:
    """Write `[section] key = value` into the TOML at `path`, keeping
    every other setting the file already has. `[voice]` by default; the
    cast tools write `[execution] cast_device` the same way."""
    data: dict = {}
    if path.is_file():
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    table = dict(data.get(section) or {})
    table[key] = value
    data[section] = table
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.part")
    tmp.write_text(_dump(data))
    tmp.replace(path)


__all__ = ["QUIET_REPLY", "VOICE_SAFE_KEYS", "is_quiet_reply", "config_path", "handoff_path", "persist", "read_handoff", "settings_home",
           "write_handoff"]
