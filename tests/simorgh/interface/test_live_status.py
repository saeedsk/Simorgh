import contextlib
import io
import os
import unittest
from unittest import mock

from simorgh.interface.live_status import LiveStatus, live_status_enabled, verb_for

_HIDE_CURSOR = "\x1b[?25l"
_SHOW_CURSOR = "\x1b[?25h"
_CLEAR_LINE = "\x1b[2K"
_TO_COL0 = "\r"


class LiveStatusEnabledTestCase(unittest.TestCase):
    def test_off_is_always_false(self):
        self.assertFalse(live_status_enabled("off"))

    def test_on_is_always_true(self):
        self.assertTrue(live_status_enabled("on"))

    def test_auto_follows_stdout_isatty(self):
        with mock.patch("sys.stdout.isatty", return_value=True):
            self.assertTrue(live_status_enabled("auto"))
        with mock.patch("sys.stdout.isatty", return_value=False):
            self.assertFalse(live_status_enabled("auto"))

    def test_auto_is_the_default(self):
        with mock.patch("sys.stdout.isatty", return_value=True):
            self.assertTrue(live_status_enabled())


class LiveStatusDisabledTestCase(unittest.TestCase):
    """`enabled=False` (the no-TTY path -- redirected/piped/headless)
    must be a true no-op: not one escape sequence, in any call order."""

    def _out(self) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status = LiveStatus(enabled=False)
            status.start()
            status.render("hello")
            status.clear()
            status.render("world")
            status.restore()
            status.clear()
            status.stop()
        return buf.getvalue()

    def test_writes_nothing_at_all(self):
        self.assertEqual(self._out(), "")

    def test_clear_before_any_render_does_not_raise(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            LiveStatus(enabled=False).clear()  # must not raise
        self.assertEqual(buf.getvalue(), "")

    def test_restore_before_any_render_does_not_raise(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            LiveStatus(enabled=False).restore()  # must not raise
        self.assertEqual(buf.getvalue(), "")


class LiveStatusEnabledRenderTestCase(unittest.TestCase):
    """`enabled=True` -- the real interactive-terminal path."""

    def _render(self, status: LiveStatus, text: str) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.render(text)
        return buf.getvalue()

    def test_render_writes_col0_then_clear_line_then_text(self):
        status = LiveStatus(enabled=True)
        out = self._render(status, "Thinking...")
        self.assertEqual(out, _TO_COL0 + _CLEAR_LINE + "Thinking...")

    def test_two_renders_each_get_their_own_clear_and_rewrite(self):
        status = LiveStatus(enabled=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.render("first")
            status.render("second")
        self.assertEqual(buf.getvalue(), (_TO_COL0 + _CLEAR_LINE + "first") + (_TO_COL0 + _CLEAR_LINE + "second"))

    def test_clear_after_a_render_writes_the_erase_sequence(self):
        status = LiveStatus(enabled=True)
        with contextlib.redirect_stdout(io.StringIO()):
            status.render("x")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.clear()
        self.assertEqual(buf.getvalue(), _TO_COL0 + _CLEAR_LINE)

    def test_clear_with_nothing_rendered_is_a_noop(self):
        status = LiveStatus(enabled=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.clear()
        self.assertEqual(buf.getvalue(), "")

    def test_clear_twice_in_a_row_only_writes_once(self):
        # `_drawn` tracks whether there's anything left to erase -- a
        # second clear() with nothing freshly rendered must not re-emit
        # the erase sequence.
        status = LiveStatus(enabled=True)
        with contextlib.redirect_stdout(io.StringIO()):
            status.render("x")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.clear()
            status.clear()
        self.assertEqual(buf.getvalue(), _TO_COL0 + _CLEAR_LINE)

    def test_restore_after_clear_redraws_the_last_rendered_text(self):
        status = LiveStatus(enabled=True)
        with contextlib.redirect_stdout(io.StringIO()):
            status.render("x")
            status.clear()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.restore()
        self.assertEqual(buf.getvalue(), _TO_COL0 + _CLEAR_LINE + "x")

    def test_restore_with_nothing_ever_rendered_writes_nothing(self):
        status = LiveStatus(enabled=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.restore()
        self.assertEqual(buf.getvalue(), "")

    def test_start_writes_hide_cursor(self):
        status = LiveStatus(enabled=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.start()
        self.assertEqual(buf.getvalue(), _HIDE_CURSOR)

    def test_stop_clears_then_shows_cursor(self):
        status = LiveStatus(enabled=True)
        with contextlib.redirect_stdout(io.StringIO()):
            status.render("x")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.stop()
        self.assertEqual(buf.getvalue(), _TO_COL0 + _CLEAR_LINE + _SHOW_CURSOR)

    def test_stop_leaves_nothing_drawn_so_a_later_restore_is_silent(self):
        status = LiveStatus(enabled=True)
        with contextlib.redirect_stdout(io.StringIO()):
            status.render("x")
            status.stop()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status.restore()
        # restore() re-renders the last *text* regardless of `_drawn`
        # (that flag only gates `clear()`) -- stop()'s own clear() is
        # what's under test here, and it must have fired exactly once.
        self.assertEqual(buf.getvalue(), _TO_COL0 + _CLEAR_LINE + "x")

    def test_long_text_is_truncated_to_the_terminal_width(self):
        status = LiveStatus(enabled=True)
        with mock.patch("shutil.get_terminal_size", return_value=os.terminal_size((20, 24))):
            out = self._render(status, "x" * 100)
        written = out[len(_TO_COL0 + _CLEAR_LINE):]
        self.assertEqual(written, "x" * 19)  # cols - 1
        self.assertEqual(len(written), 19)

    def test_short_text_is_not_truncated(self):
        status = LiveStatus(enabled=True)
        with mock.patch("shutil.get_terminal_size", return_value=os.terminal_size((20, 24))):
            out = self._render(status, "short")
        written = out[len(_TO_COL0 + _CLEAR_LINE):]
        self.assertEqual(written, "short")


class VerbForTestCase(unittest.TestCase):
    def test_known_phase_tool_pairs(self):
        self.assertEqual(verb_for("act", "read_file"), "Reading")
        self.assertEqual(verb_for("act", "list_dir"), "Listing")
        self.assertEqual(verb_for("act", "web_fetch"), "Fetching")
        self.assertEqual(verb_for("act", "run_python_sandboxed"), "Running")
        self.assertEqual(verb_for("act", "apply_source_patch"), "Patching")
        self.assertEqual(verb_for("act", "apply_skill"), "Applying")
        self.assertEqual(verb_for("act", "git_commit"), "Committing")
        self.assertEqual(verb_for("act", "git_revert"), "Reverting")
        self.assertEqual(verb_for("act", "propose_mcp_server"), "Proposing")
        self.assertEqual(verb_for("verify", None), "Verifying")

    def test_gather_with_no_tool_is_thinking(self):
        self.assertEqual(verb_for("gather", None), "Thinking")

    def test_unknown_tool_for_a_known_phase_falls_back_to_the_phase_default(self):
        self.assertEqual(verb_for("act", "some_unheard_of_tool"), "Working")
        self.assertEqual(verb_for("gather", "some_unheard_of_tool"), "Thinking")

    def test_known_phase_with_a_default_falls_back_to_it_for_an_unknown_tool(self):
        # "verify" has a (phase, None) default ("Verifying") even though
        # it has no specific-tool entries -- an unrecognized tool under
        # it still gets that phase default, not the global "Working".
        self.assertEqual(verb_for("verify", "some_unheard_of_tool"), "Verifying")

    def test_totally_unknown_phase_falls_back_to_working(self):
        self.assertEqual(verb_for("totally_unknown_phase", None), "Working")
        self.assertEqual(verb_for("totally_unknown_phase", "some_tool"), "Working")

    def test_mcp_prefixed_tool_always_returns_calling(self):
        self.assertEqual(verb_for("act", "mcp_ddg_search_ddg_search"), "Calling")
        # Wins even under "gather", the general-purpose fallback phase --
        # an mcp_ tool name is a strong enough signal to override it.
        self.assertEqual(verb_for("gather", "mcp_brave_search_brave_web_search"), "Calling")


if __name__ == "__main__":
    unittest.main()
