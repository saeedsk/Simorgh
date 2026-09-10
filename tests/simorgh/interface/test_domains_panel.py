"""`render.domains_panel`: the layout, tested without a Ledger.

The first version of this command printed a flat list with a cryptic
`[--]` marker, a run-on status line that repeated its own missing list,
and no wrapping -- so on a fresh install six near-identical rows ran off
the right of the screen and the one row that was actually ready was the
hardest to find."""

from __future__ import annotations

import unittest

from simorgh.interface.render import display_width, domains_panel

READY = {"name": "security", "blurb": "this machine's own exposure", "state": "ready",
         "detail": "nothing checked yet", "fix": "tool sec_self"}
TODO = {"name": "knowledge", "blurb": "your own documents", "state": "todo",
        "detail": "no documents indexed yet", "fix": "tool kb_sources add ..."}
BROKEN = {"name": "pim", "blurb": "calendar and mail", "state": "broken",
          "detail": "the server refused these credentials",
          "fix": "simorgh vault add imap:fastmail"}


def _panel(rows, **kwargs) -> str:
    kwargs.setdefault("width", 88)
    kwargs.setdefault("enabled", False)
    return domains_panel(rows, **kwargs)


class GroupingTestCase(unittest.TestCase):
    def test_rows_are_grouped_under_a_heading(self):
        panel = _panel([READY, TODO, BROKEN])
        for heading in ("not working", "ready", "to set up"):
            self.assertIn(heading, panel)

    def test_what_is_broken_comes_first(self):
        """It is the only group that needs acting on today."""
        panel = _panel([READY, TODO, BROKEN])
        self.assertLess(panel.index("not working"), panel.index("ready"))
        self.assertLess(panel.index("ready"), panel.index("to set up"))

    def test_an_empty_group_is_not_printed(self):
        panel = _panel([READY])
        self.assertNotIn("not working", panel)
        self.assertNotIn("to set up", panel)

    def test_the_summary_counts_each_group(self):
        panel = _panel([READY, TODO, BROKEN])
        self.assertIn("1 not working", panel)
        self.assertIn("1 ready", panel)
        self.assertIn("1 to set up", panel)

    def test_a_domain_to_set_up_shows_only_what_to_do(self):
        """"no documents indexed yet" under a heading that already says
        "to set up" is the same sentence twice."""
        panel = _panel([TODO])
        self.assertIn("tool kb_sources add", panel)
        self.assertNotIn("no documents indexed yet", panel)

    def test_a_broken_domain_shows_both_what_is_wrong_and_what_to_do(self):
        panel = _panel([BROKEN])
        self.assertIn("refused these credentials", panel)
        self.assertIn("simorgh vault add", panel)

    def test_a_ready_domain_shows_its_detail(self):
        self.assertIn("nothing checked yet", _panel([READY]))


class LayoutTestCase(unittest.TestCase):
    LONG = {"name": "home", "blurb": "the house", "state": "broken",
            "detail": "Home Assistant answered 500 and kept answering 500 for the whole "
                      "of the retry window, which usually means the integration behind it "
                      "has thrown during setup",
            "fix": "check the Home Assistant logs, then restart it and try again"}

    def test_nothing_runs_past_the_given_width(self):
        for line in _panel([self.LONG, READY, TODO], width=70).splitlines():
            self.assertLessEqual(display_width(line), 70, line)

    def test_a_narrow_terminal_still_produces_readable_lines(self):
        panel = _panel([self.LONG], width=40)
        for line in panel.splitlines():
            self.assertLessEqual(display_width(line), 40, line)
        self.assertIn("Home Assistant", panel)

    def test_wrapped_lines_line_up_under_the_blurb(self):
        lines = _panel([self.LONG], width=70).splitlines()
        header = next(line for line in lines if "the house" in line)
        wrapped = next(line for line in lines if "Home Assistant answered" in line)
        self.assertEqual(len(wrapped) - len(wrapped.lstrip()),
                         header.index("the house"))

    def test_names_of_different_lengths_are_aligned(self):
        rows = [dict(READY, name="a"), dict(READY, name="a-much-longer-name")]
        blurb_columns = {line.index(READY["blurb"]) for line in _panel(rows).splitlines()
                         if READY["blurb"] in line}
        self.assertEqual(len(blurb_columns), 1)


class GlyphTestCase(unittest.TestCase):
    def test_three_states_get_three_different_marks(self):
        """"Nothing set up yet" and "set up and not answering" are
        different facts."""
        panel = _panel([READY, TODO, BROKEN])
        marks = {line.strip()[0] for line in panel.splitlines()
                 if line.startswith("  ") and any(
                     row["name"] in line for row in (READY, TODO, BROKEN))}
        self.assertEqual(len(marks), 3, marks)

    def test_an_ascii_terminal_gets_ascii_marks(self):
        panel = _panel([READY, TODO, BROKEN], unicode="off")
        self.assertIn("[+]", panel)
        self.assertIn("[ ]", panel)
        self.assertIn("[x]", panel)
        self.assertIn("->", panel)
        self.assertNotIn("→", panel)

    def test_ascii_marks_are_still_aligned(self):
        lines = _panel([READY, TODO, BROKEN], unicode="off").splitlines()
        columns = {line.index(row["blurb"]) for line in lines
                   for row in (READY, TODO, BROKEN) if row["blurb"] in line}
        self.assertEqual(len(columns), 1)

    def test_colour_is_off_when_asked(self):
        self.assertNotIn("\x1b[", _panel([READY, TODO, BROKEN]))

    def test_colour_is_on_when_asked(self):
        self.assertIn("\x1b[", _panel([READY], enabled=True))


class EdgeCaseTestCase(unittest.TestCase):
    def test_no_rows_at_all_does_not_crash(self):
        self.assertIsInstance(_panel([]), str)

    def test_a_row_with_no_fix_or_detail_still_prints_its_name(self):
        panel = _panel([{"name": "energy", "blurb": "what it costs", "state": "ready"}])
        self.assertIn("energy", panel)
        self.assertIn("what it costs", panel)

    def test_no_trailing_whitespace_on_any_line(self):
        for line in _panel([READY, TODO, BROKEN]).splitlines():
            self.assertEqual(line, line.rstrip(), repr(line))
