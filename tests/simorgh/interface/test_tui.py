"""The prompt_toolkit prompt (`interface/tui.py`).

Driven through prompt_toolkit's own pipe input rather than a pty: the
keystrokes are real, the key bindings are the real ones, and nothing
needs a terminal. The pure parts -- what one Ctrl-C means, what `/` and
`@` complete to, how a line is coloured -- are plain functions and are
tested as such, because those are the rules a reader needs to be able to
change with confidence.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.interface import tui
from simorgh.interface.tui import (
    COMMANDS,
    Tui,
    _lex_line,
    _make_completer,
    _MAX_LINE_FOR_COMPLETION_AND_LEXING,
    path_matches,
)


def _styles(line: str, *, first_line: bool = True) -> list[tuple[str, str]]:
    return [(style.replace("class:sim.", ""), text) for style, text in _lex_line(line, first_line=first_line)]


class TestTheLexer(unittest.TestCase):
    def test_a_known_first_word_is_a_command(self):
        self.assertEqual(_styles("status")[0], ("command", "status"))

    def test_a_leading_slash_is_still_the_command(self):
        self.assertEqual(_styles("/status")[0], ("command", "/status"))

    def test_a_bare_slash_is_the_command_prefix_not_a_path(self):
        self.assertEqual(_styles("/")[0], ("command", "/"))

    def test_a_path_argument_is_coloured_as_a_path(self):
        self.assertIn(("path", "simorgh/hello.py"), _styles("improve simorgh/hello.py add docs"))

    def test_an_at_reference_is_a_path(self):
        self.assertIn(("path", "@docs/EVOLUTION.md"), _styles("research @docs/EVOLUTION.md"))

    def test_a_quoted_string_is_a_string(self):
        self.assertIn(("string", '"big'), _styles('plan "big goal"'))

    def test_an_unknown_first_word_is_plain_text_because_it_is_chat(self):
        self.assertEqual(_styles("what did you do today")[0], ("", "what"))

    def test_the_tokens_rejoin_into_the_original_line(self):
        """prompt_toolkit renders exactly what the lexer returns, so
        losing or adding a space here would silently rewrite the input."""
        for line in ("  status   simorgh/x.py  ", "improve a b", "", "   "):
            self.assertEqual("".join(text for _, text in _lex_line(line, first_line=True)), line)


class TestCompletion(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "simorgh").mkdir()
        (self.root / "simorgh" / "hello.py").write_text("x")
        (self.root / "docs").mkdir()
        (self.root / "sim.sh").write_text("x")
        (self.root / ".hidden").write_text("x")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_a_prefix_matches_files_and_directories(self):
        self.assertEqual(path_matches("@sim", root=self.root), ["simorgh/", "sim.sh"])

    def test_directories_come_first_and_are_marked(self):
        matches = path_matches("@", root=self.root)
        self.assertEqual(matches[:2], ["docs/", "simorgh/"])
        self.assertIn("sim.sh", matches)

    def test_it_descends_one_level_at_a_time(self):
        self.assertEqual(path_matches("@simorgh/h", root=self.root), ["simorgh/hello.py"])

    def test_dotfiles_are_hidden_until_asked_for_by_name(self):
        self.assertNotIn(".hidden", path_matches("@", root=self.root))
        self.assertEqual(path_matches("@.hid", root=self.root), [".hidden"])

    def test_a_missing_directory_completes_to_nothing_rather_than_raising(self):
        self.assertEqual(path_matches("@nope/x", root=self.root), [])

    def test_every_advertised_command_is_one_the_parser_knows(self):
        """The menu must not offer a command that then fails to parse."""
        from simorgh.interface.parser import COMMAND_NAMES

        for name, _desc in COMMANDS:
            self.assertIn(name, COMMAND_NAMES, f"the menu offers {name!r}, which parser.py does not know")


class _FakeCompleteEvent:
    completion_requested = False


class TestLongLinesDoNotFreezeCompletionOrLexing(unittest.TestCase):
    """A long pasted/typed line with no whitespace is one giant "word".
    `complete_while_typing=True` calls `_SimCompleter.get_completions` once
    per *character* inserted (confirmed live via cProfile: exactly as many
    calls to `document.get_word_before_cursor` as characters typed), and
    each of those calls scanned back over the *entire* text-before-cursor
    looking for a word boundary that, for a whitespace-free paste, is
    never found before position 0. That is O(current length) of work on
    every one of O(length) keystrokes -- O(length^2) overall, and it is
    what turned a several-thousand-character paste into a multi-minute
    freeze (reproduced live with a pty+pyte harness, 0% CPU, no progress).
    `_lex_line` re-scans the whole line on every redraw for the same
    reason, though prompt_toolkit coalesces redraws across bursts of
    keystrokes so it contributes less in practice than the completer does.

    Both now bail out in O(1) once the line crosses
    `_MAX_LINE_FOR_COMPLETION_AND_LEXING` -- no real command name or
    repo-relative path is anywhere near that long, so nothing genuine is
    ever short-circuited by it.
    """

    def test_lex_line_returns_one_plain_span_past_the_cap(self):
        line = "x" * (_MAX_LINE_FOR_COMPLETION_AND_LEXING + 1)
        self.assertEqual(_lex_line(line, first_line=True), [("", line)])

    def test_lex_line_still_highlights_up_to_the_cap(self):
        line = "@" + "x" * (_MAX_LINE_FOR_COMPLETION_AND_LEXING - 1)
        self.assertEqual(len(line), _MAX_LINE_FOR_COMPLETION_AND_LEXING)
        self.assertEqual(_lex_line(line, first_line=True), [("class:sim.path", line)])

    def test_completer_yields_nothing_past_the_cap(self):
        from prompt_toolkit.document import Document

        completer = _make_completer(Path("."))
        line = "@" + "x" * _MAX_LINE_FOR_COMPLETION_AND_LEXING
        doc = Document(line, cursor_position=len(line))
        self.assertEqual(list(completer.get_completions(doc, _FakeCompleteEvent())), [])

    def test_completions_do_not_grow_quadratically_with_line_length(self):
        """Feed the completer a document once per character of a growing,
        whitespace-free line -- exactly how `complete_while_typing=True`
        drives it while someone types or pastes -- and confirm the total
        cost stays roughly linear instead of quadratic. An O(n^2)
        regression would make the second run take ~4x as long as the
        first for only 2x the length; a capped, roughly-linear one keeps
        that ratio well under that.
        """
        import time
        from prompt_toolkit.document import Document

        completer = _make_completer(Path("."))

        def total_time(length: int) -> float:
            text = "x" * length
            start = time.perf_counter()
            for i in range(1, length + 1):
                doc = Document(text[:i], cursor_position=i)
                list(completer.get_completions(doc, _FakeCompleteEvent()))
            return time.perf_counter() - start

        small = _MAX_LINE_FOR_COMPLETION_AND_LEXING
        large = _MAX_LINE_FOR_COMPLETION_AND_LEXING * 4
        small_time = total_time(small)
        large_time = total_time(large)
        # Uncapped, quadrupling the length quadruples the per-call cost on
        # top of quadrupling the call count -- roughly a 16x blow-up.
        # Capped past the threshold, the extra calls are O(1), so the
        # ratio should stay close to the 4x call-count growth.
        self.assertLess(
            large_time,
            small_time * 8,
            f"completer time grew {large_time / small_time:.1f}x for a 4x longer line "
            "-- looks quadratic again",
        )


class TestTheInterruptRule(unittest.TestCase):
    """One Ctrl-C must not end a session. Nobody should lose a running
    task to a mistimed keystroke."""

    def setUp(self) -> None:
        self.t = 0.0
        self.tui = Tui(on_line=self._noop, now=lambda: self.t, double_interrupt_s=2.0)

    async def _noop(self, line: str) -> None: ...

    def test_the_first_press_with_text_typed_clears_the_buffer(self):
        self.assertEqual(self.tui.interrupt(buffer_was_empty=False), "cleared")

    def test_the_first_press_on_an_empty_buffer_cancels_the_running_work(self):
        self.assertEqual(self.tui.interrupt(buffer_was_empty=True), "cancelled")

    def test_a_second_press_straight_away_exits(self):
        self.tui.interrupt(buffer_was_empty=True)
        self.t += 0.3
        self.assertEqual(self.tui.interrupt(buffer_was_empty=True), "exit")

    def test_a_second_press_long_after_does_not_exit(self):
        self.tui.interrupt(buffer_was_empty=True)
        self.t += 5.0
        self.assertEqual(self.tui.interrupt(buffer_was_empty=True), "cancelled")

    def test_clearing_then_pressing_again_still_exits(self):
        """The double press is about the two keystrokes, not about what
        was in the buffer for the first one."""
        self.tui.interrupt(buffer_was_empty=False)
        self.t += 0.2
        self.assertEqual(self.tui.interrupt(buffer_was_empty=True), "exit")


class TestReadingLines(unittest.IsolatedAsyncioTestCase):
    """Real keystrokes through prompt_toolkit's own pipe input."""

    async def _drive(self, keys: str, **kw) -> list[str]:
        from prompt_toolkit.application import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        seen: list[str] = []

        async def on_line(line: str) -> None:
            seen.append(line)

        with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
            prompt = Tui(on_line=on_line, **kw)
            inp.send_text(keys)
            await asyncio.wait_for(prompt.run(), timeout=10)
        return seen

    async def test_enter_submits_a_line(self):
        self.assertEqual(await self._drive("status\r\x04"), ["status"])

    async def test_several_lines_arrive_in_order(self):
        self.assertEqual(await self._drive("status\rtasks\r\x04"), ["status", "tasks"])

    async def test_ctrl_j_inserts_a_newline_instead_of_submitting(self):
        """Multi-line input: the whole block is one submission."""
        self.assertEqual(await self._drive("first\x0asecond\r\x04"), ["first\nsecond"])

    async def test_a_blank_line_is_not_dispatched(self):
        self.assertEqual(await self._drive("\r  \rstatus\r\x04"), ["status"])

    async def test_ctrl_d_ends_the_prompt(self):
        self.assertEqual(await self._drive("\x04"), [])

    async def test_a_second_line_typed_mid_turn_queues_instead_of_blocking(self):
        """Live-caught with a real pty (2026-09-08): `run()` used to
        `await on_line(line)` inline, so `prompt_async()` was not running
        -- and the terminal was not even in raw mode -- for the whole
        length of a turn. A line typed in that window landed in the
        kernel's own cooked-mode line discipline instead of
        prompt_toolkit's, and its trailing Enter came out translated
        (`ICRNL`) to a literal newline -- this module's own `c-j` binding
        for "insert a newline, not submit" -- so it never became its own
        submission; the next keystroke just appended onto it, which is
        the "silently merged into one multi-line message" a wave-7
        observer reported. The fix: queue each line and hand it to a
        background worker instead of awaiting it inline, so the loop is
        back inside `prompt_async()` before the first line's handler has
        even started. This proves the structural half of that fix: a
        second line submitted while the first is still running is kept
        separate and runs after it, never merged and never dropped."""
        from prompt_toolkit.application import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        seen: list[str] = []
        release = asyncio.Event()
        started = asyncio.Event()

        async def on_line(line: str) -> None:
            if line == "slow":
                started.set()
                await release.wait()
            seen.append(line)

        with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
            prompt = Tui(on_line=on_line)
            run_task = asyncio.ensure_future(prompt.run())
            inp.send_text("slow\r")
            await asyncio.wait_for(started.wait(), timeout=5)
            # The first turn is still running (blocked on `release`) --
            # a second line submitted now must be accepted, not lost and
            # not merged into the first turn's text.
            inp.send_text("second\r")
            await asyncio.sleep(0.05)
            self.assertEqual(seen, [])  # the first turn has not finished
            release.set()
            inp.send_text("\x04")
            await asyncio.wait_for(run_task, timeout=5)
        self.assertEqual(seen, ["slow", "second"])

    async def test_ctrl_c_still_reaches_the_prompt_mid_turn(self):
        """The same bug's other half, also live-caught: with `run()`
        blocked awaiting a turn, the terminal was in cooked mode with
        `ISIG` back on, so a Ctrl-C meant to cancel the running turn
        never reached this module's own key binding at all -- it was
        consumed by the OS as a real SIGINT before prompt_toolkit ever
        saw it. `kernel/cli.py` answers a first SIGINT by publishing
        `system.stop`, not by cancelling one turn, so one mistimed
        Ctrl-C could shut down the whole system and wedge the terminal
        in cooked mode, accepting no further input -- reproduced with a
        real pty, no crash, no message. Proof that the fix keeps
        `prompt_async()` (and so this binding) live for the whole turn:
        Ctrl-C sent while `on_line` is still running for an earlier line
        must still fire `on_interrupt`."""
        from prompt_toolkit.application import create_app_session
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput

        release = asyncio.Event()
        started = asyncio.Event()
        interrupted: list[bool] = []

        async def on_line(line: str) -> None:
            started.set()
            await release.wait()

        with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
            prompt = Tui(on_line=on_line, on_interrupt=lambda: interrupted.append(True))
            run_task = asyncio.ensure_future(prompt.run())
            inp.send_text("slow\r")
            await asyncio.wait_for(started.wait(), timeout=5)
            inp.send_text("\x03")  # Ctrl-C, buffer empty -> "cancel the running turn"
            await asyncio.sleep(0.05)
            self.assertEqual(interrupted, [True])
            release.set()
            inp.send_text("\x04")
            await asyncio.wait_for(run_task, timeout=5)

    async def test_two_interrupts_end_the_prompt(self):
        self.assertEqual(await self._drive("\x03\x03"), [])

    async def test_one_interrupt_does_not_end_the_prompt(self):
        self.assertEqual(await self._drive("\x03status\r\x04"), ["status"])

    async def test_an_interrupt_with_text_typed_clears_it_and_keeps_going(self):
        self.assertEqual(await self._drive("junk\x03status\r\x04"), ["status"])

    async def test_history_is_written_to_the_configured_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history"
            await self._drive("status\r\x04", history_path=path)
            self.assertIn("status", path.read_text())

    async def test_history_from_an_earlier_session_is_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history"
            await self._drive("first command\r\x04", history_path=path)
            # Up-arrow recalls it, Enter re-submits it.
            self.assertEqual(
                await self._drive("\x1b[A\r\x04", history_path=path), ["first command"],
            )

    async def test_the_footer_callback_is_what_the_toolbar_shows(self):
        prompt = Tui(on_line=self._noop_line, footer_text=lambda: "thinking [3s]")
        session = prompt._build_session()  # noqa: SLF001
        toolbar = session.bottom_toolbar()
        self.assertEqual(toolbar[0][0], "class:sim.rule", "a rule boxes the input from below")
        self.assertEqual(toolbar[1:], [("class:sim.footer", "thinking [3s]")])

    async def _noop_line(self, line: str) -> None: ...


