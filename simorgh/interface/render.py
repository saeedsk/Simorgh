"""Console rendering conventions -- a port of v1's
`src/orchestrator/console_style.py`. Milestone 94 (hard rule, restated
in `docs/blueprint/subsystems/15-interface.md` section 7): scrolling
blocks only, *never* in-place cursor/scroll-region control. The only
escape sequences this module ever emits are SGR color codes
(`\\x1b[...m`); nothing here writes `\\x1b[` cursor-movement, erase, or
scroll-region sequences.
"""

from __future__ import annotations

import os

from .vitals import VitalsSnapshot

_RESET = "\x1b[0m"
_COLORS = {
    "dim": "\x1b[2m", "red": "\x1b[31m", "green": "\x1b[32m", "yellow": "\x1b[33m",
    "blue": "\x1b[34m", "magenta": "\x1b[35m", "cyan": "\x1b[36m", "bold": "\x1b[1m",
}
_LEVEL_COLOR = {"info": "cyan", "warn": "yellow", "error": "red", "success": "green"}


def color_enabled(mode: str = "auto") -> bool:
    if mode == "off":
        return False
    if mode == "on":
        return True
    if os.environ.get("NO_COLOR"):
        return False
    return True


def style(text: str, color: str, *, enabled: bool = True) -> str:
    if not enabled or color not in _COLORS:
        return text
    return f"{_COLORS[color]}{text}{_RESET}"


def notice(level: str, text: str, source: str, *, enabled: bool = True) -> str:
    tag = style(f"[{level}]", _LEVEL_COLOR.get(level, "cyan"), enabled=enabled)
    src = style(f"({source})", "dim", enabled=enabled) if source else ""
    return f"{tag} {text} {src}".rstrip()


def code_block(code: str, *, label: str = "", max_lines: int = 30) -> str:
    lines = code.splitlines() or [""]
    truncated = len(lines) > max_lines
    body = "\n".join(lines[:max_lines])
    header = f"--- {label} ---" if label else "---"
    footer = f"[truncated: {len(lines) - max_lines} more line(s)]" if truncated else "---"
    return f"{header}\n{body}\n{footer}"


def diff_block(lines: list[str], *, label: str = "", max_lines: int = 60, enabled: bool = True) -> str:
    truncated = len(lines) > max_lines
    shown = lines[:max_lines]
    out = []
    for line in shown:
        if line.startswith("+") and not line.startswith("+++"):
            out.append(style(line, "green", enabled=enabled))
        elif line.startswith("-") and not line.startswith("---"):
            out.append(style(line, "red", enabled=enabled))
        else:
            out.append(line)
    header = f"--- {label} ---" if label else "---"
    body = "\n".join(out)
    footer = f"[truncated: {len(lines) - max_lines} more line(s)]" if truncated else "---"
    return f"{header}\n{body}\n{footer}"


def checklist(items: list[tuple[str, str]], title: str = "") -> str:
    """`items`: [(status, label)] where status is one of
    done/doing/pending/failed."""
    icons = {"done": "✅", "doing": "\U0001f3d7️", "pending": "○", "failed": "❌"}
    lines = [title] if title else []
    for status, label in items:
        lines.append(f"{icons.get(status, '-')} {label}")
    return "\n".join(lines)


def _bar(value: float, *, width: int = 10, lo: float = -1.0, hi: float = 1.0) -> str:
    frac = 0.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    filled = round(frac * width)
    return "#" * filled + "-" * (width - filled)


def vitals(snapshot: VitalsSnapshot) -> str:
    if snapshot.stale:
        return "vitals: no data observed yet this run"
    lines = [
        f"mood     [{_bar(snapshot.mood)}] {snapshot.mood:+.2f}  ({snapshot.mood_phrase})",
        f"energy   [{_bar(snapshot.energy)}] {snapshot.energy:+.2f}",
        f"load     [{_bar(snapshot.load, lo=0.0, hi=1.0)}] {snapshot.load:.2f}",
        f"memory records: {snapshot.memory_records}   skills: {snapshot.skills}   interests: {snapshot.interests}",
        f"backlog: {snapshot.backlog}   posture: {snapshot.posture}",
    ]
    if snapshot.budget:
        lines.append(f"budget: {snapshot.budget}")
    return "\n".join(lines)
