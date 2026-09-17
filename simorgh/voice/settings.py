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

import shutil
import textwrap
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


#: `voice set` with no argument, grouped the way a person thinks about
#: their voice rather than the order the dataclass happens to declare
#: them in. The creator, 2026-09-16, looking at the old one-line run of
#: thirty-eight semicolons: "make this visually pleasant ... sim should
#: show options including their current value in a pleasant and
#: organized format".
#:
#: A key missing from every group is NOT dropped -- it falls into the
#: last group. A hand-written list that silently loses a new entry is
#: the drift this codebase keeps being bitten by, and a settings screen
#: that hides a setting is worse than an ugly one that shows it.
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Listening", ("enabled", "auto_listen", "barge_in", "endpoint_silence_ms",
                   "min_speech_ms", "vad_sensitivity", "stt_partials")),
    ("Hearing the words", ("stt", "stt_language", "stt_languages")),
    ("Knowing who is talking", ("speaker_id", "speaker_threshold", "speaker_margin",
                                "speaker_lean", "speaker_refine", "diarize", "diarize_words",
                                "introduce_after_turns", "bystander")),
    ("Speaking", ("tts", "tts_voice", "tts_farsi_voice", "tts_speed", "volume", "output",
                  "speak_replies", "max_spoken_sentences")),
    ("Feeling and the slow engine", ("tone_blend", "expressive_lane", "expressive_min_chars",
                                     "chatterbox_exaggeration", "chatterbox_reference",
                                     "miso_reference", "miso_device")),
    ("Manner", ("connectors", "backchannel")),
    ("Keeping and telling", ("diagnostics", "keep_audio", "keep_transcripts")),
)


def _shown(value: object, kind: type) -> str:
    """A value as a person set it, not as Python holds it."""
    if kind is bool:
        return "on" if value else "off"
    if value is None or value == "":
        return "-"
    return str(value)


def _allowed(kind: type, allowed: object) -> str:
    if kind is bool:
        return "on | off"
    if isinstance(allowed, tuple) and kind in (int, float):
        return f"{allowed[0]} to {allowed[1]}"
    if isinstance(allowed, tuple):
        return " | ".join(str(a) if a != "" else '""' for a in allowed)
    return {int: "a number", float: "a number", str: "text"}.get(kind, "")


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(1, width - 1)] + "\u2026"


#: The engines that are too slow for a spoken turn, so the lane rule
#: sends the turn to the fast one instead (voice/tts/lanes.py).
SLOW_ENGINES = ("chatterbox", "miso")


def _what_you_will_hear(config: Config, key: str) -> list[str]:
    """Why the engine named in `tts` may not be the voice in the room.

    The creator, 2026-09-16: "sim says the voice tts is set as miso, but
    the voice I'm hearing sounds like kokoro". Both were true, and the
    screen said only the first. `tts` names the EXPRESSIVE engine; with
    `expressive_lane = auto` -- the default -- every spoken turn and
    every aside still goes to the fast engine, because Chatterbox and
    Miso answer in seconds and a spoken turn cannot wait. A setting that
    is correct and not what you hear needs to say so where it is read,
    not in a design document.
    """
    if key not in ("tts", "expressive_lane", "expressive_min_chars"):
        return []
    engine = str(getattr(config, "tts", "") or "")
    if engine not in SLOW_ENGINES:
        return []
    lane = str(getattr(config, "expressive_lane", "auto") or "auto")
    if lane == "always":
        return [f"spoken turns are spoken by {engine} -- expect a wait before the first sound"]
    if lane == "off":
        return [f"{engine} is never used: expressive_lane = off"]
    floor = int(getattr(config, "expressive_min_chars", 0) or 0)
    reach = (f"a spoken reply longer than {floor} characters also goes to {engine}"
             if floor else "no spoken reply goes to it (expressive_min_chars = 0)")
    return [f"you will hear the fast engine, not {engine}: expressive_lane = {lane}, so {engine} "
            f"answers typed replies and `voice test` only",
            f"{reach}; `voice set expressive_lane always` sends every turn to {engine}"]


