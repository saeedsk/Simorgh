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
from simorgh.interface.tui import COMMANDS, Tui, _lex_line, path_matches


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
        self.assertEqual(session.bottom_toolbar(), [("class:sim.footer", "thinking [3s]")])

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
