"""Minimal ANSI color helpers for the CLI (src/main.py) -- purely
cosmetic, never load-bearing: every caller must still work correctly if
color is stripped or disabled, since color is skipped automatically
whenever stdout isn't a real terminal (piped output, tests, a log file)
or the user has set NO_COLOR (see https://no-color.org).
"""

from __future__ import annotations

import keyword
import os
import re
import sys
import threading
import time
from typing import Callable

_ENABLED = sys.stdout.isatty() and "NO_COLOR" not in os.environ

_CODES = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    # No standard ANSI "orange" -- 256-color code 208 is the closest widely
    # supported approximation; falls back gracefully (just no color) on a
    # terminal that only supports the 8/16-color basic codes, since it
    # simply won't recognize the escape and most terminals still print the
    # rest of the text plainly in that case.
    "orange": "\033[38;5;208m",
}


def style(text: str, *names: str) -> str:
    """Wrap `text` in the named ANSI codes (e.g. style(x, "green", "bold")).
    Returns `text` unchanged when color is disabled -- callers never need
    their own isatty/NO_COLOR check.
    """
    if not _ENABLED or not names:
        return text
    prefix = "".join(_CODES[name] for name in names if name in _CODES)
    return f"{prefix}{text}{_CODES['reset']}"


# Longest-first so e.g. "async" doesn't get half-matched by a shorter
# alternative before it -- re's alternation otherwise tries alternatives
# left-to-right and stops at the first match, not the longest one.
_PY_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(sorted(keyword.kwlist, key=len, reverse=True)) + r")\b"
)
_COMMENT_RE = re.compile(r"(#.*)$")


def _highlight_python_line(line: str) -> str:
    """A light, regex-based approximation of syntax highlighting --
    keywords and trailing comments only, no real tokenizer (so it can
    mis-highlight a '#' inside a string literal, for instance). Good
    enough to make a code block visually scannable; never claimed to be
    a real Python lexer.
    """
    if not _ENABLED:
        return line
    comment_match = _COMMENT_RE.search(line)
    code_part, comment_part = (line[: comment_match.start()], line[comment_match.start() :]) if comment_match else (line, "")
    highlighted = _PY_KEYWORD_RE.sub(lambda m: style(m.group(1), "magenta", "bold"), code_part)
    return highlighted + (style(comment_part, "dim") if comment_part else "")


def format_code_block(
    code: str, *, label: str = "code", max_lines: int = 30, max_line_chars: int = 160
) -> str:
    """Render `code` as a bordered, (lightly) syntax-highlighted block
    for terminal display, bounded in both directions -- a huge or
    pathologically long-lined payload (e.g. a confused model dumping a
    hallucinated transcript into what should have been a one-line tool
    argument) gets truncated with a clear count of what was cut, rather
    than flooding the terminal. With color disabled, this still reads
    fine as a plain bordered block -- the border/truncation notice is
    the substance, highlighting is a bonus.
    """
    lines = (code or "").splitlines() or [""]
    shown = lines[:max_lines]
    cut_line_count = len(lines) - len(shown)

    rendered = []
    for line in shown:
        cut_chars = len(line) - max_line_chars
        if cut_chars > 0:
            line = line[:max_line_chars] + style(f"…(+{cut_chars})", "dim")
        rendered.append(f"{style('│', 'dim')} {_highlight_python_line(line)}")

    header = style(f"┌─ {label} ", "dim", "bold") + style("─" * max(3, 50 - len(label)), "dim")
    footer_notice = (
        [style(f"│ … {cut_line_count} more line(s) truncated", "dim")] if cut_line_count > 0 else []
    )
    footer = style("└" + "─" * 52, "dim")
    return "\n".join([header, *rendered, *footer_notice, footer])


