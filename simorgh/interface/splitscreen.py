"""The split screen: the conversation on the left, boxes on the right.

The creator, 2026-10-30: "a right side box that can later get split in
vertical boxes ... user can use a combination of some key and tab to switch
between these windows and make them full size."

    ┌ conversation ─────────────────────┐┌ CPU · GPU ──────────────┐
    │ ...the transcript...              ││ cpu  ▂▃▅▇▅▃  37%        │
    │                                   │├ Memory · numbers ───────┤
    │                                   ││ RAM ████░░░░  55%        │
    │                                   │├ research · notify ──────┤
    │                                   ││ ✓ read_file ...          │
    └───────────────────────────────────┘└─────────────────────────┘
     live rows · an approval
     ❯ the line being typed
     the status ribbon

The inline prompt (`tui.Tui`) prints into the terminal's own scrollback,
which is what keeps native scrolling and copy/paste -- and is exactly why
it cannot have a column beside the output. This is a full-screen
prompt_toolkit Application instead, chosen with `[interface] layout =
"split"`: every `print` in the process is captured into the transcript
pane (`Transcript`), which scrolls with PageUp/PageDown.

Keys -- typing always goes to the prompt, whichever pane has focus:

- **Shift-Tab** moves focus: conversation, then each box in turn.
- **Ctrl-F** makes the focused pane full size; again (or Esc) restores.
- **Ctrl-B** hides or shows the right column.
- **PageUp / PageDown** scroll the conversation; typing returns to the end.

Everything the inline prompt does -- the approval picker, Ctrl-J newlines,
Ctrl-C cancel-then-exit, completion, history -- is the same object's
(`Tui._key_bindings`), so the two cannot drift apart.
"""

from __future__ import annotations

import asyncio
import io
import sys
import threading
from typing import Callable

from .tui import PANEL_REFRESH_S, PROMPT_GLYPH, Tui, _make_completer, _make_lexer, _parse, _pt, _style

#: Most transcript lines kept in memory; the Ledger keeps everything.
TRANSCRIPT_LINES = 5000
#: Columns the right column takes by default (`[interface] side_width`).
SIDE_WIDTH = 46


class Transcript(io.TextIOBase):
    """A file-like sink for `sys.stdout` that keeps lines for the
    conversation pane. Safe to write from any thread; `on_change` is
    called after each write (the app's thread-safe `invalidate`)."""

    def __init__(self, *, limit: int = TRANSCRIPT_LINES, on_change: Callable[[], None] | None = None) -> None:
        super().__init__()
        self._lines: list[str] = []
        self._partial = ""
        self._limit = limit
        self._lock = threading.Lock()
        self.on_change = on_change
        #: How many lines up from the end the view is; 0 follows new output.
        self.scroll = 0

    # -- file protocol --------------------------------------------------------------------------
    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        # Colour and unicode decisions ask this; the pane renders ANSI.
        return True

    @property
    def encoding(self) -> str:
        return "utf-8"

    def write(self, text: str) -> int:
        if not text:
            return 0
        with self._lock:
            chunks = (self._partial + text.replace("\r\n", "\n")).split("\n")
            self._partial = chunks.pop()
            for chunk in chunks:
                # A carriage return redraws a line in place on a real
                # terminal; here the last version of the line is the line.
                self._lines.append(chunk.rsplit("\r", 1)[-1])
            if len(self._lines) > self._limit:
                del self._lines[: len(self._lines) - self._limit]
        if self.on_change is not None:
            self.on_change()
        return len(text)

    def flush(self) -> None:
        return None

    # -- the pane ---------------------------------------------------------------------------------
    def lines(self) -> list[str]:
        with self._lock:
            return self._lines + ([self._partial] if self._partial else [])

    def tail(self, rows: int) -> tuple[list[str], int]:
        """The lines to draw for a pane `rows` tall at the current scroll,
        and the index (within them) of the line the view should end on."""
        lines = self.lines()
        self.scroll = max(0, min(self.scroll, max(0, len(lines) - 1)))
        end = len(lines) - self.scroll
        start = max(0, end - rows * 3)       # wrapped lines take more than one row
        return lines[start:end], max(0, end - start - 1)


