import contextlib
import io
import time
import unittest
from unittest.mock import patch

from src.orchestrator import console_style
from src.orchestrator.console_style import LiveTicker, format_code_block, style


class TestStyleDisabled(unittest.TestCase):
    """The test runner's stdout is never a real terminal, so _ENABLED is
    False here exactly like it would be for piped output or NO_COLOR --
    this is the "color skipped" contract every caller relies on.
    """

    def test_returns_text_unchanged_when_disabled(self):
        with patch.object(console_style, "_ENABLED", False):
            self.assertEqual(style("hello", "red", "bold"), "hello")

    def test_returns_text_unchanged_with_no_names(self):
        self.assertEqual(style("hello"), "hello")


class TestStyleEnabled(unittest.TestCase):
    def test_wraps_with_the_named_code_and_resets(self):
        with patch.object(console_style, "_ENABLED", True):
            result = style("hello", "red")

        self.assertEqual(result, "\033[31mhello\033[0m")

    def test_multiple_names_stack_in_order(self):
        with patch.object(console_style, "_ENABLED", True):
            result = style("hello", "red", "bold")

        self.assertEqual(result, "\033[31m\033[1mhello\033[0m")

    def test_unknown_name_is_silently_ignored(self):
        with patch.object(console_style, "_ENABLED", True):
            result = style("hello", "not-a-real-color")

        self.assertEqual(result, "hello\033[0m")

    def test_no_names_returns_unchanged_even_when_enabled(self):
        with patch.object(console_style, "_ENABLED", True):
            result = style("hello")

        self.assertEqual(result, "hello")

    def test_orange_has_a_256_color_escape(self):
        with patch.object(console_style, "_ENABLED", True):
            result = style("warn", "orange")

        self.assertIn("\033[38;5;208m", result)


class TestFormatCodeBlockDisabled(unittest.TestCase):
    def test_content_is_present(self):
        block = format_code_block("x = 1\ny = 2")

        self.assertIn("x = 1", block)
        self.assertIn("y = 2", block)

    def test_label_is_present_in_the_header(self):
        block = format_code_block("x = 1", label="my_skill")

        self.assertIn("my_skill", block)

    def test_empty_code_still_renders_one_line(self):
        block = format_code_block("")

        lines = block.splitlines()
        # header + one (blank) content line + footer, no truncation notice
        self.assertEqual(len(lines), 3)

    def test_none_like_falsy_code_does_not_crash(self):
        block = format_code_block("")  # closest a caller can pass to "no code"

        self.assertIsInstance(block, str)

    def test_truncates_long_line_count_with_a_notice(self):
        code = "\n".join(f"line {i}" for i in range(50))

        block = format_code_block(code, max_lines=10)

        self.assertIn("40 more line(s) truncated", block)
        self.assertNotIn("line 49", block)
        self.assertIn("line 9", block)

    def test_does_not_truncate_when_within_max_lines(self):
        code = "\n".join(f"line {i}" for i in range(5))

        block = format_code_block(code, max_lines=10)

        self.assertNotIn("truncated", block)

    def test_truncates_long_single_line_with_a_char_count(self):
        code = "x" * 500

        block = format_code_block(code, max_line_chars=100)

        self.assertIn("+400", block)

    def test_does_not_truncate_short_lines(self):
        block = format_code_block("short line", max_line_chars=100)

        self.assertNotIn("+", block)


class TestFormatCodeBlockEnabled(unittest.TestCase):
    def test_python_keyword_is_highlighted(self):
        with patch.object(console_style, "_ENABLED", True):
            block = format_code_block("def run():\n    return 1")

        self.assertIn("\033[35m\033[1mdef\033[0m", block)
        self.assertIn("\033[35m\033[1mreturn\033[0m", block)

    def test_trailing_comment_is_dimmed(self):
        with patch.object(console_style, "_ENABLED", True):
            block = format_code_block("x = 1  # a comment")

        self.assertIn("\033[2m# a comment\033[0m", block)

    def test_hash_inside_a_string_is_still_treated_as_a_comment_start(self):
        # Documented, known limitation (see _highlight_python_line's
        # docstring): this is a regex approximation, not a real Python
        # tokenizer, so a '#' inside a string literal is mis-highlighted
        # as if it started a comment. Locking in the current, understood
        # behavior rather than a stronger guarantee this module doesn't
        # actually make.
        with patch.object(console_style, "_ENABLED", True):
            block = format_code_block('x = "a # b"')

        self.assertIn('"a ', block)
        self.assertIn("\033[2m# b\"\033[0m", block)


class TestLiveTicker(unittest.TestCase):
    def test_does_not_block_entering_the_context(self):
        start = time.monotonic()
        with LiveTicker("waiting", interval=5.0):
            pass
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, 1.0)

    def test_wraps_a_slow_block_without_raising(self):
        with LiveTicker("waiting", interval=5.0):
            time.sleep(0.01)  # the "slow" call this wraps

        # No assertion beyond "didn't raise" -- the point is the ticker
        # never gets in the way of the wrapped code succeeding.

    def test_ticks_at_least_once_for_a_block_longer_than_the_interval(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with LiveTicker("running something", interval=0.02):
                time.sleep(0.1)

        output = buf.getvalue()
        self.assertIn("running something", output)
        self.assertIn("elapsed", output)

    def test_no_tick_printed_for_a_block_shorter_than_the_interval(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with LiveTicker("quick", interval=5.0):
                pass

        self.assertEqual(buf.getvalue(), "")

    def test_thread_is_joined_before_the_context_exits(self):
        ticker = LiveTicker("waiting", interval=0.01)
        with ticker:
            time.sleep(0.03)

        self.assertFalse(ticker._thread.is_alive())

    def test_a_slow_wrapped_call_that_raises_still_stops_the_ticker(self):
        ticker = LiveTicker("waiting", interval=0.01)
        with self.assertRaises(ValueError):
            with ticker:
                time.sleep(0.03)
                raise ValueError("boom")

        self.assertFalse(ticker._thread.is_alive())

    def test_elapsed_time_uses_the_injected_clock(self):
        fake_time = [0.0]

        def fake_clock():
            return fake_time[0]

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with LiveTicker("waiting", interval=0.01, clock=fake_clock):
                fake_time[0] = 42.0
                time.sleep(0.03)

        self.assertIn("42s elapsed", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
