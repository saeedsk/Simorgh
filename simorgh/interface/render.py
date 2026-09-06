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
import sys

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
    if snapshot.workers_total or snapshot.bus_published:
        lines.append(
            f"workers: {snapshot.workers_busy}/{snapshot.workers_total} busy   "
            f"bus: {snapshot.bus_published} published, {snapshot.bus_delivered} delivered"
        )
    # Live-caught: this used to print the raw per-subsystem metrics dict
    # verbatim under a "budget:" label -- a screenful of nested braces in
    # a panel meant to read at a glance. Only a real per-provider budget
    # is a budget; one short line per provider.
    for name, b in sorted(snapshot.budget.items()):
        cap = f"/{b['max_calls']}" if b.get("max_calls") is not None else ""
        flag = "  (exhausted)" if b.get("exhausted") else ""
        lines.append(f"budget: {name} {b.get('calls', 0)}{cap} calls this window{flag}")
    return "\n".join(lines)


_RULE_WIDTH = 68

# Brand palette and CLI logo -- from docs/brand/simorgh-brand.json (the
# creator's brand system, 2026-09-06); that file is the source of truth,
# these are its values transcribed. 24-bit SGR color only (`38;2;r;g;b`)
# -- still plain color codes, so milestone 94's "SGR only, never cursor
# control" rule holds; a terminal without true color shows the glyphs
# uncolored, and `enabled=False` prints them with no escapes at all.
_BRAND = {
    "gold": (197, 160, 89), "crimson": (139, 0, 0), "lapis": (15, 82, 186),
    "emerald": (80, 200, 120), "amethyst": (153, 102, 204),
}
# Each row: (color, text) segments; every row renders to exactly 27 cells.
_LOGO_ROWS: tuple[tuple[tuple[str, str], ...], ...] = (
    (("gold", "             ▲             "),),
    (("gold", "           ▲ █ ▲           "),),
    (("lapis", "   ◄██▄"), ("gold", "▄▄▄███████▄▄▄"), ("crimson", "▄██►   ")),
    (("lapis", " ◄█████"), ("gold", "█████████████"), ("crimson", "█████► ")),
    (("emerald", "     ▼████"), ("gold", "███████"), ("emerald", "████▼     ")),
    (("amethyst", "       ╰██"), ("gold", "█████"), ("amethyst", "██╯       ")),
    (("gold", "           ▼ █ ▼           "),),
    (("gold", "             ▼             "),),
)


def _rgb(text: str, color: str, *, enabled: bool = True) -> str:
    if not enabled:
        return text
    r, g, b = _BRAND[color]
    return f"\x1b[38;2;{r};{g};{b}m{text}{_RESET}"


def logo(*, enabled: bool = True, width: int = _RULE_WIDTH) -> list[str]:
    """The brand's Unicode Simorgh, one string per row, centered in `width`.
    Callers decide whether to show it at all (`banner()` omits it in the
    pure-ASCII mode)."""
    rows = []
    for segments in _LOGO_ROWS:
        plain_len = sum(len(text) for _, text in segments)
        pad = " " * max(0, (width - plain_len) // 2)
        rows.append(pad + "".join(_rgb(text, color, enabled=enabled) for color, text in segments))
    return rows


_QUICK_COMMANDS: tuple[tuple[str, str], ...] = (
    ("status", "subsystem health at a glance"),
    ("propose <topic>", "draft a new skill, audited before it lands"),
    ("patch <path> <description>", "revise existing code, tested before it lands"),
    ("tasks / work", "see the backlog, advance the next item"),
    ("research <topic>", "investigate a question, no code written"),
    ("project <goal>", "break a goal into tracked steps"),
    ("autonomous [on|off]", "control the idle self-improvement loop"),
    ("vitals", "mood, memory, curiosity as bar meters"),
    ("pause / resume / stop", "hold everything, or let it continue"),
    ("exit", "leave (Ctrl-D also detaches)"),
)


def unicode_mode(setting: str = "auto") -> str:
    """Resolve the `[interface] unicode` setting to `off | auto | full`.
    `auto` degrades to `off` when stdout isn't UTF-8 (a redirected file
    with a legacy locale, some CI shells) -- glyphs that can't be encoded
    would otherwise raise or print as `?`."""
    if setting in ("off", "full"):
        return setting
    encoding = (getattr(sys.stdout, "encoding", None) or "").lower()
    return "auto" if "utf" in encoding else "off"


def banner(*, enabled: bool = True, unicode: str = "auto") -> str:
    """The startup splash. `سی مرغ` ("si morgh", thirty birds) is a pun
    on `سیمرغ` (Simorgh) that IS the point of Attar's `Conference of the
    Birds`: thirty birds journey to find the Simorgh and discover they
    themselves, together, are it -- the same shape as this system's own
    sixteen subsystems composing one being. That's the reference this
    banner actually earns, not decoration for its own sake. Scrolling
    text only (module docstring's hard rule) -- no cursor control, so
    this is exactly what a redirected/piped session sees too, just
    without the color codes.

    `unicode`: `off` is pure ASCII; `auto` uses box-drawing and one
    geometric glyph (present in essentially every monospace font) but
    never non-Latin script; `full` also shows the Persian name. Live-
    caught: the first version put `سیمرغ` in the centered mark line by
    default, and on the creator's terminal it rendered as garbage -- a
    font without Arabic-script glyphs is common, and right-to-left text
    also breaks monospace centering arithmetic. So the script is opt-in,
    and even then it lives in the epigraph, where alignment is irrelevant.
    """
    if unicode == "off":
        rule_ch, mark_plain = "-", "*  SIMORGH  *"
    else:
        rule_ch, mark_plain = "─", "◆  SIMORGH  ◆"
    rule = style(rule_ch * _RULE_WIDTH, "dim", enabled=enabled)
    # The wordmark in the brand's own gold (docs/brand/simorgh-brand.json),
    # bold; falls back to plain text when color is off.
    mark = _rgb(style(mark_plain.center(_RULE_WIDTH), "bold", enabled=enabled), "gold", enabled=enabled)
    name = "Simorgh (سیمرغ)" if unicode == "full" else "Simorgh"
    epigraph = style(
        f'"si morgh": thirty birds, one {name} -- Attar\'s Conference of\n'
        "the Birds. Sixteen subsystems, one self.",
        "dim", enabled=enabled,
    )
    lines = [rule]
    if unicode != "off":
        # Block/geometric glyphs only -- present in essentially every
        # monospace font, unlike the Arabic script this replaced in the
        # centered line; the pure-ASCII mode simply omits the picture.
        lines.extend(logo(enabled=enabled))
    lines += [
        mark,
        rule,
        "",
        epigraph,
        "",
        "Type plain text to chat, or a command below ('/' is optional).",
        "`help` lists everything; here's where to start:",
        "",
    ]
    width = max(len(name) for name, _ in _QUICK_COMMANDS)
    for name, desc in _QUICK_COMMANDS:
        label = style(name.ljust(width), "cyan", enabled=enabled)
        lines.append(f"  {label}   {desc}")
    lines.append(rule)
    return "\n".join(lines)