def explain(config: Config, key: str, *, width: int = 0) -> str:
    """One setting: what it is now, what it means, what it accepts.

    The creator typed `voice set tts` on 2026-09-16 and got "tts must be
    one of: ..." -- an error, because an empty value fails validation,
    when he was plainly asking what it was set to. Naming a setting and
    no value is a question, not a malformed command.
    """
    if width <= 0:
        width = shutil.get_terminal_size((100, 24)).columns
    kind, allowed, help_ = SAFE_KEYS[key]
    lines = [f"{key} = {_shown(getattr(config, key, None), kind)}"]
    if help_:
        lines.extend(textwrap.wrap(help_, width=max(24, width - 2),
                                   initial_indent="  ", subsequent_indent="    ") or [])
    choices = _allowed(kind, allowed)
    if choices:
        lines.extend(textwrap.wrap(f"takes: {choices}", width=max(24, width - 2),
                                   initial_indent="  ", subsequent_indent="    ") or [])
    for line in _what_you_will_hear(config, key):
        # Wrapped, never cut: the second half of each of these lines is
        # the part that tells a person what to DO about it.
        lines.extend(textwrap.wrap(line, width=max(24, width - 2),
                                   initial_indent="  ", subsequent_indent="    ") or [])
    lines.append(f"  change it with `voice set {key} <value>`")
    return "\n".join(lines)


def overview(config: Config, *, width: int = 0) -> str:
    """Every settable voice key, grouped, with what it is set to now.

    Stdlib only and no colour: this is the Voice subsystem, which may
    not import Interface's renderer (no subsystem imports another), and
    the string travels over the bus to whatever displays it.

    A hint is shown whole or not at all. Half a hint -- `[on |` -- is
    worse than none: it reads as a broken screen rather than a setting
    whose choices did not fit.
    """
    if width <= 0:
        width = shutil.get_terminal_size((100, 24)).columns
    width = max(48, min(width, 120))

    grouped, seen = [], set()
    for title, keys in GROUPS:
        rows = [k for k in keys if k in SAFE_KEYS]
        seen.update(rows)
        if rows:
            grouped.append((title, rows))
    missing = [k for k in SAFE_KEYS if k not in seen]
    if missing:
        grouped.append(("Other", missing))

    all_keys = [k for _t, ks in grouped for k in ks]
    key_w = max((len(k) for k in all_keys), default=12) + 2
    # One long value (a Piper voice id) must not starve the help on every
    # other row: past the cap it overflows its column instead.
    val_w = min(max((len(_shown(getattr(config, k, None), SAFE_KEYS[k][0])) for k in all_keys),
                    default=6), 12) + 2

    lines = [_fit("voice settings -- change one with `voice set <key> <value>`", width)]
    room = width - 4 - key_w - val_w
    for title, keys in grouped:
        lines.append("")
        lines.append(f"  {title}")
        for key in keys:
            kind, allowed, help_ = SAFE_KEYS[key]
            value = _shown(getattr(config, key, None), kind)
            choices = _allowed(kind, allowed)
            note = help_
            if choices and choices not in ("text", "a number") and choices.lower() not in help_.lower():
                whole = f"{help_}  [{choices}]" if help_ else f"[{choices}]"
                # Whole or nothing: never a hint cut mid-token.
                note = whole if len(whole) <= room else help_
            # A value longer than its column (a Piper voice id) overflows
            # rather than widening every row -- but it must never run
            # straight into the help: `fa_IR-amir-mediumthe Piper voice`
            # read as one broken word, and the line overran the terminal.
            cell = value.ljust(val_w) if len(value) < val_w else value + " "
            row = f"    {key.ljust(key_w)}{cell}"
            left = width - len(row)
            lines.append((row + _fit(note, left)).rstrip() if left > 12 else row.rstrip())
    heard = _what_you_will_hear(config, "tts")
    if heard:
        lines.append("")
        for line in heard:
            lines.extend(textwrap.wrap(line, width=max(24, width - 2),
                                       initial_indent="  ", subsequent_indent="    ") or [])
    return "\n".join(lines)


__all__ = ["GROUPS", "SAFE_KEYS", "apply", "describe", "SLOW_ENGINES", "explain", "overview", "parse", "persist"]
