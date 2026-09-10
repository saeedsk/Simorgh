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
import re
import shutil
import sys

from .vitals import VitalsSnapshot

_RESET = "\x1b[0m"
_COLORS = {
    "dim": "\x1b[2m", "red": "\x1b[31m", "green": "\x1b[32m", "yellow": "\x1b[33m",
    "blue": "\x1b[34m", "magenta": "\x1b[35m", "cyan": "\x1b[36m", "bold": "\x1b[1m",
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
        blocks.append(code_block(match.group(1).rstrip("\n")))
        return _MD_FENCE_PLACEHOLDER.format(len(blocks) - 1)

    working = _MD_FENCE_RE.sub(_stash_fence, text)
    working = _MD_HEADER_RE.sub(lambda m: style(m.group(2), "bold", enabled=enabled), working)
    working = _MD_BOLD_RE.sub(lambda m: style(m.group(1), "bold", enabled=enabled), working)
    working = _MD_CODE_RE.sub(lambda m: style(m.group(1), "cyan", enabled=enabled), working)
    for i, block in enumerate(blocks):
        working = working.replace(_MD_FENCE_PLACEHOLDER.format(i), block)
    return working


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
    """The official logo (images/logo/Logo-5.png) as terminal art: one
    string per row of half-block cells generated by
    tools/render_logo_splash.py into `splash_art.py`. Each cell is `▀`
    with foreground = top pixel and background = bottom pixel (24-bit
    SGR); a transparent half uses `▀`/`▄` with only one color, and a
    fully transparent cell is a space. With color disabled the shape is
    drawn in plain block glyphs, so the silhouette still reads."""
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
    return rows


_QUICK_COMMANDS: tuple[tuple[str, str], ...] = (
    ("status", "health, vitals, posture, and tools in one panel"),
    ("improve <path> <description>", "revise existing code, tested before it lands"),
    ("... steps=N", "a bigger step cap for a big task"),
    ("improve <topic>", "draft a new skill, audited before it lands"),
    ("tasks / tasks work", "see the backlog, advance the next item"),
    ("cancel <task_id>", "stop a running task"),
    ("research <topic>", "investigate a question, no code written"),
    ("benchmark", "score this system on GAIA or BFCL, and track it"),
    ("plan <goal>", "break a goal into tracked steps"),
    ("auto [on|off|now]", "control the idle self-improvement loop"),
    ("mcp", "review external tools Sim has proposed"),
    ("capabilities", "what Sim can actually reach: Node, Docker, optional packages"),
    ("tool [name] [args]", "list every tool, or run one -- Guardian gates it as usual"),
    ("domains", "documents, mail, the house, energy, media, security: on? reachable?"),
    ("config [section]", "the settings actually in force, and any nothing reads"),
    ("alerts", "what the monitors have raised, and what is waiting for the digest"),
    ("schedule [every] <15m> <label>", "fire a reminder later, or on a repeat"),
    ("pause / resume", "hold everything, or let it continue"),
    ("exit", "leave (Ctrl-D also detaches)"),
)


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
        # The official logo (images/logo/Logo-5.png) as half-block art --
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
    if not tasks and not projects:
        return "no tasks"

    order = ["in_progress", "available", "blocked", "awaiting_human", "pending", "paused", "failed", "completed"]
    by_status: dict[str, list[dict]] = {}
    for task in tasks:
        by_status.setdefault(task.get("status", "?"), []).append(task)

    lines: list[str] = []
    summary = "  ".join(
        style(f"{len(by_status[s])} {s}", _STATUS_COLOR.get(s, "dim"), enabled=enabled)
        for s in order if by_status.get(s)
    )
    extra = [s for s in by_status if s not in order]
    if extra:
        summary += "  " + "  ".join(f"{len(by_status[s])} {s}" for s in sorted(extra))
    lines.append(f"{len(tasks)} task(s): {summary}" if summary else f"{len(tasks)} task(s)")

    shown = 0
    for status in order + sorted(extra):
        group = by_status.get(status)
        if not group:
            continue
        for task in group:
            if shown >= limit:
                break
            lines.append("  " + _task_line(task, enabled=enabled))
            shown += 1
        if shown >= limit:
            break
    if len(tasks) > shown:
        lines.append(style(f"  ... {len(tasks) - shown} more (`tasks all` to see them)", "dim", enabled=enabled))

    if projects:
        by_id = {t.get("task_id"): t for t in tasks}
        lines.append("")
        lines.append(f"{len(projects)} project(s):")
        for project in projects[:limit]:
            lines.append("  " + _project_line(project, by_id, enabled=enabled))
        if len(projects) > limit:
            lines.append(style(f"  ... {len(projects) - limit} more", "dim", enabled=enabled))
    return "\n".join(lines)


def _project_line(project: dict, by_id: dict, *, enabled: bool = True) -> str:
    """One project row.

    Live-caught (the creator, 2026-09-07): every project read `pending
    0/0 steps` while the same ids appeared as `claimed` in the task list
    directly above -- two different answers about one task on one screen.
    The rollup is computed from a project's children, so with no children
    it reports `pending` regardless of what the project itself is doing.
    A project with no steps says so, in its own real status.
    """
    project_id = project.get("project_id", "?")
    task = by_id.get(project_id, {})
    total = project.get("total", 0)
    if not total:
        status = task.get("status", "?")
        return (
            f"{project_id[:12]:12s}  "
            f"{style(f'{status:<12s}', _STATUS_COLOR.get(status, 'dim'), enabled=enabled)}  "
            + style("not broken down into steps yet", "dim", enabled=enabled)
        )
    rollup = project.get("rollup", "?")
    stalled = "  stalled" if project.get("stalled") else ""
    return (
        f"{project_id[:12]:12s}  "
        f"{style(f'{rollup:<12s}', _STATUS_COLOR.get(rollup, 'dim'), enabled=enabled)}  "
        f"{project.get('done', 0)}/{total} steps{stalled}"
    )


def _task_line(task: dict, *, enabled: bool = True) -> str:
    status = task.get("status", "?")
    origin = task.get("origin", "?")
    description = (task.get("description") or "").replace("\n", " ").strip()
    subject = task.get("subject") or ""
    if subject and subject not in description:
        description = f"{subject}: {description}"
    # Measure the prefix rather than guessing its width -- guessing is
    # exactly how this line came to be 87 columns on an 80-column
    # terminal (observer, 2026-09-08).
    prefix = (
        f"{task.get('task_id', '?')[:12]:12s}  "
        f"{status:<12s}  {task.get('kind', '?'):<8s}  {origin:<9s}  "
    )
    description = fit(description, max(20, terminal_width() - display_width(prefix) - 2))
    return (
        f"{task.get('task_id', '?')[:12]:12s}  "
        f"{style(f'{status:<12s}', _STATUS_COLOR.get(status, 'dim'), enabled=enabled)}  "
        f"{task.get('kind', '?'):<8s}  "
        f"{style(f'{origin:<9s}', 'dim', enabled=enabled)}  {description}"
    )