class Panes:
    """Which pane has focus and which, if any, is full size. Pane 0 is the
    conversation; 1.. are the boxes, whose number changes as agents come
    and go -- so the focus is clamped every time it is read."""

    def __init__(self) -> None:
        self.focus = 0
        self.maximised: int | None = None
        self.side_hidden = False

    def clamp(self, boxes: int) -> None:
        self.focus = min(self.focus, boxes)
        if self.maximised is not None and self.maximised > boxes:
            self.maximised = None

    def next(self, boxes: int) -> None:
        self.focus = (self.focus + 1) % (boxes + 1)
        if self.maximised is not None:
            self.maximised = self.focus

    def toggle_full(self) -> None:
        self.maximised = None if self.maximised is not None else self.focus

    def restore(self) -> None:
        self.maximised = None


class SplitTui(Tui):
    """`Tui` laid out full screen with a right-hand column of boxes.
    `boxes()` returns the boxes to show, top to bottom (`sidepanel.py`)."""

    def __init__(self, *, boxes: Callable[[], list], side_width: int = SIDE_WIDTH, **kwargs) -> None:
        super().__init__(**kwargs)
        self._boxes = boxes
        self._side_width = max(24, int(side_width))
        self.panes = Panes()
        self.transcript = Transcript()
        self._real_stdout = None
        self._app = None
        #: A terminal to draw on instead of the real one (tests).
        self.input = None
        self.output = None

    # -- stdout -------------------------------------------------------------------------------------
    def capture_stdout(self) -> None:
        """Every print from here on lands in the conversation pane."""
        if self._real_stdout is None:
            self._real_stdout = sys.stdout
            sys.stdout = self.transcript

    def _release_stdout(self) -> None:
        if self._real_stdout is not None:
            sys.stdout = self._real_stdout
            self._real_stdout = None

    def _invalidate(self) -> None:
        app = self._app
        if app is not None and app.is_running:
            app.invalidate()

    # -- layout -------------------------------------------------------------------------------------
    def _size(self) -> tuple[int, int]:
        app = self._app
        try:
            size = app.output.get_size()
            return size.columns, size.rows
        except Exception:  # noqa: BLE001 -- before the app runs
            return 120, 40

    def _box_list(self) -> list:
        try:
            boxes = list(self._boxes() or [])
        except Exception:  # noqa: BLE001 -- a broken box must not take the screen down
            boxes = []
        self.panes.clamp(len(boxes))
        return boxes

    def _pane_title(self, index: int, title: str) -> str:
        hint = "  ⤢" if self.panes.focus == index and self.panes.maximised is None else ""
        return f" {title}{hint} "

    def _frame(self, body, *, title: str, focused: bool, height=None):
        """A rounded box with its title in the top edge:

            ╭─ CPU · GPU ──────╮
            │ ...              │
            ╰──────────────────╯

        prompt_toolkit's own `Frame` draws `|  title  |`; this is the
        lighter, rounded shape the rest of the screen's glyphs suit."""
        pt = _pt()
        layout = pt["layout"]
        label = f" {title} "
        top = layout.VSplit([
            layout.Window(width=2, height=1, char="╭─", style="class:frame.border"),
            layout.Window(layout.FormattedTextControl([("class:frame.label", label)]), height=1,
                          width=pt["D"].exact(len(label)), dont_extend_width=True),
            layout.Window(height=1, char="─", style="class:frame.border"),
            layout.Window(width=1, height=1, char="╮", style="class:frame.border"),
        ], height=1)
        middle = layout.VSplit([
            layout.Window(width=1, char="│", style="class:frame.border"), body,
            layout.Window(width=1, char="│", style="class:frame.border"),
        ])
        bottom = layout.VSplit([
            layout.Window(width=1, height=1, char="╰", style="class:frame.border"),
            layout.Window(height=1, char="─", style="class:frame.border"),
            layout.Window(width=1, height=1, char="╯", style="class:frame.border"),
        ], height=1)
        return layout.HSplit([top, middle, bottom], height=height,
                             style="class:pane.focused" if focused else "")

    def _box_pane(self, index: int, box, *, width: int, height: int):
        pt = _pt()
        layout = pt["layout"]
        control = layout.FormattedTextControl(lambda: box.render(width - 2, max(1, height - 2)), focusable=False)
        return self._frame(layout.Window(control, wrap_lines=False), title=self._pane_title(index, box.title).strip(),
                           focused=self.panes.focus == index, height=pt["D"](preferred=height))

    def _conversation(self, *, rows: int):
        pt = _pt()
        layout = pt["layout"]

        def text():
            lines, _ = self.transcript.tail(rows)
            return pt["ANSI"]("\n".join(lines))

        def cursor():
            _, last = self.transcript.tail(rows)
            return pt["Point"](x=0, y=last)

        window = layout.Window(layout.FormattedTextControl(text, get_cursor_position=cursor, show_cursor=False),
                               wrap_lines=True)
        title = "conversation" + (f"  ↑ {self.transcript.scroll} lines up" if self.transcript.scroll else "")
        return self._frame(window, title=self._pane_title(0, title).strip(), focused=self.panes.focus == 0)

    def _top(self):
        """The part above the prompt: conversation and boxes, as the focus
        and full-size state say."""
        pt = _pt()
        layout = pt["layout"]
        cols, rows = self._size()
        room = max(6, rows - 6)
        boxes = self._box_list()
        full = self.panes.maximised
        if full is not None and full > 0:
            return self._box_pane(full, boxes[full - 1], width=cols, height=room)
        conversation = self._conversation(rows=room)
        if full == 0 or self.panes.side_hidden or not boxes:
            return conversation
        side_w = min(self._side_width, max(24, cols // 2))
        each = max(4, room // len(boxes))
        column = layout.HSplit([self._box_pane(i + 1, box, width=side_w, height=each)
                                for i, box in enumerate(boxes)], width=pt["D"].exact(side_w))
        return layout.VSplit([conversation, column])

    def _bottom_rows(self):
        cols, _ = self._size()
        rows = self._live_rows()
        if rows and rows[-1][1] != "\n":
            rows.append(("", "\n"))
        return rows + self._picker_rows()

    def _build_app(self):
        pt = _pt()
        layout = pt["layout"]
        history = pt["FileHistory"](str(self._history_path)) if self._history_path else pt["InMemoryHistory"]()
        self._buffer = pt["Buffer"](history=history, completer=_make_completer(self._root),
                                    complete_while_typing=True, multiline=False, accept_handler=self._accept)
        prompt = layout.Window(
            layout.BufferControl(self._buffer, lexer=_make_lexer(),
                                 input_processors=[pt["BeforeInput"](f"{PROMPT_GLYPH} ", style="class:sim.prompt")]),
            height=pt["D"](min=1, max=8), wrap_lines=True, dont_extend_height=True)
        rule = layout.Window(height=1, char="─", style="class:sim.rule")
        root = layout.HSplit([
            layout.DynamicContainer(self._top),
            layout.ConditionalContainer(
                layout.Window(layout.FormattedTextControl(self._bottom_rows), dont_extend_height=True,
                              height=pt["D"](max=14)),
                filter=pt["Condition"](lambda: bool(self._bottom_rows()))),
            rule, prompt, rule,
            layout.Window(layout.FormattedTextControl(self._footer_rows), dont_extend_height=True),
        ])
        body = layout.FloatContainer(content=root, floats=[
            layout.Float(xcursor=True, ycursor=True, content=pt["CompletionsMenu"](max_height=12))])
        output = self.output or pt["create_output"](stdout=self._real_stdout or sys.__stdout__)
        return pt["Application"](
            input=self.input,
            layout=layout.Layout(body, focused_element=prompt),
            key_bindings=pt["merge_key_bindings"]([self._key_bindings(), self._pane_bindings()]),
            style=_style(), full_screen=True, mouse_support=False, refresh_interval=PANEL_REFRESH_S,
            output=output)

    def _footer_rows(self):
        text = self._footer_text()
        if isinstance(text, str):
            text = [("class:sim.footer", text or "")]
        hint = [("class:pane.hint", "   ⇧Tab focus · ^F full size · ^B side · PgUp/PgDn scroll")]
        return list(text or []) + hint

    def _pane_bindings(self):
        pt = _pt()
        keys = pt["KeyBindings"]()

        @keys.add("s-tab")
        def _next(event) -> None:
            # Shift-Tab steps back through an open completion menu while a
            # word is being typed; otherwise it moves the focus. Not a
            # `has_completions` filter: completion runs in the background,
            # and results for a line already sent can land on the empty
            # prompt after it -- which turned Shift-Tab into a no-op.
            buffer = event.current_buffer
            if buffer.complete_state is not None and buffer.text.strip():
                buffer.complete_previous()
                return
            buffer.cancel_completion()
            self.panes.next(len(self._box_list()))

        @keys.add("c-f")
        def _full(event) -> None:
            self.panes.toggle_full()

        @keys.add("escape", filter=pt["Condition"](lambda: self.panes.maximised is not None and not self.picking()))
        def _restore(event) -> None:
            self.panes.restore()

        @keys.add("c-b")
        def _side(event) -> None:
            self.panes.side_hidden = not self.panes.side_hidden

        @keys.add("pageup")
        def _up(event) -> None:
            self.transcript.scroll += max(1, self._size()[1] // 2)

        @keys.add("pagedown")
        def _down(event) -> None:
            self.transcript.scroll = max(0, self.transcript.scroll - max(1, self._size()[1] // 2))

        @keys.add("c-d", filter=pt["Condition"](lambda: not self._buffer.text))
        def _eof(event) -> None:
            event.app.exit(exception=EOFError)

        return keys

    # -- lines --------------------------------------------------------------------------------------
    def _accept(self, buffer) -> bool:
        line = buffer.text
        self.transcript.scroll = 0
        if not line.strip():
            return False
        command = _parse(line)
        if command is not None and command.name in ("exit", "quit", "restart"):
            if command.name == "restart":
                self.stop_reason = "restart"
            self._stopped = True
            self._app.exit()
            return False
        self._queue.put_nowait(line)
        return False

    def stop(self) -> None:
        self._stopped = True
        app = self._app
        if app is not None and app.is_running:
            app.exit(exception=EOFError, style="class:exiting")

    async def run(self) -> None:
        """Run the screen until exit, Ctrl-D, a double Ctrl-C, or `stop()`.
        Lines are queued and handled one at a time by a worker, as in
        `Tui.run` and for the same reason: the screen never stops reading
        keys while a turn runs."""
        self.capture_stdout()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._app = self._build_app()
        # The service's `_invalidate` reaches the app through `_session.app`.
        self._session = type("_Session", (), {"app": self._app})()
        self.transcript.on_change = self._invalidate

        async def _drain() -> None:
            while True:
                line = await self._queue.get()
                try:
                    if self._typing_an_answer(line):
                        continue
                    print(f"{PROMPT_GLYPH} {line}")
                    await self._on_line(line)
                except asyncio.CancelledError:
                    raise
                finally:
                    self._queue.task_done()

        worker = asyncio.ensure_future(_drain())
        asyncio.get_running_loop().set_exception_handler(self._on_loop_exception)
        try:
            await self._app.run_async()
        except (EOFError, KeyboardInterrupt):
            pass
        finally:
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass
            self._release_stdout()
            # Leave the last of the conversation on the real terminal, so
            # leaving the full screen does not leave a blank one.
            for line in self.transcript.lines()[-20:]:
                print(line)


__all__ = ["Panes", "SIDE_WIDTH", "SplitTui", "TRANSCRIPT_LINES", "Transcript"]
