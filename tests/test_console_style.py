import contextlib
import io
import time
import unittest
from unittest.mock import patch

from src.orchestrator import console_style
from src.orchestrator.console_style import (
    LiveTicker,
    VitalsMonitor,
    format_code_block,
    format_diff_block,
    render_bar,
    render_checklist,
    render_vitals,
    style,
)


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


class TestRenderChecklist(unittest.TestCase):
    def test_renders_a_label_per_item(self):
        block = render_checklist([("first", "done"), ("second", "pending")])

        self.assertIn("first", block)
        self.assertIn("second", block)

    def test_title_is_included_when_given(self):
        block = render_checklist([("a", "pending")], title="My Batch")

        self.assertIn("My Batch", block)

    def test_no_title_omits_a_title_line(self):
        block = render_checklist([("a", "pending")])

        self.assertEqual(len(block.splitlines()), 1)

    def test_each_status_gets_a_distinct_icon(self):
        block = render_checklist(
            [("a", "pending"), ("b", "in_progress"), ("c", "done"), ("d", "failed")]
        )

        icons = {"○", "◐", "✅", "❌"}
        for icon in icons:
            self.assertIn(icon, block)

    def test_unknown_status_does_not_raise(self):
        block = render_checklist([("a", "some-made-up-status")])

        self.assertIn("a", block)

    def test_empty_items_with_title_still_renders_the_title(self):
        block = render_checklist([], title="Nothing yet")

        self.assertEqual(block, "Nothing yet")


class TestFormatDiffBlock(unittest.TestCase):
    def test_empty_diff_reports_no_changes(self):
        block = format_diff_block([])

        self.assertIn("no changes", block)

    def test_content_lines_are_present(self):
        block = format_diff_block(["--- a\n", "+++ b\n", "-old line\n", "+new line\n"])

        self.assertIn("old line", block)
        self.assertIn("new line", block)

    def test_label_is_present_in_the_header(self):
        block = format_diff_block(["+x\n"], label="src/main.py")

        self.assertIn("src/main.py", block)

    def test_truncates_long_diffs_with_a_notice(self):
        lines = [f"+line {i}\n" for i in range(100)]

        block = format_diff_block(lines, max_lines=10)

        self.assertIn("90 more line(s) truncated", block)
        self.assertNotIn("line 99", block)

    def test_colors_additions_and_removals_when_enabled(self):
        with patch.object(console_style, "_ENABLED", True):
            block = format_diff_block(["+added\n", "-removed\n"])

        self.assertIn("\033[32m+added\033[0m", block)
        self.assertIn("\033[31m-removed\033[0m", block)

    def test_hunk_header_is_colored_when_enabled(self):
        with patch.object(console_style, "_ENABLED", True):
            block = format_diff_block(["@@ -1,2 +1,2 @@\n"])

        self.assertIn("\033[36m\033[1m@@ -1,2 +1,2 @@\033[0m", block)


class TestRenderBar(unittest.TestCase):
    def test_zero_is_fully_empty(self):
        bar = render_bar(0.0, width=10)

        self.assertEqual(bar.count("█"), 0)
        self.assertEqual(bar.count("░"), 10)

    def test_one_is_fully_filled(self):
        bar = render_bar(1.0, width=10)

        self.assertEqual(bar.count("█"), 10)
        self.assertEqual(bar.count("░"), 0)

    def test_half_is_half_filled(self):
        bar = render_bar(0.5, width=20)

        self.assertEqual(bar.count("█"), 10)
        self.assertEqual(bar.count("░"), 10)

    def test_out_of_range_values_are_clamped(self):
        self.assertEqual(render_bar(-5.0, width=10).count("█"), 0)
        self.assertEqual(render_bar(5.0, width=10).count("█"), 10)


class TestRenderVitals(unittest.TestCase):
    def test_includes_mood_phrase_and_bar_labels(self):
        panel = render_vitals(
            "calm, nothing much going on",
            [("Mood", 0.5), ("Energy", 0.5), ("Focus load", 0.0)],
            [("Memory records", "6"), ("Skills applied", "22")],
        )

        self.assertIn("calm, nothing much going on", panel)
        self.assertIn("Mood", panel)
        self.assertIn("Energy", panel)
        self.assertIn("Focus load", panel)
        self.assertIn("Memory records", panel)
        self.assertIn("6", panel)
        self.assertIn("22", panel)

    def test_shows_a_percentage_per_bar(self):
        panel = render_vitals("calm", [("Mood", 0.5)], [])

        self.assertIn("50%", panel)

    def test_with_no_stats_still_renders_the_bars(self):
        panel = render_vitals("calm", [("Mood", 1.0)], [])

        self.assertIn("Mood", panel)
        self.assertIn("100%", panel)