class TestAvailability(unittest.TestCase):
    def test_available_reports_whether_prompt_toolkit_is_importable(self):
        self.assertTrue(tui.available())  # it is a declared dependency of this suite


class TestWhenTheServiceUsesIt(unittest.TestCase):
    """The rich prompt is for a real terminal. Everywhere else -- a pipe,
    a test, a machine without prompt_toolkit -- the readline REPL is still
    correct and must keep being chosen."""

    def _service(self, **cfg):
        from simorgh.interface.config import Config as InterfaceConfig
        from simorgh.interface.service import Service

        return Service(InterfaceConfig(**cfg), run_repl=True, http_enabled=False)

    def test_not_used_when_the_config_turns_it_off(self):
        self.assertFalse(self._service(rich_prompt=False)._use_tui())  # noqa: SLF001

    def test_not_used_when_stdout_is_not_a_terminal(self):
        # pytest captures stdout, so this is the real state under test.
        self.assertFalse(self._service(rich_prompt=True)._use_tui())  # noqa: SLF001

    def test_not_used_when_prompt_toolkit_is_missing(self):
        service = self._service(rich_prompt=True)
        with unittest.mock.patch.object(tui, "available", return_value=False):
            self.assertFalse(service._use_tui())  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()


class TestTheTaskListRendering(unittest.TestCase):
    """`tasks` output. Live-caught 2026-09-07: it printed only a count,
    and once it printed rows, every project read `pending 0/0 steps` while
    the same ids showed as `claimed` in the task list directly above."""

    def _render(self, tasks, projects=()):
        from simorgh.interface.render import task_list

        return task_list(list(tasks), list(projects), enabled=False)

    def test_a_project_with_no_steps_shows_its_own_status(self):
        out = self._render(
            [{"task_id": "p1", "kind": "project", "status": "claimed",
              "origin": "curiosity", "description": "design a thing"}],
            [{"project_id": "p1", "rollup": "pending", "done": 0, "total": 0, "stalled": False}],
        )
        project_line = out.splitlines()[-1]
        self.assertIn("claimed", project_line)
        self.assertNotIn("0/0", project_line)
        self.assertIn("not broken down", project_line)

    def test_a_project_with_steps_shows_the_rollup_and_the_count(self):
        out = self._render(
            [{"task_id": "p1", "kind": "project", "status": "in_progress",
              "origin": "human", "description": "a thing"}],
            [{"project_id": "p1", "rollup": "in_progress", "done": 1, "total": 3, "stalled": False}],
        )
        self.assertIn("1/3 steps", out)

    def test_an_empty_backlog_says_so(self):
        self.assertEqual(self._render([]), "no tasks")

    def test_the_rows_carry_id_status_kind_origin_and_description(self):
        out = self._render([{"task_id": "abc123def456", "kind": "patch", "status": "available",
                             "origin": "curiosity", "description": "tighten the retry loop"}])
        for fragment in ("abc123def456", "available", "patch", "curiosity", "tighten the retry loop"):
            self.assertIn(fragment, out)

    def test_a_long_backlog_is_truncated_with_a_count_of_the_rest(self):
        tasks = [{"task_id": f"t{i:012d}", "kind": "patch", "status": "available",
                  "origin": "curiosity", "description": f"thing {i}"} for i in range(30)]
        out = self._render(tasks, [])
        self.assertIn("... 10 more", out)
        self.assertIn("tasks all", out)

    def test_work_in_flight_is_listed_before_work_that_is_waiting(self):
        out = self._render([
            {"task_id": "waiting", "kind": "patch", "status": "available",
             "origin": "curiosity", "description": "later"},
            {"task_id": "moving", "kind": "patch", "status": "in_progress",
             "origin": "human", "description": "now"},
        ])
        self.assertLess(out.index("moving"), out.index("waiting"))