def format_diff_block(diff_lines: list[str], *, label: str = "diff", max_lines: int = 60) -> str:
    """Render a unified diff (e.g. from `difflib.unified_diff`) as a
    bordered, colored block -- `+`/`-` lines in green/red, `@@` hunk
    headers cyan, the `---`/`+++` file headers bold, everything else
    left plain. Bounded like `format_code_block` (a full-file rewrite's
    diff can still be huge) with the same truncation notice; empty input
    renders as an explicit "(no changes)" line rather than an empty
    block that could read as a rendering bug.
    """
    lines = list(diff_lines) or ["(no changes)"]
    shown = lines[:max_lines]
    cut_line_count = len(lines) - len(shown)

    rendered = []
    for raw in shown:
        line = raw.rstrip("\n")
        if line.startswith("+++") or line.startswith("---"):
            colored = style(line, "bold")
        elif line.startswith("@@"):
            colored = style(line, "cyan", "bold")
        elif line.startswith("+"):
            colored = style(line, "green")
        elif line.startswith("-"):
            colored = style(line, "red")
        else:
            colored = line
        rendered.append(f"{style('│', 'dim')} {colored}")

    header = style(f"┌─ {label} ", "dim", "bold") + style("─" * max(3, 50 - len(label)), "dim")
    footer_notice = (
        [style(f"│ … {cut_line_count} more line(s) truncated", "dim")] if cut_line_count > 0 else []
    )
    footer = style("└" + "─" * 52, "dim")
    return "\n".join([header, *rendered, *footer_notice, footer])


_CHECKLIST_ICONS = {
    "pending": "○",
    "in_progress": "◐",
    "done": "✅",
    "failed": "❌",
}
_CHECKLIST_COLORS = {
    "pending": "dim",
    "in_progress": "cyan",
    "done": "green",
    "failed": "red",
}


def render_checklist(items: list[tuple[str, str]], title: str = "") -> str:
    """A compact, icon-prefixed checklist for multi-step work (`batch`,
    `evolve`) -- `items` is a list of `(label, status)` pairs, `status`
    one of "pending"/"in_progress"/"done"/"failed". Reprinted as a whole
    block after each step changes (not redrawn in place -- same
    reasoning as `LiveTicker`: a cursor/carriage-return-based redraw is
    fragile across terminals, piped output, and non-TTY logging), so a
    multi-item run has a visible, persistent "what's left" view between
    the individual step's own drafting/audit/test narration, instead of
    only a scrolling trail with no summary until the very end.
    """
    lines = [style(title, "magenta", "bold")] if title else []
    for label, status in items:
        icon = _CHECKLIST_ICONS.get(status, "?")
        color = _CHECKLIST_COLORS.get(status, "dim")
        lines.append(f"  {style(icon, color)} {label}")
    return "\n".join(lines)


DEFAULT_TICK_INTERVAL_SECONDS = 5.0


class LiveTicker:
    """A periodic "still working... (Ns elapsed)" status line for a
    long-running blocking call that would otherwise sit completely
    silent -- run_isolated_test_suite (copies the repo, runs the entire
    test suite twice) is the direct motivating case: previously just two
    static print()s around a subprocess call that can genuinely take a
    while, with zero feedback in between. This is Claude Code's
    "ongoing status" idea (the creator's own phrase), adapted to a
    plain-text, no-TUI-library CLI: not a true in-place spinner (a
    carriage-return redraw is fragile across terminals, and this project
    already has a working, safer precedent to reuse instead) -- a new
    line every `interval` seconds, printed by a daemon thread while the
    caller's own code stays blocked on the slow call. Safe for exactly
    the same reason reminders/the autonomous loop are: the thread only
    ever prints between the caller's own output, never concurrently with
    it, as long as the wrapped block doesn't itself print (true here --
    the wrapped call is a blocking subprocess.run with nothing printed
    until it returns).

    Usage:
        with LiveTicker("running the isolated test suite"):
            slow_call()
    """

    def __init__(
        self,
        message: str,
        interval: float = DEFAULT_TICK_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._message = message
        self._interval = interval
        self._clock = clock
        self._start = 0.0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "LiveTicker":
        self._start = self._clock()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._tick, daemon=True)
        self._thread.start()
        return self

    def _tick(self) -> None:
        while not self._stop_event.wait(self._interval):
            elapsed = self._clock() - self._start
            print(style(f"   ⏳ {self._message}... ({elapsed:.0f}s elapsed)", "dim"))

    def __exit__(self, exc_type, exc, tb) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1.0)


_BAR_FILLED = "█"
_BAR_EMPTY = "░"


def render_bar(fraction: float, width: int = 20, color: str = "cyan") -> str:
    """A single `[width]`-wide bar meter for a value already normalized to
    [0.0, 1.0] -- the caller maps whatever real range a stat lives in
    (e.g. EmotionalState.valence's [-1, 1]) onto that first, so this
    stays a dumb, reusable renderer rather than knowing about any one
    stat's own scale.
    """
    clamped = max(0.0, min(1.0, fraction))
    filled = round(clamped * width)
    bar = _BAR_FILLED * filled + _BAR_EMPTY * (width - filled)
    return style(bar, color)


