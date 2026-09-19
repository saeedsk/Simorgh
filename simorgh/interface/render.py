"""Console rendering conventions -- a port of v1's
`src/orchestrator/console_style.py`. Milestone 94 (hard rule, restated
in `docs/blueprint/subsystems/15-interface.md` section 7): scrolling
blocks only, *never* in-place cursor/scroll-region control. The only
escape sequences this module ever emits are SGR color codes
(`\\x1b[...m`); nothing here writes `\\x1b[` cursor-movement, erase, or
scroll-region sequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import os
import re
import shutil
import sys

from .parser import SPLASH_COMMANDS as _SPLASH_COMMANDS, command_help as _command_help
from .vitals import VitalsSnapshot

_RESET = "\x1b[0m"
_COLORS = {
    "dim": "\x1b[2m", "red": "\x1b[31m", "green": "\x1b[32m", "yellow": "\x1b[33m",
    "blue": "\x1b[34m", "magenta": "\x1b[35m", "cyan": "\x1b[36m", "bold": "\x1b[1m",
    # The breathing line's muted tan (tui.BREATH_COLOURS), for the quiet
    # lines that keep it company -- "listening..." was the one cold line
    # left beside it (the creator, 2026-09-12).
    "warm": "\x1b[38;2;172;127;79m",
}
_LEVEL_COLOR = {"info": "cyan", "warn": "yellow", "error": "red", "success": "green"}


# The creator, 2026-09-08: "some of the sim agent text on tui are
# limited and not using the whole cli width". Every narration line used
# to truncate at a constant chosen for an 80-column terminal, so a wide
# window showed the same clipped topic with empty space beside it. One
# helper, so a line is cut to fit the screen someone actually has.
_MIN_WIDTH = 60
_MAX_WIDTH = 200


# An ANSI sequence occupies no columns. Measuring it as text made every
# coloured line look wider than it is, and cutting one could slice
# through an escape and leave the terminal mid-sequence (caught by the
# banner's own "no stray escapes" test, 2026-09-08).
_ANSI = re.compile(r"\x1b\[[0-9;:]*[A-Za-z]")


def _cell_width(ch: str) -> int:
    import unicodedata

    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) > 0x1F000 else 1


def display_width(text: str) -> int:
    """Columns `text` occupies on screen. Escape sequences are free; an
    emoji is two cells, not one -- every feed line was measured 1-2
    cells narrow (observer, 2026-09-08)."""
    return sum(_cell_width(ch) for ch in _ANSI.sub("", text or ""))


def fit(text: str, width: int, *, ellipsis: str = "…") -> str:
    """`text` cut to at most `width` display columns, escapes intact.

    Cuts between characters, never inside an escape sequence, and
    carries any sequences from the cut-off tail so a cut line cannot
    leave the terminal coloured."""
    if display_width(text) <= width:
        return text
    room = max(1, width - display_width(ellipsis))
    out: list[str] = []
    used = 0
    index = 0
    dropped_escape = False
    while index < len(text):
        match = _ANSI.match(text, index)
        if match:
            if used < room:
                out.append(match.group(0))
            else:
                dropped_escape = True
            index = match.end()
            continue
        cell = _cell_width(text[index])
        if used + cell > room:
            dropped_escape = dropped_escape or bool(_ANSI.search(text, index))
            break
        out.append(text[index])
        used += cell
        index += 1
    tail = ellipsis + ("\x1b[0m" if dropped_escape else "")
    return "".join(out) + tail


def terminal_width(default: int = 100) -> int:
    """Usable columns. Bounded at both ends: a 20-column report of a
    terminal that is really wider (a pipe, a CI log) would clip
    everything, and a 400-column line is unreadable however wide the
    window is."""
    try:
        columns = shutil.get_terminal_size((default, 24)).columns
    except Exception:  # noqa: BLE001 -- no terminal at all
        columns = default
    return max(_MIN_WIDTH, min(_MAX_WIDTH, columns))


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


def one_safe_line(text: str, *, limit: int = 200) -> str:
    """Text somebody else wrote, rendered as one harmless line.

    A reminder's label is whatever a person or a model typed, and it was
    printed to the terminal verbatim: `\x1b[2J` cleared the screen,
    newlines printed a paragraph where one line was expected, and 20,000
    characters printed 20,000 (observer, 2026-09-10). Anything the
    system echoes back from outside itself belongs here."""
    cleaned = "".join(
        ch if ch.isprintable() or ch == " " else " "
        for ch in (text or "")
    )
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return cleaned


def notice(level: str, text: str, source: str, *, enabled: bool = True) -> str:
    tag = style(f"[{level}]", _LEVEL_COLOR.get(level, "cyan"), enabled=enabled)
    src = style(f"({source})", "dim", enabled=enabled) if source else ""
    return f"{tag} {text} {src}".rstrip()


# How much of a diff or a code block the transcript shows before it says
# "… +N lines". Was 30 for code and 60 for a diff; the creator, 2026-09-12,
# with Claude Code beside it: the console must not be flooded with source
# -- a short, coloured excerpt and a count, the way Claude Code does it.
BLOCK_LINES = 12
BLOCK_LINE_CHARS = 160


def _more(lines: list[str], shown: int, *, enabled: bool = True) -> str:
    rest = len(lines) - shown
    return style(f"… +{rest} line{'s' if rest != 1 else ''}", "dim", enabled=enabled) if rest > 0 else ""


def _clip(line: str, limit: int = BLOCK_LINE_CHARS) -> str:
    return line if len(line) <= limit else line[: limit - 1] + "…"


def code_block(code: str, *, label: str = "", max_lines: int = BLOCK_LINES, enabled: bool = True) -> str:
    lines = code.splitlines() or [""]
    shown = [_clip(line) for line in lines[:max_lines]]
    header = style(f"--- {label} ---" if label else "---", "dim", enabled=enabled)
    parts = [header, *shown]
    more = _more(lines, len(shown), enabled=enabled)
    parts.append(more if more else style("---", "dim", enabled=enabled))
    return "\n".join(parts)


_MD_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)
_MD_HEADER_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_CODE_RE = re.compile(r"`([^`\n]+?)`")
_MD_FENCE_PLACEHOLDER = "\x00FENCE{}\x00"


def markdown(text: str, *, enabled: bool = True) -> str:
    """A deliberately small subset of Markdown -> ANSI (live-caught: a
    chat-tuned model naturally writes `**bold**`/`` `code` ``/headers/
    fenced blocks, and this REPL was printing that syntax completely
    unprocessed -- literal asterisks and backticks on screen). Not a
    CommonMark parser -- good enough for what a real reply actually
    contains, not a guarantee for arbitrary markdown input. Fenced code
    blocks are extracted and rendered via `code_block()` *before* the
    other patterns run, so a stray `**`/backtick inside a code sample is
    never touched -- then spliced back in by placeholder. The markdown
    delimiters are always stripped (`re.sub`'s replacement keeps only
    the *inner* captured text), independent of `enabled`; `enabled` only
    controls whether the result also gets real SGR styling instead of
    plain unstyled text."""
    if not text:
        return text
    blocks: list[str] = []

    def _stash_fence(match: "re.Match[str]") -> str:
        blocks.append(code_block(match.group(1).rstrip("\n"), enabled=enabled))
        return _MD_FENCE_PLACEHOLDER.format(len(blocks) - 1)

    working = _MD_FENCE_RE.sub(_stash_fence, text)
    working = _bullets(working)
    working = _MD_HEADER_RE.sub(lambda m: style(m.group(2), "bold", enabled=enabled), working)
    working = _MD_BOLD_RE.sub(lambda m: style(m.group(1), "bold", enabled=enabled), working)
    working = _MD_CODE_RE.sub(lambda m: style(m.group(1), "cyan", enabled=enabled), working)
    for i, block in enumerate(blocks):
        working = working.replace(_MD_FENCE_PLACEHOLDER.format(i), block)
    return working


def diff_block(lines: list[str], *, label: str = "", max_lines: int = BLOCK_LINES, enabled: bool = True) -> str:
    """A diff as Claude Code shows one: added lines green, removed red,
    the first `max_lines` only and then "… +N lines". The `---`/`+++`
    file header and hunk markers are dimmed, not coloured as changes."""
    out = []
    for line in lines[:max_lines]:
        line = _clip(line)
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            out.append(style(line, "dim", enabled=enabled))
        elif line.startswith("+"):
            out.append(style(line, "green", enabled=enabled))
        elif line.startswith("-"):
            out.append(style(line, "red", enabled=enabled))
        else:
            out.append(line)
    header = style(f"--- {label} ---" if label else "---", "dim", enabled=enabled)
    more = _more(lines, len(out), enabled=enabled)
    return "\n".join([header, *out, more] if more else [header, *out])


_MD_BULLET_RE = re.compile(r"^(\s*)[-*•]\s+(.*)$")
_BULLETS = ("•", "◦", "▪")


def _bullets(text: str) -> str:
    """`- item` becomes `• item`, and an indented one `◦ item` under it:
    the nested bullets a report reads best in, instead of raw dashes."""
    out = []
    for line in text.splitlines():
        match = _MD_BULLET_RE.match(line)
        if match is None or line.lstrip().startswith(("- [", "-- ")):
            out.append(line)
            continue
        depth = min(len(match.group(1).replace("\t", "  ")) // 2, len(_BULLETS) - 1)
        out.append(f"{'  ' * depth}{_BULLETS[depth]} {match.group(2)}")
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def reply_block(text: str, *, enabled: bool = True, unicode: bool = True) -> str:
    """Sim's answer the way Claude Code prints its own: a filled bullet
    on the first line, the rest indented under it, markdown rendered
    and lists as real bullets. Blank lines between paragraphs stay."""
    body = markdown(text or "", enabled=enabled)
    lead = "● " if unicode else "* "
    lines = body.splitlines() or [""]
    return "\n".join([f"{lead}{lines[0]}"] + [f"  {line}" if line else "" for line in lines[1:]])


def prompt_banner(question: str, options: list[str], *, enabled: bool = True) -> str:
    """A boxed confirmation banner for a pending `ui.prompt` -- "Explicit
    Gating" in the creator's own Claude Code reference: a visually
    distinct block for the one moment execution is genuinely waiting on
    a human decision, not another dim narration line. Pure scrolling
    text, box-drawing glyphs only -- no cursor control (module
    docstring's rule). Width/padding are computed on the *plain* text
    before `style()` wraps it in SGR codes, the same order `banner()`'s
    own `mark_plain.center(...)` uses -- an SGR code adds bytes but no
    printed columns, so padding computed after wrapping would misalign."""
    opts_plain = " / ".join(options)
    width = max(len(question), len(opts_plain), 24)
    top = "╭" + "─" * (width + 2) + "╮"
    bottom = "╰" + "─" * (width + 2) + "╯"
    q_line = "│ " + style(question.ljust(width), "bold", enabled=enabled) + " │"
    o_line = "│ " + style(opts_plain.ljust(width), "cyan", enabled=enabled) + " │"
    return "\n".join([top, q_line, o_line, bottom])


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


# The width the splash art was drawn for. Everything that renders text
# beside it asks `terminal_width()` instead: at 70 columns eight of
# twelve splash lines overran, and every task row was 119 columns and
# wrapped mid-column, destroying the table on the first screen a user
# sees (observer, 2026-09-08). My earlier width pass covered the feed
# and the panel and missed this file entirely.
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


def splash(*, enabled: bool = True, width: int = _RULE_WIDTH) -> list[str]:
    """The official logo (images/logo/Sim-Logo-transparent.png) as terminal art: one
    string per row of half-block cells generated by
    tools/render_logo_splash.py into `splash_art.py`. Each cell is `▀`
    with foreground = top pixel and background = bottom pixel (24-bit
    SGR); a transparent half uses `▀`/`▄` with only one color, and a
    fully transparent cell is a space. With color disabled the shape is
    drawn in plain block glyphs, so the silhouette still reads. A second
    splash -- one of five Unicode cartoons, picked at random -- follows
    the logo rows, so every startup shows the logo then a cartoon."""
    import os

    from . import splash_art

    rows: list[str] = []
    pad = " " * max(0, (width - splash_art.WIDTH) // 2)
    for row in splash_art.ROWS:
        cells = []
        for top, bot in row:
            if top is None and bot is None:
                cells.append(" ")
            elif not enabled:
                cells.append("█" if top and bot else ("▀" if top else "▄"))
            elif top is not None and bot is not None:
                cells.append(f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m\x1b[48;2;{bot[0]};{bot[1]};{bot[2]}m▀{_RESET}")
            elif top is not None:
                cells.append(f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m▀{_RESET}")
            else:
                cells.append(f"\x1b[38;2;{bot[0]};{bot[1]};{bot[2]}m▄{_RESET}")
        rows.append(pad + "".join(cells).rstrip())
    # One of five Unicode cartoons, picked at random, follows the logo
    # rows. Cleanly removable: set SIMORGH_CARTOON_SPLASH=0 (or delete
    # appended cartoon section of splash_art.py) to uninstall it.
    if os.environ.get("SIMORGH_CARTOON_SPLASH", "1") not in ("0", "false", "off"):   # colour or not
        name, art = splash_art.pick()
        cwidth = max(len(line) for line in art)
        cpad = " " * max(0, (width - cwidth) // 2)
        rows.append("")
        rows.extend(cpad + line for line in art)
        rows.append(cpad + f"~ {name} ~")
    return rows


def logo_rows(*, enabled: bool = True, width: int = _RULE_WIDTH) -> list[str]:
    """The logo alone, no cartoon -- for a caller that wants the emblem."""
    rows = splash(enabled=enabled, width=width)
    from . import splash_art

    return rows[:len(splash_art.ROWS)]


#: Derived from `parser.COMMANDS` -- see the note there. The splash
#: shows the head of the table, not all of it: twenty rows on the first
#: screen someone sees is a wall, and `help` is one word away.
_QUICK_COMMANDS: tuple[tuple[str, str], ...] = _command_help(limit=_SPLASH_COMMANDS)


#: Domain status glyphs. Three states, not two: "nothing set up yet" and
#: "set up and not answering" are different facts, and showing them the
#: same way makes a fresh install look like a system on fire.
_DOMAIN_GLYPHS = {
    "ready": ("\u25cf", "green", "[+]"),
    "todo": ("\u25cb", "dim", "[ ]"),
    "broken": ("\u2715", "red", "[x]"),
}

_DOMAIN_SECTIONS = (
    ("broken", "not working"),
    ("ready", "ready"),
    ("todo", "to set up"),
)


def domains_panel(rows: list[dict], *, width: int | None = None, enabled: bool = True,
                  unicode: str = "auto") -> str:
    """`domains`, laid out.

    Grouped by state rather than listed flat, because on a fresh install
    five of six rows say the same thing and the one that does not is
    what the person is looking for. Anything broken comes first: it is
    the only group that needs acting on today.

    `row`: `{name, blurb, state, detail, fix}`.
    """
    width = width or terminal_width()
    glyphs = unicode_mode(unicode) != "off"
    label_width = max((display_width(row["name"]) for row in rows), default=8)
    label_width = max(label_width, 8)
    # Where the blurb starts, so a wrapped detail line sits under it
    # rather than under the glyph. Derived from the glyph's real width
    # because the ASCII fallback is three columns wide and the unicode
    # one is a single column.
    mark_width = 1 if glyphs else 3
    indent = 2 + mark_width + 2 + label_width + 2

    counts = {state: sum(1 for row in rows if row["state"] == state)
              for state, _ in _DOMAIN_SECTIONS}
    summary = " \u00b7 ".join(
        f"{counts[state]} {title}" for state, title in _DOMAIN_SECTIONS if counts[state])
    out = [style(f"domains  {summary}", "dim", enabled=enabled)]

    for state, title in _DOMAIN_SECTIONS:
        group = [row for row in rows if row["state"] == state]
        if not group:
            continue
        glyph, colour, ascii_glyph = _DOMAIN_GLYPHS[state]
        mark = glyph if glyphs else ascii_glyph
        out.append("")
        out.append(style(f"  {title}", "dim", enabled=enabled))
        for row in group:
            name = row["name"].ljust(label_width)
            out.append(f"  {style(mark, colour, enabled=enabled)}  "
                       f"{style(name, 'bold', enabled=enabled)}  {row.get('blurb', '')}".rstrip())
            # A domain that is simply not set up yet does not need its
            # status spelled out -- "no documents indexed yet" under a
            # heading that already says "to set up" is the same sentence
            # twice. What it needs is the one thing to do.
            detail = str(row.get("detail") or "").strip()
            if detail and state != "todo":
                out.extend(_domain_wrap(detail, indent, width))
            fix = str(row.get("fix") or "").strip()
            if fix:
                arrow = "\u2192" if glyphs else "->"
                out.extend(_domain_wrap(f"{arrow} {fix}", indent, width,
                                        colour="cyan", enabled=enabled))
    return "\n".join(out)


def _domain_wrap(text: str, indent: int, width: int, *, colour: str = "",
                 enabled: bool = True) -> list[str]:
    """Wrap to the real terminal width, hanging-indented under the name.

    `textwrap` is given BOTH indents rather than being handed a bare
    width with the indent added afterwards -- doing it the second way
    left the two-space hanging indent outside the budget, so every
    continuation line was two columns too long. Sized from
    `terminal_width()` rather than a constant: the reason the first
    version of this ran off the screen is that its longest line was
    written for whatever window it happened to be tested in.
    """
    import textwrap

    lead = " " * indent
    room = max(24, width)
    lines = textwrap.wrap(text, width=room, initial_indent=lead,
                          subsequent_indent=lead + "  ") or [lead]
    if not colour:
        return lines
    return [style(line, colour, enabled=enabled) for line in lines]


# -- status panel -----------------------------------------------------------
#
# The first version printed one line per subsystem, an ASCII bar, and
# then every registered tool name in one comma-run. On this machine that
# is sixteen near-identical "ok" lines burying the one that said
# "degraded", followed by fifty names nobody reads. A status panel is
# read at a glance or not at all.

#: Health glyphs. A filled ring for well, a half ring for degraded, a
#: cross for down -- distinguishable by SHAPE, so the panel still works
#: with no colour and for anyone who cannot tell green from amber.
_HEALTH = {"ok": ("\u25cf", "green", "o"), "degraded": ("\u25d0", "yellow", "~"),
           "down": ("\u2715", "red", "x")}

_BAR_FULL, _BAR_EMPTY = "\u2588", "\u2591"


def meter(value: float, *, width: int = 10, lo: float = -1.0, hi: float = 1.0,
          unicode: bool = True) -> str:
    """A proportion, as a bar. Solid blocks rather than `#` and `-`:
    at a glance the eye reads a filled length, and hashes read as text
    to be parsed."""
    span = (hi - lo) or 1.0
    frac = max(0.0, min(1.0, (value - lo) / span))
    filled = round(frac * width)
    # Anything above the floor gets at least one block. 27 calls out of
    # 1500 rounds to nothing, and an empty bar beside a non-zero number
    # reads as a broken bar rather than as a small one.
    if filled == 0 and value > lo:
        filled = 1
    if not unicode:
        return "#" * filled + "-" * (width - filled)
    return _BAR_FULL * filled + _BAR_EMPTY * (width - filled)


def _duration(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


def status_panel(*, health: dict | None, snapshot, posture: dict | None,
                 tools: list | None, git: dict | None, width: int | None = None,
                 enabled: bool = True, unicode: str = "auto") -> str:
    """Everything `status` knows, on one screen.

    Takes the raw payloads rather than pre-rendered strings, because the
    layout decisions -- which subsystems to name, what to put in the
    second column, how much of a commit subject fits -- can only be made
    with the numbers in hand. Each piece is optional and its absence is
    said plainly: a panel that silently omits the part that failed is
    worse than one that admits it.
    """
    width = width or terminal_width()
    glyphs = unicode_mode(unicode) != "off"
    dim = lambda text: style(text, "dim", enabled=enabled)  # noqa: E731 -- one short local
    # Every non-ASCII character the panel can emit has a fallback. A
    # terminal that cannot encode one does not print a `?`; it gets a
    # plainer panel that still lines up.
    sep = " \u00b7 " if glyphs else " - "
    rule = "\u2500" if glyphs else "-"
    dots = "\u2026" if glyphs else "..."
    out: list[str] = []

    # -- header ----------------------------------------------------------
    right = ""
    if health:
        right = sep.join(x for x in (
            str(health.get("state", "")), str(health.get("mode", "")),
            f"up {_duration(health.get('uptime_seconds', 0.0))}") if x)
    title = style("simorgh", "bold", enabled=enabled)
    pad = max(1, width - display_width("simorgh") - display_width(right))
    out.append(f"{title}{' ' * pad}{dim(right)}")
    out.append(dim(rule * width))
    out.append("")

    label = 12

    def row(name: str, value: str) -> None:
        out.append(f"  {dim(name.ljust(label))}{value}")

    # -- subsystems ------------------------------------------------------
    if health is None:
        row("subsystems", dim("no answer from the Kernel"))
    else:
        subsystems = health.get("subsystems", []) or []
        counts: dict[str, int] = {}
        strip = []
        for entry in subsystems:
            status_name = str(entry.get("status", "down"))
            counts[status_name] = counts.get(status_name, 0) + 1
            glyph, colour, ascii_glyph = _HEALTH.get(status_name, _HEALTH["down"])
            strip.append(style(glyph if glyphs else ascii_glyph, colour, enabled=enabled))
        summary = sep.join(f"{n} {name}" for name, n in sorted(counts.items()))
        row("subsystems", "".join(strip) + "  " + dim(summary))
        # Only the ones that are NOT well get named. Fifteen lines saying
        # "ok" is fifteen lines hiding the one that does not.
        for entry in subsystems:
            if entry.get("status") == "ok":
                continue
            glyph, colour, ascii_glyph = _HEALTH.get(str(entry.get("status")), _HEALTH["down"])
            detail = str(entry.get("detail") or "").strip()
            line = f"{style(glyph if glyphs else ascii_glyph, colour, enabled=enabled)} " \
                   f"{entry.get('name', '?')}"
            if detail:
                line += dim(f"  {detail}")
            out.append("  " + " " * label + fit(line, width - label - 4, ellipsis=dots))

    # -- vitals ----------------------------------------------------------
    if snapshot is not None and not getattr(snapshot, "stale", True):
        out.append("")
        for name, value, lo, hi, note in (
            ("mood", snapshot.mood, -1.0, 1.0, snapshot.mood_phrase),
            ("energy", snapshot.energy, -1.0, 1.0, ""),
            ("load", snapshot.load, 0.0, 1.0, ""),
        ):
            bar = meter(value, lo=lo, hi=hi, unicode=glyphs)
            # Mood and energy run -1..+1 and the sign is the point; load
            # runs 0..1 and a `+` in front of it is noise.
            number = f"{value:+.2f}" if lo < 0 else f" {value:.2f}"
            row(name, f"{bar}  {number}" + (dim(f"   {note}") if note else ""))

    # -- counters, two columns -------------------------------------------
    left_items: list[tuple[str, str]] = []
    right_items: list[tuple[str, str]] = []
    if posture:
        left_items.append(("guardian", f"{posture.get('mode', '?')}{sep}"
                                        f"trust {posture.get('trust_score', 0.0):.1f}"))
    if snapshot is not None and not getattr(snapshot, "stale", True):
        if snapshot.workers_total:
            left_items.append(("workers", f"{snapshot.workers_busy} of "
                                           f"{snapshot.workers_total} busy"))
        if snapshot.bus_published:
            left_items.append(("bus", f"{snapshot.bus_published} sent{sep}"
                                       f"{snapshot.bus_delivered} delivered"))
        right_items.append(("memory", f"{snapshot.memory_records} records"))
        right_items.append(("backlog", f"{snapshot.backlog} tasks"))
        right_items.append(("interests", str(snapshot.interests)))
    if tools is not None:
        # A count and where to see them, not fifty names. The list was
        # the longest thing on the screen and the least read.
        right_items.append(("tools", f"{len(tools)} registered" + (
            dim(f"{sep}`tool` lists them") if tools else "")))
    if left_items or right_items:
        out.append("")
        # Measured from the longest left cell rather than guessed at
        # half the width: guessing put "1357 sent - 582 delivered" flush
        # against the word beside it, with no gap at all.
        right_label = max((len(name) for name, _ in right_items), default=0) + 1
        gutter = max((label + display_width(_strip_ansi(value)) for _, value in left_items),
                     default=0) + 3
        # Measured from the widest right-hand VALUE, not a guess. Guessing
        # 24 columns let a 33-column cell ("50 registered - `tool` lists
        # them") push the line five columns past the terminal.
        right_value = max((display_width(_strip_ansi(value)) for _, value in right_items),
                          default=0)
        two_columns = bool(right_items) and width >= 2 + gutter + right_label + right_value
        for index in range(max(len(left_items), len(right_items))):
            left = left_items[index] if index < len(left_items) else None
            right_pair = right_items[index] if index < len(right_items) else None
            if not two_columns:
                # A narrow terminal gets one column: a second column
                # that wraps is worse than no second column.
                for pair in (left, right_pair):
                    if pair:
                        out.append(f"  {dim(pair[0].ljust(label))}{pair[1]}")
                continue
            cell = f"{dim(left[0].ljust(label))}{left[1]}" if left else ""
            visible = display_width(_strip_ansi(cell))
            line = "  " + cell + (" " * max(0, gutter - visible) if right_pair else "")
            if right_pair:
                line += f"{dim(right_pair[0].ljust(right_label))}{right_pair[1]}"
            out.append(line.rstrip())

    # -- budgets ---------------------------------------------------------
    budgets = dict(getattr(snapshot, "budget", {}) or {}) if snapshot is not None else {}
    if budgets:
        out.append("")
        name_width = max(len(name) for name in budgets)
        first = True
        for name, entry in sorted(budgets.items(),
                                   key=lambda kv: -(kv[1].get("calls") or 0)):
            calls = entry.get("calls", 0)
            cap = entry.get("max_calls")
            bar = meter(calls / cap if cap else 0.0, lo=0.0, hi=1.0, unicode=glyphs)
            used = f"{calls}/{cap}" if cap is not None else str(calls)
            flag = style("  exhausted", "red", enabled=enabled) if entry.get("exhausted") else ""
            row("budgets" if first else "", f"{name.ljust(name_width)}  {bar}  {used}{flag}")
            first = False

    # -- git -------------------------------------------------------------
    if git is not None:
        out.append("")
        if not git.get("available", False):
            row("git", dim("no repository here"))
        else:
            dirty = (style(f"{git.get('changed_files', 0)} uncommitted", "yellow", enabled=enabled)
                     if git.get("dirty") else style("clean", "green", enabled=enabled))
            row("git", f"{git.get('branch', '?')} @ {str(git.get('head', ''))[:7]}  {dirty}")
            for line in (git.get("recent_commits") or [])[:3]:
                out.append("  " + " " * label
                           + dim(fit(str(line), width - label - 4, ellipsis=dots)))
    return "\n".join(out)


def _strip_ansi(text: str) -> str:
    import re as _re

    return _re.sub(r"\x1b\[[0-9;]*m", "", text)


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
    banner_width = min(_RULE_WIDTH, terminal_width())
    rule = style(rule_ch * banner_width, "dim", enabled=enabled)
    # The wordmark in the brand's own gold (docs/brand/simorgh-brand.json),
    # bold; falls back to plain text when color is off.
    mark = _rgb(style(mark_plain.center(banner_width), "bold", enabled=enabled), "gold", enabled=enabled)
    name = "Simorgh (سیمرغ)" if unicode == "full" else "Simorgh"
    epigraph = style(
        f'"si morgh": thirty birds, one {name} -- Attar\'s Conference of\n'
        "the Birds. Sixteen subsystems, one self.",
        "dim", enabled=enabled,
    )
    lines = [rule]
    if unicode != "off":
        # The official logo (images/logo/Sim-Logo-transparent.png) as half-block art --
        # block glyphs only, present in essentially every monospace font,
        # unlike the Arabic script this replaced in the centered line; the
        # pure-ASCII mode simply omits the picture. `logo()` (the compact
        # brand-SDK mark) stays available for narrow surfaces.
        lines.extend(splash(enabled=enabled))
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
    # The name column is as wide as the longest name; the description
    # gets whatever the terminal has left, and is cut if it does not
    # fit. At 70 columns eight of these ran past the edge and wrapped
    # (observer, 2026-09-08).
    # ASCII mode means ASCII everywhere, including the cut marker.
    ellipsis = "…" if unicode != "off" else "..."
    width = max(len(name) for name, _ in _QUICK_COMMANDS)
    room = max(16, banner_width - width - 5)
    for name, desc in _QUICK_COMMANDS:
        label = style(name.ljust(width), "cyan", enabled=enabled)
        lines.append(f"  {label}   {fit(desc, room, ellipsis=ellipsis)}")
    lines.append(rule)
    # Last word on width: nothing in the splash may exceed the terminal.
    # The prose lines are hand-wrapped for 68 and the art has its own
    # shape, so cut here rather than trying to reflow either.
    return "\n".join(fit(line, banner_width, ellipsis=ellipsis) for line in lines)

_STATUS_COLOR = {
    "in_progress": "cyan", "available": "yellow", "pending": "dim", "blocked": "magenta",
    "completed": "green", "failed": "red", "paused": "dim", "awaiting_human": "magenta",
}


def task_list(tasks: list[dict], projects: list[dict], *, limit: int = 20, enabled: bool = True) -> str:
    """The `tasks` command's real output.

    Live-caught (the creator, 2026-09-07): "when I run tasks command it
    only show the total number of tasks, not the tasks details". The
    reply had carried every field all along -- id, kind, status, origin,
    description -- and `dispatch.py` rendered `len(...)` of it and threw
    the rest away, so a backlog of 100 was indistinguishable from a
    backlog of 1 and there was no way to see what any of them were.

    Grouped by status with the work that is actually moving first, since
    "what is Sim doing" is the question being asked, and truncated with a
    count of what was left out rather than printing a hundred lines.
    """
    return _task_panel(tasks, projects, limit=limit, enabled=enabled)

def command_panel(topic: str, *, enabled: bool = True, unicode: bool = True) -> str:
    """`help voice`: that command's usage and every word it takes, alone
    on the screen; `help work`: one section. An unknown topic gets the
    nearest names, never the whole manual (the creator, 2026-09-13)."""
    import difflib

    from .parser import COMMANDS, SECTIONS, SUBCOMMANDS

    topic = (topic or "").strip().lstrip("/").lower().split()[0] if (topic or "").strip() else ""
    by_name = {name: (hint, desc) for name, hint, desc in COMMANDS}
    if topic in by_name:
        hint, desc = by_name[topic]
        lines = [f"{style(f'{topic} {hint}'.strip(), 'warm', enabled=enabled)}  {desc}"]
        subs = SUBCOMMANDS.get(topic, ())
        if subs:
            lines.append("")
            lines.extend(_subcommand_rows(topic, subs, enabled=enabled, unicode=unicode))
        elif hint:
            lines.append(style("  no sub-commands; the words in brackets are its arguments", "dim", enabled=enabled))
        else:
            lines.append(style("  takes nothing after it", "dim", enabled=enabled))
        return "\n".join(lines)
    for title, names in SECTIONS:
        if topic == title.split(",")[0].split()[0].lower():
            lines = [style(title, "bold", enabled=enabled)]
            lines.extend(_section_rows(names, by_name, SUBCOMMANDS, enabled=enabled, unicode=unicode))
            return "\n".join(lines)
    near = difflib.get_close_matches(topic, list(by_name), n=3, cutoff=0.5)
    hint = f"; did you mean {', '.join(f'help {n}' for n in near)}?" if near else ""
    return f"no command called {topic!r}{hint} -- `help` alone lists everything"


def _subcommand_rows(name: str, subs, *, enabled: bool, unicode: bool) -> list[str]:
    corner = "⎿" if unicode else "`-"
    width = max((len(f"{name} {sub}".strip()) for sub, _m in subs), default=0)
    return [f"    {style(corner, 'dim', enabled=enabled)} {style(f'{name} {sub}'.strip().ljust(width), 'warm', enabled=enabled)}"
            f"  {style(meaning, 'dim', enabled=enabled)}" for sub, meaning in subs]


def _section_rows(names, by_name, subcommands, *, enabled: bool, unicode: bool, full: bool = True) -> list[str]:
    usages = {name: (f"{name} {by_name[name][0]}".strip() if by_name[name][0] and name not in subcommands
                     else name) for name in names}
    column = max(len(u) for u in usages.values())
    rows: list[str] = []
    for name in names:
        _hint, desc = by_name[name]
        subs = subcommands.get(name, ())
        more = "" if full or len(subs) < 2 else style(f"  · help {name}: {len(subs)} ways", "dim", enabled=enabled)
        rows.append(f"  {style(usages[name].ljust(column), 'warm', enabled=enabled)}  {desc}{more}")
        if full:
            rows.extend(_subcommand_rows(name, subs, enabled=enabled, unicode=unicode))
    return rows


def help_panel(*, enabled: bool = True, unicode: bool = True, full: bool = False) -> str:
    """The help screen: commands in sections, one line each, and where a
    command has several ways to use it, where to read them (`help tv`).

    The full manual -- every command with all its words, as the creator
    asked for on 2026-09-12 -- is `help all`. It was the default until
    2026-09-19, when it had grown to 120 lines and the creator's screen
    was "lots of noise"."""
    from .parser import COMMANDS, SECTIONS, SUBCOMMANDS

    by_name = {name: (hint, desc) for name, hint, desc in COMMANDS}
    placed = {name for _title, names in SECTIONS for name in names}
    sections = list(SECTIONS) + ([("More", tuple(n for n in by_name if n not in placed))]
                                 if set(by_name) - placed else [])
    lines = [style(f"{len(by_name)} commands. A leading / is optional everywhere; Tab completes; "
                   f"`help <command>` shows one command's words; `help all` shows every one.", "dim", enabled=enabled)]
    for title, names in sections:
        lines.append("")
        lines.append(style(title, "bold", enabled=enabled))
        lines.extend(_section_rows(names, by_name, SUBCOMMANDS, enabled=enabled, unicode=unicode, full=full))
    lines.append("")
    lines.append(f"  {style('!<shell command>', 'warm', enabled=enabled)}  run a shell command directly")
    lines.append(f"  {style('anything else', 'warm', enabled=enabled)}      is chat")
    return "\n".join(lines)


def _cut_words(text: str, width: int) -> str:
    """`text` in at most `width` columns, cut at a word, with an ellipsis."""
    text = " ".join(str(text or "").split())
    if display_width(text) <= width:
        return text
    cut = fit(text, max(1, width - 1), ellipsis="")
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:-") + "\u2026"



# ------------------------------------------------------------------ panels
# One look for every listing command: a bold title with a dim count, then
# sections, then one aligned row per item -- a coloured mark, a bold name,
# dim columns, and a detail cut at a word to the terminal. The creator,
# 2026-09-19, of the first two: "I like this new panel style".

_MARKS = {
    "good": ("\u25cf", "+", "green"), "bad": ("\u25cb", "-", "red"),
    "warn": ("\u25d0", "~", "yellow"), "busy": ("\u25cf", "*", "cyan"),
    "idle": ("\u25cb", ".", "dim"),
}


@dataclass
class PanelRow:
    name: str
    cells: tuple[str, ...] = ()
    detail: str = ""
    mark: str | None = None        # good | bad | warn | busy | idle


@dataclass
class PanelSection:
    title: str
    rows: list[PanelRow] = field(default_factory=list)
    tone: str = "warm"
    note: str = ""


def panel(title: str, sections: list[PanelSection], *, count: str = "", footer: str = "",
          legend: tuple[tuple[str, str], ...] = (), enabled: bool = True, unicode: bool = True) -> str:
    """Render a panel. Columns are aligned across all sections; each column
    is at most 28 wide; the detail takes what is left and is cut at a word."""
    width = terminal_width() - 1
    rows = [row for section in sections for row in section.rows]
    marked = any(row.mark for row in rows)
    name_w = min(32, max((display_width(r.name) for r in rows), default=0))
    ncells = max((len(r.cells) for r in rows), default=0)
    cell_w = [min(28, max((display_width(r.cells[i]) for r in rows if len(r.cells) > i), default=0))
              for i in range(ncells)]

    def pad(text: str, w: int) -> str:
        text = _cut_words(text, w) if display_width(text) > w else text
        return text + " " * (w - display_width(text))

    def line(row: PanelRow) -> str:
        head = "  "
        if marked:
            glyph, plain, colour = _MARKS.get(row.mark or "idle", _MARKS["idle"])
            head += style(glyph if unicode else plain, colour, enabled=enabled) + " "
        head += style(pad(row.name, name_w), "bold", enabled=enabled)
        used = 2 + (2 if marked else 0) + name_w
        for i in range(ncells):
            text = row.cells[i] if i < len(row.cells) else ""
            head += "  " + style(pad(text, cell_w[i]), "dim", enabled=enabled)
            used += 2 + cell_w[i]
        if row.detail:
            room = max(10, width - used - 2)
            head += "  " + _cut_words(row.detail, room)
        return head.rstrip()

    top = style(title, "bold", enabled=enabled)
    if count:
        top += style(f" \u00b7 {count}", "dim", enabled=enabled)
    lines = [top]
    for section in sections:
        if not section.rows and not section.note:
            continue
        lines.append("")
        heading = style(section.title, section.tone, enabled=enabled) if section.title else ""
        if section.note:
            heading += ("  " if heading else "") + style(section.note, "dim", enabled=enabled)
        if heading:
            lines.append(heading)
        lines += [line(row) for row in section.rows]
    tail = []
    for mark, label in legend:
        glyph, plain, colour = _MARKS[mark]
        tail.append(style(glyph if unicode else plain, colour, enabled=enabled) + " " + style(label, "dim", enabled=enabled))
    if footer:
        tail.append(style(footer, "dim", enabled=enabled))
    if tail:
        lines += ["", "  ".join(tail)]
    return "\n".join(lines)


def capabilities_panel(latest: dict[str, dict], *, enabled: bool = True, unicode: bool = True) -> str:
    """`capabilities`: what Sim can reach, ready first."""
    def rows(good: bool) -> list[PanelRow]:
        return [PanelRow(name, (", ".join(p.get("tools") or ()),), str(p.get("detail") or ""),
                         "good" if good else "bad")
                for name, p in sorted(latest.items()) if bool(p.get("ok")) == good]

    ready = rows(True)
    return panel("Capabilities", [PanelSection("Ready", ready, "green"),
                                  PanelSection("Not available", rows(False), "red")],
                 count=f"{len(ready)} of {len(latest)} ready", enabled=enabled, unicode=unicode)


def skills_panel(cards, written, invalid, *, written_dir: str, enabled: bool = True, unicode: bool = True) -> str:
    """`skills list`: installed Agent Skills and the ones Sim wrote."""
    sections = [
        PanelSection("Installed", [PanelRow(c.name, (c.source,), c.description, "good") for c in cards]),
        PanelSection("Written by Sim", [PanelRow(n, ("by Sim",), d, "good") for n, d in written],
                     note=f"run one as skill:<name> \u00b7 {written_dir}/"),
        PanelSection(f"Ignored ({len(invalid)})" if invalid else "",
                     [PanelRow(str(b.path), (), str(b.reason), "bad") for b in invalid[:8]], "red"),
    ]
    return panel("Skills", sections, count=str(len(cards) + len(written)), enabled=enabled, unicode=unicode)



_TASK_SECTIONS = (
    ("in_progress", "Running", "busy"), ("awaiting_human", "Waiting for you", "warn"),
    ("blocked", "Blocked", "warn"), ("available", "Waiting", "idle"), ("pending", "Queued behind others", "idle"),
    ("paused", "Paused", "idle"), ("failed", "Failed", "bad"), ("completed", "Done", "good"),
)


def _task_panel(tasks: list[dict], projects: list[dict], *, limit: int = 20, enabled: bool = True,
                unicode: bool = True) -> str:
    """`tasks` as a panel: a section per status, work in flight first; each
    row the id, kind and origin, then the task's title."""
    from .activity import short_title

    if not tasks and not projects:
        return "no tasks"
    by_status: dict[str, list[dict]] = {}
    for task in tasks:
        by_status.setdefault(task.get("status", "?"), []).append(task)
    order = list(_TASK_SECTIONS) + [(s, s.replace("_", " ").capitalize(), "idle")
                                    for s in sorted(by_status) if s not in dict((k, 1) for k, _t, _m in _TASK_SECTIONS)]
    sections: list[PanelSection] = []
    shown = 0
    for status, title, mark in order:
        group = by_status.get(status) or []
        rows = []
        for task in group:
            if shown >= limit:
                break
            name = task.get("title") or short_title(task.get("description") or "", subject=task.get("subject"), limit=90)
            rows.append(PanelRow(str(task.get("task_id", "?"))[:12], (str(task.get("kind", "?")),
                                                                        str(task.get("origin", "?"))), name, mark))
            shown += 1
        if rows:
            sections.append(PanelSection(title, rows, _STATUS_COLOR.get(status, "dim"),
                                         note=f"{status} \u00b7 {len(group)}"))
    if projects:
        by_id = {t.get("task_id"): t for t in tasks}
        rows = []
        for project in projects[:limit]:
            pid = str(project.get("project_id", "?"))
            total = project.get("total", 0)
            if not total:
                status = by_id.get(pid, {}).get("status", "?")
                rows.append(PanelRow(pid[:12], (status,), "not broken down into steps yet", "idle"))
            else:
                stalled = " \u00b7 stalled" if project.get("stalled") else ""
                rows.append(PanelRow(pid[:12], (str(project.get("rollup", "?")),),
                                     f"{project.get('done', 0)}/{total} steps{stalled}",
                                     "warn" if project.get("stalled") else "busy"))
        sections.append(PanelSection("Projects", rows, note=f"{len(projects)} project(s)"))
    counts = " \u00b7 ".join(f"{len(by_status[k])} {t.lower()}" for k, t, _m in _TASK_SECTIONS if by_status.get(k))
    footer = ""
    if len(tasks) > shown:
        footer = f"... {len(tasks) - shown} more \u2014 `tasks all` to see them"
    elif len(projects) > limit:
        footer = f"... {len(projects) - limit} more projects"
    return panel("Tasks", sections, count=f"{len(tasks)} task(s)" + (f" \u00b7 {counts}" if counts else ""),
                 footer=footer, enabled=enabled, unicode=unicode)
