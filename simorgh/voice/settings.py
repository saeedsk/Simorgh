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

from dataclasses import fields, replace

from simorgh.contracts.settings import VOICE_SAFE_KEYS as SAFE_KEYS, persist

from .config import Config


def parse(key: str, raw: str) -> tuple[object | None, str]:
    """`(value, problem)` for a `voice set` argument."""
    spec = SAFE_KEYS.get(key)
    if spec is None:
        import difflib

        close = difflib.get_close_matches(key, list(SAFE_KEYS), n=1, cutoff=0.6)
        hint = f"did you mean {close[0]}?" if close else f"one of: {', '.join(sorted(SAFE_KEYS))}"
        return None, f"{key!r} is not a setting you can change here; {hint}"
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


def describe() -> list[tuple[str, str, str]]:
    """`(key, type, help)` for every safe key, for `voice set` alone."""
    return [(key, kind.__name__ if kind is not bool else "on|off", help_) for key, (kind, _a, help_) in SAFE_KEYS.items()]


__all__ = ["SAFE_KEYS", "apply", "describe", "parse", "persist"]
