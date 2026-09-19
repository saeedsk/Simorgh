"""Every bottom-of-screen row fits the terminal (2026-09-19: a running row
was 10-15 columns too wide, wrapped, and every redraw left a trail)."""

import unittest
from unittest import mock

from simorgh.interface import panel
from simorgh.interface.activity import TaskBook
from simorgh.interface.render import display_width


class LiveRowsNeverWrap(unittest.TestCase):
    def test_a_long_running_task_row_fits(self):
        book = TaskBook()
        topic = "How many studio albums were published by Mercedes Sosa between 2000 and 2009 (included)? " * 3
        book.on_created({"task_id": "t1", "kind": "research", "description": topic, "origin": "benchmark"})
        book.on_started("t1", now=0.0)
        for width in (60, 100, 160):
            with mock.patch("simorgh.interface.render.terminal_width", return_value=width):
                rows = panel.live_rows(book, now=13.0) + panel.footer_rows(book, now=13.0, auto="on")
                text = "".join(t for _, t in panel.flatten(rows))
            for line in text.split("\n"):
                self.assertLess(display_width(line), width, (width, line))

    def test_a_wide_glyph_counts_as_two(self):
        row = [("", "🔍" * 30)]
        self.assertLessEqual(display_width("".join(t for _, t in panel.fit_row(row, 21))), 21)
