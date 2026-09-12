"""`voice set <key> <value>`: the safe settings, persisted.

Only the keys a person should reach from the prompt are here -- the
design's VoiceSettings, by the names `config.py` uses. Nothing that
names a model path, a command or a device string is settable this
way: those stay in `simorgh.toml` under the operator's own hand. A
value is checked against its type and range before it is written, and
what is written is the `[voice]` table of the data directory's
`simorgh.toml`, which `kernel/config.py` reads at the next boot; the
running service applies it at once.
"""

from __future__ import annotations

import tomllib
from dataclasses import fields, replace
from pathlib import Path

from .config import Config

#: key -> (type, allowed values or (low, high) range, help)
SAFE_KEYS: dict[str, tuple[type, object, str]] = {
    "enabled": (bool, None, "listen on boot"),
    "tts_voice": (str, None, "the voice id (Kokoro: af_heart, af_jessica, ...; `voice voices` lists them)"),
    "tts_farsi_voice": (str, None, "the Piper voice for Farsi"),
    "stt_language": (str, None, "\"\" to detect, or a code such as en, fa"),
    "tts_speed": (float, (0.5, 2.0), "speaking rate, 1.0 = normal"),
    "volume": (float, (0.2, 2.0), "playback gain"),
    "auto_listen": (bool, None, "listen again after each reply"),
    "barge_in": (bool, None, "interrupt Sim by talking"),
    "endpoint_silence_ms": (int, (200, 3000), "silence that ends your turn"),
    "min_speech_ms": (int, (50, 2000), "shorter than this is not a turn"),
    "vad_sensitivity": (str, ("low", "balanced", "high"), "how sure the detector must be"),
    "tts": (str, ("auto", "kokoro", "piper", "say", "fake"), "the voice engine; say is the system fallback"),
    "stt": (str, ("auto", "faster_whisper", "whisper_cli", "fake"), "the recogniser"),
    "stt_partials": (bool, None, "show what is heard while you are still talking"),
    "connectors": (bool, None, "the rare Okay / Yeah lead-ins"),
    "max_spoken_sentences": (int, (1, 30), "longer answers are cut and say there is more on screen"),
    "diagnostics": (bool, None, "per-turn latencies in voice status"),
    "keep_audio": (bool, None, "keep raw recordings under workspace/voice/audio (off by default)"),
    "keep_transcripts": (bool, None, "ledger the transcripts"),
    "speak_replies": (bool, None, "speak replies to typed turns too"),
}


def parse(key: str, raw: str) -> tuple[object | None, str]:
    """`(value, problem)` for a `voice set` argument."""
    spec = SAFE_KEYS.get(key)
    if spec is None:
        return None, f"{key!r} is not a setting you can change here; one of: {', '.join(sorted(SAFE_KEYS))}"
    kind, allowed, _help = spec
    text = raw.strip().strip('"')
    try:
        if kind is bool:
            if text.lower() not in ("on", "off", "true", "false", "yes", "no", "1", "0"):
                return None, f"{key} takes on or off"
            value: object = text.lower() in ("on", "true", "yes", "1")
        elif kind is int:
            value = int(text)
        elif kind is float:
            value = float(text)
        else:
            value = text
    except ValueError:
        return None, f"{key} takes a {kind.__name__}, not {raw!r}"
    if isinstance(allowed, tuple) and kind in (int, float):
        low, high = allowed
        if not (low <= value <= high):
            return None, f"{key} must be between {low} and {high}"
    elif isinstance(allowed, tuple) and kind is str and value not in allowed:
        return None, f"{key} must be one of: {', '.join(allowed)}"
    return value, ""


def apply(config: Config, key: str, value: object) -> Config:
    if key not in {f.name for f in fields(Config)}:
        raise KeyError(key)
    return replace(config, **{key: value})


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
    """A small TOML writer for what `simorgh.toml` holds: scalar keys at
    the top, then one `[section]` per table of scalars (and one level
    of `[section.sub]`). Enough for a settings file; not a general one."""
    lines: list[str] = []
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {_toml_value(value)}")
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append("")
            lines.append(f"[{key}]")
            for k, v in value.items():
                if isinstance(v, dict):
                    continue
                lines.append(f"{k} = {_toml_value(v)}")
            for k, v in value.items():
                if isinstance(v, dict):
                    lines.append("")
                    lines.append(f"[{key}.{k}]")
                    for k2, v2 in v.items():
                        lines.append(f"{k2} = {_toml_value(v2)}")
    return "\n".join(lines).strip() + "\n"


def persist(path: Path, key: str, value: object) -> None:
    """Write `[voice] key = value` into the TOML at `path`, keeping every
    other setting the file already has."""
    data: dict = {}
    if path.is_file():
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    voice = dict(data.get("voice") or {})
    voice[key] = value
    data["voice"] = voice
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.part")
    tmp.write_text(_dump(data))
    tmp.replace(path)


def describe() -> list[tuple[str, str, str]]:
    """`(key, type, help)` for every safe key, for `voice set` alone."""
    return [(key, kind.__name__ if kind is not bool else "on|off", help_) for key, (kind, _a, help_) in SAFE_KEYS.items()]


__all__ = ["SAFE_KEYS", "apply", "describe", "parse", "persist"]
