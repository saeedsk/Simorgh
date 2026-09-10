"""`render.status_panel`: the whole of `status`, on one screen.

The first version printed one line per subsystem, an ASCII bar, and
every registered tool name in one comma-run. On a real machine that is
sixteen near-identical "ok" lines burying the one saying "degraded",
followed by fifty names nobody reads. A status panel is read at a
glance or not at all."""

from __future__ import annotations

import unittest

from simorgh.interface.render import display_width, meter, status_panel
from simorgh.interface.vitals import VitalsSnapshot

NAMES = ("bus", "ledger", "cognition", "memory", "guardian", "execution", "learning",
         "reflection", "persona", "interface", "orchestration")


def _health(degraded=("learning",), down=()) -> dict:
    return {
        "state": "running", "mode": "single", "uptime_seconds": 949.5,
        "subsystems": [
            {"name": name,
             "status": "down" if name in down else ("degraded" if name in degraded else "ok"),
             "detail": "embedder fell back to hashing" if name in degraded else ""}
            for name in NAMES],
    }


def _snapshot(**overrides) -> VitalsSnapshot:
    base = dict(mood=0.16, energy=0.0, load=0.0, memory_records=9, skills=0, interests=3,
                backlog=2, posture="guarded", workers_busy=0, workers_total=1,
                bus_published=1357, bus_delivered=582, mood_phrase="content, at ease",
                stale=False,
                budget={"together": {"calls": 27, "max_calls": 1500},
                        "gemini": {"calls": 0, "max_calls": 1500}})
    base.update(overrides)
    return VitalsSnapshot(**base)


GIT = {"available": True, "branch": "main", "head": "aa11f2e9abcdef", "dirty": True,
       "changed_files": 3,
       "recent_commits": ["aa11f2e Make `domains` readable: group it, wrap it, and stop "
                          "repeating itself", "5dd37ce Let a chat turn actually make it"]}


def _panel(**overrides) -> str:
    kwargs = dict(health=_health(), snapshot=_snapshot(),
                  posture={"mode": "guarded", "trust_score": 1.0},
                  tools=[{"name": f"t{n}"} for n in range(50)], git=GIT,
                  width=88, enabled=False)
    kwargs.update(overrides)
    return status_panel(**kwargs)


class MeterTestCase(unittest.TestCase):
    def test_a_full_value_fills_the_bar(self):
        self.assertEqual(meter(1.0, width=4), "████")

    def test_the_floor_is_empty(self):
        self.assertEqual(meter(-1.0, width=4), "░░░░")

    def test_a_tiny_non_zero_value_still_shows_something(self):
        """27 calls out of 1500 rounds to nothing, and an empty bar
        beside a non-zero number reads as a broken bar, not a small
        one."""
        self.assertTrue(meter(27 / 1500, lo=0.0, hi=1.0, width=10).startswith("█"))

    def test_exactly_zero_stays_empty(self):
        self.assertEqual(meter(0.0, lo=0.0, hi=1.0, width=4), "░░░░")

    def test_ascii_mode_uses_ascii(self):
        bar = meter(0.5, lo=0.0, hi=1.0, width=4, unicode=False)
        self.assertEqual(bar, "##--")

    def test_every_bar_is_the_width_asked_for(self):
        for value in (-1.0, -0.3, 0.0, 0.42, 1.0):
            self.assertEqual(display_width(meter(value, width=10)), 10)


class SubsystemStripTestCase(unittest.TestCase):
    def test_every_subsystem_gets_a_glyph(self):
        strip_line = next(line for line in _panel().splitlines() if "subsystems" in line)
        self.assertEqual(sum(strip_line.count(g) for g in "●◐✕"), len(NAMES))

    def test_healthy_subsystems_are_not_named(self):
        """Fifteen lines saying "ok" is fifteen lines hiding the one
        that does not."""
        panel = _panel()
        self.assertNotIn("cognition", panel)
        self.assertNotIn("orchestration", panel)

    def test_an_unhealthy_subsystem_is_named_with_its_reason(self):
        panel = _panel()
        self.assertIn("learning", panel)
        self.assertIn("embedder fell back", panel)

    def test_the_counts_are_summarised(self):
        panel = _panel()
        self.assertIn(f"{len(NAMES) - 1} ok", panel)
        self.assertIn("1 degraded", panel)

    def test_states_are_told_apart_by_shape_not_only_colour(self):
        """So the panel still works with no colour, and for anyone who
        cannot tell green from amber."""
        panel = _panel(health=_health(degraded=("learning",), down=("memory",)), enabled=False)
        strip = next(line for line in panel.splitlines() if "subsystems" in line)
        self.assertEqual(len({c for c in strip if c in "●◐✕"}), 3)

    def test_no_kernel_answer_says_so_rather_than_showing_nothing(self):
        self.assertIn("no answer from the Kernel", _panel(health=None))


