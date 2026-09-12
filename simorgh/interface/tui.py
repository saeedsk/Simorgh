"""The interactive prompt, built on `prompt_toolkit`.

The creator, 2026-09-07, asked for a Claude-Code-shaped terminal UI and
was explicit that `input()` is the wrong foundation for it. It is: the
old REPL ran `input("> ")` on a daemon thread, and every one of the
features asked for here -- a prompt pinned to the bottom while output
scrolls above it, multi-line editing, a completion menu you arrow
through, live syntax colouring, redraw on window resize -- is something
`input()` structurally cannot do. `readline` gives history and in-line
editing and stops there; the live-status footer had to be hand-rolled
around it, clearing and redrawing itself so prints would not interleave
(`live_status.py`).

What this module changes, against that blueprint:

- **Sticky footer.** `patch_stdout` reroutes every `print` in the
  process, from any thread, so background output scrolls above a prompt
  that stays at the bottom. That is also what retires the manual
  clear-and-redraw dance: nothing can interleave with the prompt any
  more, because nothing writes to the terminal behind its back.
- **One event loop, not two.** `prompt_async` runs on the same asyncio
  loop as everything else, so a line is handled where the bus already
  lives. The old thread had to bridge every line back with
  `run_coroutine_threadsafe(...).result()`, which blocked the reader
  until the turn finished -- the reason a second line typed during a slow
  turn could not even be *typed*. Here `run()` queues each line and
  hands it to a background worker instead of awaiting it inline, so the
  loop is back inside `prompt_async()` -- raw mode, buffer live -- before
  the previous turn's handler has even started running.
- **Resize** is prompt_toolkit's own SIGWINCH handling; there is nothing
  to do but stop fighting it.
- **Enter submits, Ctrl-J and Alt-Enter insert a newline.** A pasted
  multi-line block stays one submission.
- **Ctrl-C cancels, twice exits.** The first press clears a non-empty
  buffer, or asks the running task to stop if the buffer is already
  empty; a second press within `DOUBLE_INTERRUPT_S` leaves.
- **`/` completes commands, `@` completes paths**, in a menu navigated
  with the arrow keys and accepted with Tab or Enter.
- **History is persistent** across sessions in the same file the readline
  REPL used, so nobody loses their history to this change.

`prompt_toolkit` is an optional dependency (principle 4.14, and the same
shape as the Gemini provider's `google-genai`): `available()` is false
when it is not installed, and `service.py` keeps the readline REPL as the
fallback. Nothing here may be imported at module scope for that reason.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Awaitable, Callable, Iterable

from .parser import COMMANDS as _PARSER_COMMANDS

DOUBLE_INTERRUPT_S = 2.0
PROMPT_GLYPH = "❯"
_MAX_PATH_COMPLETIONS = 40

# No real command name or repo-relative path is anywhere near this long, so
# once a line crosses it -- pasted prose, a giant unbracketed paste, a stray
# long word -- it is never a completion or highlighting candidate. Bailing
# out at this length caps the per-keystroke cost of `_SimCompleter` and
# `_lex_line` at a constant instead of it scaling with line length; every
# other character insertion still re-triggers the completer and lexer
# (`complete_while_typing=True`, prompt_toolkit's own per-keystroke redraw),
# so a long line still costs O(length) total work across all its keystrokes
# -- this only removes the *extra* per-keystroke multiplier this module
# itself would otherwise add on top of that.
_MAX_LINE_FOR_COMPLETION_AND_LEXING = 4000

# What the completion menu offers after `/`. The description is the
# right-hand column, the same text `render.py` shows in the splash.
#: Derived from `parser.COMMANDS`, never maintained beside it. This was
#: its own list until 2026-09-09, when four new commands were added to
#: the parser and the help panel and not to here -- so they worked when
#: typed and did not autocomplete, which reads like they do not exist.
COMMANDS: tuple[tuple[str, str], ...] = tuple(
    (name, description) for name, _, description in _PARSER_COMMANDS)


class PromptToolkitMissing(ImportError):
    """`prompt_toolkit` is not installed. `service.py` checks
    `available()` first and falls back to the readline REPL, so this is
    only ever raised by a caller that skipped that check."""


def _pt():
    """Every `prompt_toolkit` name this module uses, imported once and
    guarded.

    One loader rather than an import inside each function: the module
    boundary checker (`tests/simorgh/test_module_boundaries.py`) requires
    a third-party import to sit under `except ImportError`, and it is
    right to -- an optional dependency that can still crash the process on
    import is not optional. Doing it in one place keeps that guard honest
    instead of repeating it five times.
    """
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.history import FileHistory, InMemoryHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.lexers import Lexer
        from prompt_toolkit.patch_stdout import patch_stdout
        from prompt_toolkit.styles import Style
    except ImportError as exc:  # pragma: no cover -- exercised by `available()`
        raise PromptToolkitMissing(str(exc)) from exc
    return {
        "PromptSession": PromptSession, "Completer": Completer, "Completion": Completion,
        "FileHistory": FileHistory, "InMemoryHistory": InMemoryHistory, "KeyBindings": KeyBindings,
        "Lexer": Lexer, "patch_stdout": patch_stdout, "Style": Style,
    }


def available() -> bool:
    """Whether `prompt_toolkit` can actually be imported."""
    try:
        _pt()
    except PromptToolkitMissing:
        return False
    return True


# --------------------------------------------------------------- completion
def _command_matches(word: str) -> list[tuple[str, str]]:
    stem = word.lstrip("/").lower()
    return [(name, desc) for name, desc in COMMANDS if name.startswith(stem)]


def path_matches(fragment: str, *, root: Path, limit: int = _MAX_PATH_COMPLETIONS) -> list[str]:
    """Repo-relative paths starting with `fragment`, directories first and
    marked with a trailing separator. Kept a plain function so the
    matching is testable without a terminal.

    Deliberately one directory level at a time rather than a recursive
    walk: `@s` on this repo would otherwise mean stat-ing the whole tree
    to answer a keystroke.
    """
    fragment = fragment.lstrip("@")
    directory, _, stem = fragment.rpartition("/")
    base = (root / directory) if directory else root
    try:
        entries = sorted(os.scandir(base), key=lambda e: (not e.is_dir(), e.name))
    except OSError:
        return []
    out: list[str] = []
    for entry in entries:
        if entry.name.startswith(".") and not stem.startswith("."):
            continue  # dotfiles only when asked for by name
        if not entry.name.startswith(stem):
            continue
        prefix = f"{directory}/" if directory else ""
        out.append(prefix + entry.name + ("/" if entry.is_dir() else ""))
        if len(out) >= limit:
            break
    return out


def _make_completer(root: Path):
    pt = _pt()

    class _SimCompleter(pt["Completer"]):
        """`/` completes commands, `@` completes paths, and a bare first
        word completes commands too -- the leading slash is optional
        everywhere else in this CLI (`parser.py`), so requiring it just to
        get help would be inconsistent."""

        def get_completions(self, document, complete_event) -> Iterable[Completion]:
            if len(document.text_before_cursor) > _MAX_LINE_FOR_COMPLETION_AND_LEXING:
                return  # a line this long is never a command or a path
            word = document.get_word_before_cursor(WORD=True)
            if word.startswith("@"):
                for path in path_matches(word, root=root):
                    yield pt["Completion"](f"@{path}", start_position=-len(word), display=path)
                return
            is_first_word = not document.text_before_cursor[: -len(word) or None].strip()
            if not (word.startswith("/") or is_first_word):
                return
            lead = "/" if word.startswith("/") else ""
            for name, desc in _command_matches(word):
                yield pt["Completion"](
                    lead + name, start_position=-len(word), display=name, display_meta=desc,
                )

    return _SimCompleter()


# ------------------------------------------------------------------ lexing
def _make_lexer():
    """Colour the line as it is typed. A hand-written lexer rather than a
    Pygments one: this grammar is "first word, maybe a path, maybe quoted
    text", which no existing language lexer describes, and a wrong
    highlight reads as a bug in the shell."""
    class _SimLexer(_pt()["Lexer"]):
        def lex_document(self, document):
            def get_line(lineno: int):
                line = document.lines[lineno]
                return _lex_line(line, first_line=lineno == 0)

            return get_line

    return _SimLexer()


def _lex_line(line: str, *, first_line: bool) -> list[tuple[str, str]]:
    """One line as (style, text) pairs. Exported for tests -- the styles
    are the contract, not the colours they resolve to."""
    if len(line) > _MAX_LINE_FOR_COMPLETION_AND_LEXING:
        return [("", line)]  # too long to be a command/path/quoted token anyway
    out: list[tuple[str, str]] = []
    known = {name for name, _ in COMMANDS}
    index = 0
    for token in _split_keeping_space(line):
        stripped = token.strip()
        if not stripped:
            out.append(("", token))
            continue
        style = ""
        first_word = index == 0 and first_line
        if first_word and (stripped.lstrip("/").lower() in known or stripped == "/"):
            # A bare "/" is the command prefix mid-typing, not a path.
            style = "class:sim.command"
        elif stripped.startswith("@"):
            style = "class:sim.path"
        elif stripped.startswith(("'", '"')):
            style = "class:sim.string"
        elif "/" in stripped and not stripped.startswith("-"):
            style = "class:sim.path"
        elif stripped.startswith("-"):
            style = "class:sim.flag"
        out.append((style, token))
        index += 1
    return out


def _split_keeping_space(line: str) -> list[str]:
    """Words and the whitespace between them, so re-joining the tokens
    reproduces the line exactly -- prompt_toolkit renders what it is
    given, and dropping a space would silently rewrite the input."""
    out: list[str] = []
    current = ""
    space = line[:1].isspace() if line else False
    for char in line:
        if char.isspace() == space:
            current += char
        else:
            out.append(current)
            current, space = char, char.isspace()
    if current:
        out.append(current)
    return out


# The breathing word's shades, dimmest to brightest (`panel.breath_shade`
# picks the index). Six steps of the prompt's own cyan, so the word
# swells and fades rather than blinking.
# Orange-brown, and only a little of it: six close shades of the same
# muted tan, so the wave reads as a shimmer, not a flash (the creator,
# 2026-09-12: "limit the span of changing color ... more neutral color
# tone changes; the color change span should be very minimum").
BREATH_COLOURS: tuple[str, ...] = ("#9a7146", "#a3784a", "#ac7f4f", "#b58654", "#be8d59", "#c7945e")
PANEL_REFRESH_S = 0.25


def _style():
    shades = {f"sim.breath.{i}": f"{colour} bold" for i, colour in enumerate(BREATH_COLOURS)}
    return _pt()["Style"].from_dict({
        "sim.command": "#00afd7 bold",
        "sim.path": "#5faf5f",
        "sim.string": "#87af87",
        "sim.flag": "#d7af5f",
        # The prompt glyph: light grey, a shade under white (the creator,
        # 2026-09-12: "❯ ... in light gray color ... a bit on darker shade
        # compared to full white").
        "sim.prompt": "#bcbcbc",
        "sim.rule": "#3a3a3a",
        "sim.footer": "#6c6c6c",
        "sim.live": "#d0d0d0",
        # prompt_toolkit reverses the toolbar's colours by default, which
        # reads as a light band across the bottom (the creator,
        # 2026-09-12: "weird light background color, I expect regular
        # black"). Plain text on the terminal's own background.
        "bottom-toolbar": "noreverse",
        "bottom-toolbar.text": "noreverse",
        "sim.status": "#8a8a8a",
        **shades,
        "completion-menu.completion": "bg:#1c1c1c #d0d0d0",
        "completion-menu.completion.current": "bg:#00afd7 #000000 bold",
        "completion-menu.meta.completion": "bg:#1c1c1c #808080",
        "completion-menu.meta.completion.current": "bg:#0087af #000000",
    })


# ------------------------------------------------------------------- prompt
class Tui:
    """Owns the prompt. `run()` reads lines until told to stop and hands
    each one to `on_line`; `footer_text` is polled for the panel under
    the prompt -- a plain string for one line, or formatted-text
    fragments (`panel.flatten`) for the multi-row activity panel, which
    the toolbar re-renders every `PANEL_REFRESH_S` so a breathing word
    breathes.
    """

    def __init__(
        self, *, on_line: Callable[[str], Awaitable[None]],
        on_interrupt: Callable[[], None] | None = None,
        footer_text: Callable[[], str] | None = None,
        live_text: Callable[[], list] | None = None,
        history_path: Path | None = None,
        root: Path | None = None,
        double_interrupt_s: float = DOUBLE_INTERRUPT_S,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_line = on_line
        self._on_interrupt = on_interrupt or (lambda: None)
        self._footer_text = footer_text or (lambda: "")
        self._live_text = live_text or (lambda: [])
        self._history_path = history_path
        self._root = root or Path.cwd()
        self._double_interrupt_s = double_interrupt_s
        self._now = now
        self._last_interrupt: float | None = None
        self._stopped = False
        self._session = None

    # -- interrupts ---------------------------------------------------------
    def interrupt(self, buffer_was_empty: bool) -> str:
        """What one Ctrl-C means, given the buffer. Returns "cleared",
        "cancelled" or "exit". Split out from the key binding so the rule
        is testable without a terminal: a first press clears typing or
        cancels the running task, and only a second press soon after
        leaves -- nobody should lose a session to a mistimed Ctrl-C.
        """
        now = self._now()
        recent = self._last_interrupt is not None and (now - self._last_interrupt) < self._double_interrupt_s
        self._last_interrupt = now
        if recent:
            return "exit"
        if not buffer_was_empty:
            return "cleared"
        return "cancelled"

    def stop(self) -> None:
        self._stopped = True
        session, self._session = self._session, None
        if session is not None:
            app = session.app
            if app.is_running:
                app.exit(exception=EOFError, style="class:exiting")

    # -- the loop -----------------------------------------------------------
    def _build_session(self):
        pt = _pt()
        bindings = pt["KeyBindings"]()

        @bindings.add("c-j")
        @bindings.add("escape", "enter")
        def _newline(event) -> None:
            event.current_buffer.insert_text("\n")

        @bindings.add("c-c")
        def _interrupt(event) -> None:
            buffer = event.current_buffer
            what = self.interrupt(buffer_was_empty=not buffer.text.strip())
            if what == "exit":
                event.app.exit(exception=EOFError, style="class:exiting")
                return
            if what == "cleared":
                buffer.reset()
                return
            self._on_interrupt()

        history = pt["FileHistory"](str(self._history_path)) if self._history_path else pt["InMemoryHistory"]()
        return pt["PromptSession"](
            message=self._message,
            history=history,
            completer=_make_completer(self._root),
            lexer=_make_lexer(),
            style=_style(),
            bottom_toolbar=self._toolbar,
            complete_while_typing=True,
            key_bindings=bindings,
            multiline=False,          # Enter submits; c-j / M-Enter insert newlines
            mouse_support=False,      # keeps terminal scrollback and copy/paste working
            # 6 until 2026-09-12: six blank lines between the prompt and
            # the ribbon, always (the creator's screenshot). 0: the
            # completion menu floats over the ribbon while it is open.
            reserve_space_for_menu=0,
            refresh_interval=PANEL_REFRESH_S,
        )

    def _message(self):
        """Above the input: the live section (`panel.live_rows` -- the
        call in flight and the breathing line, re-rendered every
        `PANEL_REFRESH_S` because the message is a callable), then a rule,
        then the prompt. The rule is what separates what is happening
        from the line being typed, the way Claude Code boxes its input."""
        cols = shutil.get_terminal_size((80, 24)).columns
        live: list = []
        try:
            for fragment in self._live_text() or []:
                live.append(fragment)
        except Exception:  # noqa: BLE001 -- a broken live row must not take the prompt down
            live = []
        if live and live[-1][1] != "\n":
            live.append(("", "\n"))
        return live + [("class:sim.rule", "─" * max(10, cols - 1) + "\n"), ("class:sim.prompt", f"{PROMPT_GLYPH} ")]

    def _toolbar(self):
        """The activity panel under the input, behind a rule of its own:
        transcript, rule, input, rule, panel -- the input boxed between
        two lines the way Claude Code's is (the creator, 2026-09-12)."""
        cols = shutil.get_terminal_size((80, 24)).columns
        rule = [("class:sim.rule", "─" * max(10, cols - 1) + "\n")]
        text = self._footer_text()
        if isinstance(text, str):
            return rule + [("class:sim.footer", text or "")]
        return rule + list(text or [("class:sim.footer", "")])

    async def run(self) -> None:
        """Read lines until EOF, Ctrl-D, or `stop()`.

        `prompt_async()` only holds the terminal in raw mode -- no local
        echo, `ISIG` off so Ctrl-C is a key event instead of a real
        `SIGINT`, `ICRNL` off so a bare `\\r` reaches prompt_toolkit as
        Enter -- for as long as it is the one awaiting input. Awaiting
        `_on_line(line)` right here, inline, gave up that raw mode for
        the whole turn: the terminal falls back to cooked mode between
        one `prompt_async()` call and the next, and anything typed in
        that gap is handled by the kernel's own line discipline instead
        of prompt_toolkit's. Live-caught (pexpect+pyte, 2026-09-08): a
        line typed while a turn was running sat in the buffer, pre-filled
        but never submitted, because its trailing `\\r` arrived translated
        to `\\n` (`ICRNL`) and this module's own binding treats `c-j` as
        "insert a newline", not "submit" -- so the *next* real keystroke
        appended onto it instead of starting a fresh line, which is
        exactly the "silently merged into one multi-line message" a
        wave-7 observer reported. Far worse: with `ISIG` back on in that
        same gap, a Ctrl-C meant to cancel the running turn is consumed
        by the kernel as a real `SIGINT` before prompt_toolkit ever sees
        it -- and `kernel/cli.py`'s own signal handler answers a *single*
        `SIGINT` by publishing `system.stop`, not by cancelling one turn.
        One Ctrl-C at the wrong moment shut down the whole system and
        left the terminal wedged in cooked mode, accepting no further
        input, with no crash and no message -- reproduced live with a
        pty harness, not inferred.

        The fix: never give up raw mode while a turn is running. Each
        line goes on a queue instead of being awaited inline, so the
        very next loop iteration is back inside `prompt_async()` -- raw
        mode never lapses -- while a single background worker drains the
        queue and runs `on_line` calls one at a time, in the order they
        arrived. A second line typed mid-turn is queued behind the first
        and runs after it finishes; it is never merged with it and never
        silently dropped.
        """
        patch_stdout = _pt()["patch_stdout"]
        self._session = self._build_session()
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def _drain() -> None:
            while True:
                line = await queue.get()
                try:
                    await self._on_line(line)
                except asyncio.CancelledError:
                    raise
                finally:
                    queue.task_done()

        worker = asyncio.ensure_future(_drain())
        try:
            # `patch_stdout` is what makes the prompt a real sticky footer:
            # every print in the process, including the ones the bus
            # handlers make from other threads, is rendered above the
            # prompt instead of on top of it.
            with patch_stdout(raw=True):
                while not self._stopped:
                    try:
                        line = await self._session.prompt_async()
                    except (EOFError, KeyboardInterrupt):
                        break
                    except asyncio.CancelledError:
                        raise
                    if self._stopped:
                        break
                    if line is None or not line.strip():
                        continue
                    queue.put_nowait(line)
        finally:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass


__all__ = ["COMMANDS", "DOUBLE_INTERRUPT_S", "PromptToolkitMissing", "Tui", "available", "path_matches"]
