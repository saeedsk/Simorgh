"""No rendered line may overrun the terminal.

The assertion that was missing. Seven overruns survived 2,865 passing
tests because nothing anywhere compared a finished line against
`terminal_width()` -- the code measured guessed overheads instead, and
counted an emoji as one column when it occupies two (observer round,
2026-09-08). This file measures the finished line, in display columns,
at every width the renderer supports.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from simorgh.interface import panel
from simorgh.interface.activity import TaskBook, TaskRecord, finished_line, footer, started_line, step_line
from simorgh.interface.render import display_width, fit, terminal_width

WIDTHS = (60, 80, 100, 120, 200)
LONG = ("add a module-level constant DEFAULT_HISTORY_LIMIT = 200 near the top of "
        "simorgh/interface/parser.py, above the COMMAND_NAMES tuple, with a comment")


def _at(columns: int):
    return mock.patch("shutil.get_terminal_size", return_value=os.terminal_size((columns, 24)))


def _book(n: int = 1, running: int = 1) -> TaskBook:
    book = TaskBook()
    for i in range(n):
        book.on_created({"task_id": f"t{i}", "kind": "patch", "origin": "human", "description": LONG})
        if i < running:
            book.on_started(f"t{i}", now=0.0)
    return book


class DisplayWidthTestCase(unittest.TestCase):
    def test_an_emoji_is_two_columns(self):
        self.assertEqual(display_width("ab"), 2)
        self.assertEqual(display_width("🔧"), 2)
        self.assertEqual(display_width("🔧ab"), 4)

    def test_fit_never_exceeds_the_width_asked_for(self):
        for text in ("short", LONG, "🔧🔧🔧" + LONG):
            for width in (5, 20, 60, 200):
                self.assertLessEqual(display_width(fit(text, width)), width, (text[:20], width))

    def test_fit_leaves_short_text_alone(self):
        self.assertEqual(fit("hello", 40), "hello")


class NarrationFitsTestCase(unittest.TestCase):
    """Every scrolling line the feed emits."""

    def _lines(self, record: TaskRecord):
        return {
            "started_line": started_line(record),
            "step_line": step_line(record, tool="apply_source_patch", summary=LONG, ok=True),
            "step_line ascii": step_line(record, tool="run_tests", summary=LONG, ok=False, unicode=False),
            "finished_line": finished_line(record, elapsed=61.0, detail=LONG),
            "footer": footer(_book(3, running=1), now=12.0),
        }

    def test_no_narration_line_overruns_any_width(self):
        for width in WIDTHS:
            with _at(width):
                record = _book().get("t0")
                for name, line in self._lines(record).items():
                    self.assertLessEqual(display_width(line), width, f"{name} at {width}: {line!r}")

    def test_a_wide_terminal_is_actually_used(self):
        record = _book().get("t0")
        with _at(80):
            narrow = display_width(started_line(record))
        with _at(160):
            wide = display_width(started_line(record))
        self.assertGreater(wide, narrow)


class PanelFitsTestCase(unittest.TestCase):
    """The bottom panel and the transcript tree."""

    def test_no_panel_row_overruns_any_width(self):
        for width in WIDTHS:
            with _at(width):
                for running in (0, 1, 3, 5):
                    rows = panel.footer_rows(_book(6, running=running), now=12.0, auto="on",
                                             posture="guarded", model="zai-org/GLM-5.3-Flash",
                                             budget="together 12/200", hint="Ctrl-C cancels")
                    for row in rows:
                        line = "".join(text for _style, text in row)
                        self.assertLessEqual(display_width(line), width, f"{running} running at {width}: {line!r}")

    def test_no_tree_line_overruns_any_width(self):
        for width in WIDTHS:
            with _at(width):
                record = _book().get("t0")
                record.status = "completed"
                lines = [
                    panel.tree_start(record),
                    panel.tree_step(tool="apply_source_patch", head=LONG, ok=True, took=1.2),
                    panel.tree_step(tool="run_tests", head=LONG, ok=False, took=142.0, unicode=False),
                    panel.tree_end(record, elapsed=61.0, detail=LONG),
                    *panel.tree_note(["+" + LONG, "-" + LONG]),
                ]
                for line in lines:
                    self.assertLessEqual(display_width(line), width, f"{width}: {line!r}")

    def test_the_tree_rail_survives_a_long_diff_line(self):
        with _at(60):
            [noted] = panel.tree_note(["+" + LONG])
        self.assertTrue(noted.startswith("    ⎿  ") or noted.startswith("       "))
        self.assertLessEqual(display_width(noted), 60)


class BoundsTestCase(unittest.TestCase):
    def test_the_width_is_bounded_at_both_ends(self):
        with _at(10):
            self.assertGreaterEqual(terminal_width(), 60)
        with _at(1000):
            self.assertLessEqual(terminal_width(), 200)

    def test_an_unmeasurable_terminal_still_renders(self):
        with mock.patch("shutil.get_terminal_size", side_effect=OSError):
            self.assertGreaterEqual(terminal_width(), 60)


if __name__ == "__main__":
    unittest.main()