def render_vitals(mood_phrase: str, bars: list[tuple[str, float]], stats: list[tuple[str, str]]) -> str:
    """The 'vitals' panel: a few labeled bar meters (already-normalized
    [0.0, 1.0] fractions, e.g. mood/energy/focus-load) plus a few plain
    label/value stat lines (memory size, skills applied, interests
    tracked, task backlog) -- direct answer to the creator's ask for
    "a window or box... that shows its mood in form of a couple of bar
    meters... and any other thing I can measure." `mood_phrase` is the
    same natural-language rendering `_mood_phrase()` already produces
    for conversation (never the raw numbers alone) so this panel reads
    the same "voice" as everything else, not a diagnostics dump.
    """
    label_width = max((len(label) for label, _ in bars), default=0)
    lines = [style("🩺 vitals", "magenta", "bold") + style(f" -- feeling {mood_phrase}", "dim")]
    for label, fraction in bars:
        pct = round(max(0.0, min(1.0, fraction)) * 100)
        lines.append(f"  {label.ljust(label_width)}  {render_bar(fraction)}  {pct:>3}%")
    if stats:
        stat_width = max(len(label) for label, _ in stats)
        for label, value in stats:
            lines.append(f"  {label.ljust(stat_width)}  {style(value, 'bold')}")
    return "\n".join(lines)


DEFAULT_VITALS_INTERVAL_SECONDS = 15.0
DEFAULT_PINNED_INTERVAL_SECONDS = 2.0

_SAVE_CURSOR = "\x1b7"
_RESTORE_CURSOR = "\x1b8"
_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"
_CLEAR_LINE = "\x1b[2K"


def _terminal_size() -> tuple[int, int] | None:
    """(columns, rows) of the real controlling terminal, or `None` if
    stdout isn't one (piped, non-interactive, CI, the test suite) --
    callers must treat `None` as "pinning isn't possible here" and never
    fall back to a guessed size, the same discipline `style()`'s own
    `_ENABLED` check already applies to color.
    """
    if not sys.stdout.isatty():
        return None
    try:
        size = os.get_terminal_size(sys.stdout.fileno())
    except OSError:
        return None
    return size.columns, size.lines


def _set_scroll_region(top: int, bottom: int) -> None:
    """DECSTBM: confines normal scrolling to rows `top..bottom`
    (1-indexed, inclusive) -- rows above `top` become a reserved area
    ordinary output never touches or scrolls. `reset_scroll_region()`
    (no args) restores the whole terminal.
    """
    sys.stdout.write(f"\x1b[{top};{bottom}r")


def _reset_scroll_region() -> None:
    sys.stdout.write("\x1b[r")