class TestThePanelToolbar(unittest.IsolatedAsyncioTestCase):
    """The bottom panel (`panel.py`) hands the toolbar formatted-text
    fragments with their own style classes -- the breathing word's
    shade among them -- and the toolbar must pass them through as-is,
    while a plain string still becomes one footer fragment."""

    async def test_formatted_rows_pass_through_untouched(self):
        rows = [("class:sim.breath.3", "✻ Osmosing…"), ("class:sim.footer", "  patch · x · 3s"), ("", "\n"), ("class:sim.status", "auto on")]
        prompt = Tui(on_line=self._noop_line, footer_text=lambda: rows)
        session = prompt._build_session()  # noqa: SLF001
        toolbar = session.bottom_toolbar()
        self.assertEqual(toolbar[0][0], "class:sim.rule")
        self.assertEqual(toolbar[1:], rows)

    async def test_the_input_bar_has_a_rule_above_the_prompt(self):
        prompt = Tui(on_line=self._noop_line)
        session = prompt._build_session()  # noqa: SLF001
        message = session.message() if callable(session.message) else session.message
        self.assertEqual(message[0][0], "class:sim.rule")
        self.assertTrue(message[0][1].startswith("─"))
        self.assertTrue(message[0][1].endswith("\n"))
        self.assertEqual(message[-1], ("class:sim.prompt", "❯ "))

    async def test_the_live_section_sits_above_the_rule_and_the_prompt(self):
        rows = [("class:sim.live", "⏺ run_shell(pytest)"), ("", "\n"), ("class:sim.breath.2", "✻ Osmosing…")]
        prompt = Tui(on_line=self._noop_line, live_text=lambda: rows)
        session = prompt._build_session()  # noqa: SLF001
        message = session.message() if callable(session.message) else session.message
        self.assertEqual(message[:3], rows)
        self.assertEqual(message[3], ("", "\n"))
        self.assertEqual(message[4][0], "class:sim.rule")
        self.assertEqual(message[-1], ("class:sim.prompt", "❯ "))

    async def test_every_breathing_shade_has_a_colour(self):
        from simorgh.interface import panel
        from simorgh.interface.tui import BREATH_COLOURS

        self.assertEqual(len(BREATH_COLOURS), panel.BREATH_SHADES)

    async def _noop_line(self, line: str) -> None: ...