class LayoutTestCase(unittest.TestCase):
    def test_nothing_runs_past_the_width(self):
        for line in _panel(width=80).splitlines():
            self.assertLessEqual(display_width(line), 80, line)

    def test_a_narrow_terminal_drops_to_one_column(self):
        """A second column that wraps is worse than no second column."""
        panel = _panel(width=60)
        for line in panel.splitlines():
            self.assertLessEqual(display_width(line), 60, line)
        self.assertIn("memory", panel)
        self.assertIn("guardian", panel)

    def test_the_two_columns_do_not_touch(self):
        """"1357 sent - 582 delivered" used to run flush into the word
        beside it, with no gap at all."""
        for line in _panel(width=88).splitlines():
            if "delivered" in line and "interests" in line:
                self.assertIn("   ", line[line.index("delivered"):])

    def test_the_header_carries_state_mode_and_uptime(self):
        header = _panel().splitlines()[0]
        for piece in ("running", "single", "up 15m"):
            self.assertIn(piece, header)

    def test_no_trailing_whitespace_anywhere(self):
        for line in _panel().splitlines():
            self.assertEqual(line, line.rstrip(), repr(line))


class ContentTestCase(unittest.TestCase):
    def test_tools_are_counted_not_listed(self):
        """The list was the longest thing on the screen and the least
        read."""
        panel = _panel()
        self.assertIn("50 registered", panel)
        self.assertNotIn("t17", panel)

    def test_it_says_where_to_see_the_tools(self):
        self.assertIn("`tool` lists them", _panel())

    def test_load_has_no_sign_but_mood_does(self):
        """Mood runs -1..+1 and the sign is the point; load runs 0..1
        and a `+` in front of it is noise."""
        panel = _panel(snapshot=_snapshot(mood=0.16, load=0.4))
        self.assertIn("+0.16", panel)
        self.assertNotIn("+0.40", panel)
        self.assertIn("0.40", panel)

    def test_budgets_are_bars_sorted_by_use(self):
        panel = _panel()
        self.assertLess(panel.index("together"), panel.index("gemini"))

    def test_an_exhausted_budget_is_called_out(self):
        panel = _panel(snapshot=_snapshot(
            budget={"gemini": {"calls": 1500, "max_calls": 1500, "exhausted": True}}))
        self.assertIn("exhausted", panel)

    def test_a_dirty_tree_says_how_many_files(self):
        self.assertIn("3 uncommitted", _panel())

    def test_a_clean_tree_says_clean(self):
        self.assertIn("clean", _panel(git={**GIT, "dirty": False, "changed_files": 0}))

    def test_commit_subjects_are_cut_to_fit_rather_than_wrapping(self):
        lines = [line for line in _panel(width=70).splitlines() if "aa11f2e Make" in line]
        self.assertTrue(lines)
        self.assertLessEqual(display_width(lines[0]), 70)

    def test_no_repository_says_so(self):
        self.assertIn("no repository here", _panel(git={"available": False}))

    def test_stale_vitals_are_simply_absent_rather_than_shown_as_zero(self):
        """Zeroes for a system that has not reported yet would be a
        panel confidently stating something it does not know."""
        panel = _panel(snapshot=VitalsSnapshot())
        self.assertNotIn("mood", panel)
        self.assertIn("running", panel)

    def test_a_missing_piece_does_not_take_the_panel_with_it(self):
        panel = _panel(posture=None, tools=None, git=None)
        self.assertIn("running", panel)
        self.assertIn("subsystems", panel)


class AsciiTestCase(unittest.TestCase):
    def test_an_ascii_terminal_gets_ascii_throughout(self):
        panel = _panel(unicode="off")
        for glyph in ("●", "◐", "✕", "█", "░", "─"):
            self.assertNotIn(glyph, panel)

    def test_ascii_states_are_still_told_apart(self):
        panel = _panel(health=_health(degraded=("learning",), down=("memory",)), unicode="off")
        strip = next(line for line in panel.splitlines() if "subsystems" in line)
        self.assertEqual(len({c for c in strip if c in "o~x"}), 3)