class VitalsMonitor:
    """The vitals panel's toggleable display modes -- one on-demand
    snapshot (`_print_vitals`/`vitals`, elsewhere), plus two live modes
    this class owns: 'vitals on' (safe, scrolling) and 'vitals pin'
    (a real fixed on-screen region, at the creator's explicit request
    after being told the tradeoff).

    'vitals on'/'off' -- the SAFE mode, on by default preference: same
    pattern this project already established for everything else that
    prints on its own (LiveTicker above, reminders.py, the autonomous
    loop): a daemon thread prints a fresh block between `input()`
    calls, never a fragile in-place cursor redraw -- this project has
    deliberately avoided true in-place TUI redraws throughout (see
    LiveTicker's own docstring) since they're fragile across terminals,
    piped output, and non-TTY logging. Only actually prints while
    `enabled` and `is_idle()` both say so, so a "live" panel never
    interrupts someone actively typing -- the exact same idle-gating
    idea `AutonomyController` already uses.

    'vitals pin'/'unpin' -- the genuinely riskier mode, built only
    after the creator was told the tradeoff and chose it anyway: a real
    reserved region at the top of the screen (`DECSTBM`, the same
    scroll-region technique `tmux`'s status bar and similar tools use),
    redrawn in place via save/restore-cursor -- the panel stays visibly
    present at all times instead of scrolling away, unlike 'vitals on'.
    Gated hard behind `_terminal_size()` returning a real size (never
    engages when stdout isn't a genuine TTY -- piped output, CI, the
    test suite all silently keep the safe scrolling mode instead, same
    as `console_style.style()`'s own color gating). Redraws are still
    idle-gated even while pinned -- the panel's PRESENCE never depends
    on idle time once pinned, but its CONTENT only refreshes when
    `readline` is unlikely to be mid-redraw of the input line itself,
    since both write to the same underlying terminal file descriptor
    and a genuinely concurrent write from each side could interleave.
    `unpin()`/`stop()` always restore the terminal's normal scroll
    region -- this must never be skipped, or the user's terminal stays
    visibly broken (scrolling confined to a partial screen) after Sim
    exits, including on Ctrl-C or a crash.

    Started once at CLI startup and left running for the process's
    whole life, exactly like `AutonomyController` -- `enabled`/`pinned`
    are plain toggles checked every tick, not things that start/stop
    the underlying thread, so there's no restart-race to get wrong.
    """

    def __init__(
        self,
        render: Callable[[], str],
        is_idle: Callable[[], bool],
        interval: float = DEFAULT_VITALS_INTERVAL_SECONDS,
        pinned_interval: float = DEFAULT_PINNED_INTERVAL_SECONDS,
    ) -> None:
        self._render = render
        self._is_idle = is_idle
        self._interval = interval
        self._pinned_interval = pinned_interval
        self.enabled = False
        self._pinned = False
        self._panel_height = 0
        self._pin_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def pinned(self) -> bool:
        return self._pinned

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="simorgh-vitals")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.unpin()

    def pin(self) -> bool:
        """Switches to the fixed on-screen panel. Returns False (and
        changes nothing) if stdout isn't a real terminal -- pinning is
        simply impossible there, not something to fake.

        Sets the scroll region exactly ONCE here, deliberately not on
        every later redraw: DECSTBM (`_set_scroll_region`) resets the
        cursor to the top of the new region as a side effect on most
        terminals, and reissuing it on every redraw would fight
        wherever ordinary conversation output had actually left the
        cursor, on every single tick. A later terminal resize isn't
        auto-detected because of this -- `vitals unpin` then `vitals
        pin` again re-measures and re-fits cleanly, deliberately kept
        manual rather than adding back the every-redraw reset this is
        avoiding.
        """
        size = _terminal_size()
        if size is None:
            return False
        _, rows = size
        panel_lines = self._render().split("\n")
        # Never reserve the WHOLE screen -- always leave real room for
        # the actual conversation, or a giant panel on a tiny terminal
        # would leave nothing for `input()` to even draw into.
        height = min(len(panel_lines), max(1, rows - 3))
        with self._pin_lock:
            self._panel_height = height
            self._pinned = True
            _set_scroll_region(height + 1, max(height + 1, rows))
            self._draw_pinned_locked(panel_lines[:height])
        return True

    def unpin(self) -> None:
        with self._pin_lock:
            if not self._pinned:
                return
            self._pinned = False
            _reset_scroll_region()
            sys.stdout.flush()

    def _draw_pinned_locked(self, panel_lines: list[str]) -> None:
        """Caller must hold `_pin_lock`. Draws `panel_lines` into the
        already-reserved top rows via save/restore-cursor -- never a
        bare cursor move with nothing to restore it, which would leave
        the terminal's cursor stranded in the reserved area. Never
        touches the scroll region itself -- see `pin()`'s own docstring
        for why that's set up exactly once, not on every redraw.
        """
        out = [_SAVE_CURSOR, _HIDE_CURSOR]
        for i, line in enumerate(panel_lines):
            out.append(f"\x1b[{i + 1};1H{_CLEAR_LINE}{line}")
        out.append(_SHOW_CURSOR)
        out.append(_RESTORE_CURSOR)
        sys.stdout.write("".join(out))
        sys.stdout.flush()

    def _loop(self) -> None:
        while True:
            interval = self._pinned_interval if self._pinned else self._interval
            if self._stop.wait(interval):
                return
            if not self._is_idle():
                continue
            with self._pin_lock:
                pinned = self._pinned
            if pinned:
                if _terminal_size() is None:
                    # The terminal disappeared out from under a pinned
                    # session (e.g. genuinely detached) -- nothing safe
                    # left to draw into; stop trying rather than error.
                    self.unpin()
                    continue
                panel_lines = self._render().split("\n")[: self._panel_height]
                with self._pin_lock:
                    if self._pinned:  # re-check: unpin() may have raced in
                        self._draw_pinned_locked(panel_lines)
            elif self.enabled:
                print("\n" + self._render())
                print(style("> ", "cyan", "bold"), end="", flush=True)