class TestVitalsMonitor(unittest.TestCase):
    def test_disabled_by_default_never_prints(self):
        monitor = VitalsMonitor(render=lambda: "PANEL", is_idle=lambda: True, interval=0.01)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            monitor.start()
            time.sleep(0.05)
            monitor.stop()

        self.assertEqual(buf.getvalue(), "")

    def test_enabled_and_idle_prints_the_panel(self):
        monitor = VitalsMonitor(render=lambda: "PANEL", is_idle=lambda: True, interval=0.01)
        monitor.enabled = True

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            monitor.start()
            time.sleep(0.05)
            monitor.stop()

        self.assertIn("PANEL", buf.getvalue())

    def test_enabled_but_not_idle_never_prints(self):
        monitor = VitalsMonitor(render=lambda: "PANEL", is_idle=lambda: False, interval=0.01)
        monitor.enabled = True

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            monitor.start()
            time.sleep(0.05)
            monitor.stop()

        self.assertEqual(buf.getvalue(), "")

    def test_starting_twice_does_not_spawn_a_second_thread(self):
        monitor = VitalsMonitor(render=lambda: "PANEL", is_idle=lambda: True, interval=5.0)

        monitor.start()
        first_thread = monitor._thread
        monitor.start()

        self.assertIs(monitor._thread, first_thread)
        monitor.stop()


class TestVitalsMonitorPinning(unittest.TestCase):
    """The genuinely riskier 'vitals pin' mode, built only after the
    creator was told the tradeoff (breaks over non-TTY output, has to
    coexist with readline) and chose it anyway. Every test here mocks
    `_terminal_size` -- the real test runner's stdout is never a TTY,
    matching production's own hard gate (pinning must be impossible
    wherever a real terminal isn't confirmed).
    """

    def test_pin_returns_false_when_not_a_real_terminal(self):
        # No mocking here on purpose: this IS the real, un-mocked
        # environment every test in this suite already runs in.
        monitor = VitalsMonitor(render=lambda: "PANEL", is_idle=lambda: True)

        self.assertFalse(monitor.pin())
        self.assertFalse(monitor.pinned)

    def test_pin_with_a_real_terminal_sets_the_scroll_region(self):
        monitor = VitalsMonitor(render=lambda: "line1\nline2", is_idle=lambda: True)

        buf = io.StringIO()
        with patch.object(console_style, "_terminal_size", return_value=(80, 24)):
            with contextlib.redirect_stdout(buf):
                result = monitor.pin()

        self.assertTrue(result)
        self.assertTrue(monitor.pinned)
        output = buf.getvalue()
        self.assertIn("\x1b[3;24r", output)  # scroll region starts after the 2-line panel
        self.assertIn("line1", output)
        self.assertIn("line2", output)

    def test_pin_never_reserves_the_whole_screen(self):
        # A panel taller than the terminal must still leave real room
        # for the actual conversation, not swallow every row.
        tall_panel = "\n".join(f"line{i}" for i in range(50))
        monitor = VitalsMonitor(render=lambda: tall_panel, is_idle=lambda: True)

        with patch.object(console_style, "_terminal_size", return_value=(80, 24)):
            with contextlib.redirect_stdout(io.StringIO()):
                monitor.pin()

        self.assertLessEqual(monitor._panel_height, 21)  # rows - 3

    def test_unpin_resets_the_scroll_region(self):
        monitor = VitalsMonitor(render=lambda: "PANEL", is_idle=lambda: True)
        with patch.object(console_style, "_terminal_size", return_value=(80, 24)):
            with contextlib.redirect_stdout(io.StringIO()):
                monitor.pin()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            monitor.unpin()

        self.assertFalse(monitor.pinned)
        self.assertIn("\x1b[r", buf.getvalue())

    def test_unpin_when_never_pinned_does_nothing(self):
        monitor = VitalsMonitor(render=lambda: "PANEL", is_idle=lambda: True)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            monitor.unpin()

        self.assertEqual(buf.getvalue(), "")

    def test_stop_also_unpins(self):
        monitor = VitalsMonitor(
            render=lambda: "PANEL", is_idle=lambda: True, pinned_interval=5.0
        )
        with patch.object(console_style, "_terminal_size", return_value=(80, 24)):
            with contextlib.redirect_stdout(io.StringIO()):
                monitor.start()
                monitor.pin()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            monitor.stop()

        self.assertFalse(monitor.pinned)
        self.assertIn("\x1b[r", buf.getvalue())

    def test_pinned_and_idle_redraws_in_place(self):
        monitor = VitalsMonitor(
            render=lambda: "PANEL", is_idle=lambda: True, pinned_interval=0.01
        )

        buf = io.StringIO()
        with patch.object(console_style, "_terminal_size", return_value=(80, 24)):
            with contextlib.redirect_stdout(buf):
                monitor.pin()
                monitor.start()
                time.sleep(0.05)
                monitor.stop()

        # More than one draw happened: the initial pin() draw, plus at
        # least one redraw from the loop.
        self.assertGreater(buf.getvalue().count("PANEL"), 1)

    def test_pinned_but_not_idle_never_redraws_after_the_initial_draw(self):
        monitor = VitalsMonitor(
            render=lambda: "PANEL", is_idle=lambda: False, pinned_interval=0.01
        )

        with patch.object(console_style, "_terminal_size", return_value=(80, 24)):
            with contextlib.redirect_stdout(io.StringIO()):
                monitor.pin()  # the initial draw always happens

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                monitor.start()
                time.sleep(0.05)
                monitor.stop()

        self.assertNotIn("PANEL", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
