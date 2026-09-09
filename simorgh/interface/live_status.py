"""A live, redraw-in-place status line beneath the REPL's scrolling
output (the creator's explicit call, 2026-09-06, after being shown the
tradeoff plainly: a real Claude-Code-style footer, not just richer
scrolling text).

`render.py`'s own hard rule (milestone 94, restated in
`docs/blueprint/subsystems/15-interface.md` section 7) stays exactly
true: "the only escape sequences `render.py` ever emits are SGR color
codes." This module is the one place in this package that owns real
cursor-movement/erase/hide-cursor escape sequences, and it only ever
writes them when `sys.stdout.isatty()` -- a redirected file, a pipe, or
a headless/detached run sees the identical plain scrolling text as
before, with zero of the sequences below. `enabled=False` (the no-TTY
path) makes every method here a no-op by construction, not by a
separate code path someone could let drift out of sync.

The footer is deliberately one physical line: multi-line in-place
redraw needs cursor-up-by-N plus per-line erase, and N only stays
correct if nothing else ever prints without going through this same
class first -- a much larger invariant to hold across a REPL with many
independent `print()` call sites. `interface/service.py`'s own `_out()`
is the one gate: every scrolling line clears the footer first and
restores it after, so the footer and real output never interleave
mid-line.
"""

from __future__ import annotations

import shutil
import sys

_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"
_CLEAR_LINE = "\x1b[2K"
_TO_COL0 = "\r"

# "Breathing verbs" (the creator's own term, from the Claude Code
# reference they sent): a phase+tool pair maps to a present-tense verb
# instead of one static "thinking" for the whole turn. Sourced from the
# real `task.step` `phase`/`tool` fields already flowing through
# `_on_task_event` -- not invented state, the same data the old dim
# narration line already had.
_VERBS: dict[tuple[str, str | None], str] = {
    ("gather", None): "Thinking",
    ("act", "read_file"): "Reading",
    ("act", "list_dir"): "Listing",
    ("act", "self_map"): "Checking",
    ("act", "web_fetch"): "Fetching",
    ("act", "render_page"): "Rendering",
    ("act", "search_listings"): "Searching",
    ("act", "geocode"): "Geocoding",
    ("act", "find_package"): "Searching",
    ("act", "install_package"): "Installing",
    ("act", "run_script"): "Running",
    ("act", "grant_capability"): "Granting",
    ("act", "revoke_capability"): "Revoking",
    ("act", "run_python_sandboxed"): "Running",
    ("act", "run_js_sandboxed"): "Running",
    ("act", "run_tests"): "Testing",
    ("act", "search_code"): "Searching",
    ("act", "apply_source_patch"): "Patching",
    ("act", "apply_skill"): "Applying",
    ("act", "run_shell"): "Running",
    ("act", "web_search"): "Searching",
    ("act", "git_commit"): "Committing",
    ("act", "git_revert"): "Reverting",
    ("act", "git_discard"): "Discarding",
    ("act", "propose_mcp_server"): "Proposing",
    ("verify", None): "Verifying",
}
_DEFAULT_VERB = "Working"


def verb_for(phase: str, tool: str | None) -> str:
    if tool and tool.startswith("mcp_"):
        return "Calling"
    return _VERBS.get((phase, tool)) or _VERBS.get((phase, None)) or _DEFAULT_VERB


def live_status_enabled(mode: str = "auto") -> bool:
    """Mirrors `render.py::color_enabled`/`unicode_mode`'s own
    resolution pattern: `off`/`on` are explicit; `auto` (the default)
    follows `sys.stdout.isatty()`, so tests (which redirect stdout to an
    `io.StringIO` -- never a tty) and any redirected/piped/headless run
    get the plain scrolling fallback without needing to know this
    feature exists, and a real interactive terminal gets the footer."""
    if mode == "off":
        return False
    if mode == "on":
        return True
    return sys.stdout.isatty()


def _terminal_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 24)).columns
    except OSError:
        return default


def clear_current_line() -> None:
    """Blanks whatever's on the terminal's current line right now.

    Distinct from `LiveStatus.clear()`, which only erases a footer
    *this class itself* drew (a no-op the rest of the time). Live-caught
    (the creator, real use, twice): a bare `input("> ")` prompt has no
    footer to protect, so a bus handler's `_out()` printing while that
    prompt sits on screen (an autonomous task's own notice, a Guardian
    denial for work the REPL didn't start) wrote straight onto the same
    line as the "> " -- garbled text mid-prompt, easy to mistake for the
    process hanging. `service.py::_out()` calls this whenever
    `_input_pending` says a real `input()` call is blocked right now,
    same no-op-off-a-real-tty guarantee as everything else here."""
    if sys.stdout.isatty():
        sys.stdout.write(_TO_COL0 + _CLEAR_LINE)
        sys.stdout.flush()


class LiveStatus:
    """One in-place-updating line. `render(text)` overwrites it;
    `clear()` erases it back to nothing (call before printing anything
    else); `start()`/`stop()` hide/restore the terminal cursor for the
    footer's own lifetime. Every method is a no-op when `enabled` is
    False (the default resolves from `sys.stdout.isatty()`, so a
    redirected/piped/headless run never touches an escape sequence)."""

    def __init__(self, *, enabled: bool | None = None) -> None:
        self._enabled = sys.stdout.isatty() if enabled is None else enabled
        self._drawn = False
        self._text = ""
        self._sink = None

    def redirect(self, sink) -> None:
        """Send this line somewhere else instead of writing escape codes.

        The prompt_toolkit prompt (`tui.py`) owns the bottom of the
        screen and draws its own toolbar, so the two cannot both write
        there -- the clear-and-restore dance this class does around every
        print exists precisely because nothing else was coordinating. A
        sink hands the same text to the prompt's footer instead, and every
        `render`/`clear` caller stays exactly as it was. `redirect(None)`
        puts it back.
        """
        self._sink = sink
        if sink is not None:
            self.clear()

    @property
    def enabled(self) -> bool:
        # True while redirected as well: the call sites guard their
        # `render` calls on this, and a redirected footer is still a
        # footer that gets drawn -- just by the prompt, not by us.
        return self._enabled or self._sink is not None

    def start(self) -> None:
        if self._enabled:
            sys.stdout.write(_HIDE_CURSOR)
            sys.stdout.flush()

    def stop(self) -> None:
        if not self._enabled:
            return
        self.clear()
        sys.stdout.write(_SHOW_CURSOR)
        sys.stdout.flush()

    def render(self, text: str) -> None:
        self._text = text
        if self._sink is not None:
            self._sink(text)
            return
        if not self._enabled:
            return
        cols = _terminal_width()
        line = text if len(text) < cols else text[: max(0, cols - 1)]
        sys.stdout.write(_TO_COL0 + _CLEAR_LINE + line)
        sys.stdout.flush()
        self._drawn = True

    def clear(self) -> None:
        if self._sink is not None:
            self._sink("")
            return
        if not self._enabled or not self._drawn:
            return
        sys.stdout.write(_TO_COL0 + _CLEAR_LINE)
        sys.stdout.flush()
        self._drawn = False

    def restore(self) -> None:
        """Re-draws the last `render()`ed text -- used after a scrolling
        `print()` to put the footer back beneath the new line, if a
        turn is still in flight."""
        if self._text:
            self.render(self._text)
