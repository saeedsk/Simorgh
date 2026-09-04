import unittest
from unittest.mock import patch

from src.orchestrator import console_style
from src.orchestrator.console_style import format_code_block, style


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


if __name__ == "__main__":
    unittest.main()
