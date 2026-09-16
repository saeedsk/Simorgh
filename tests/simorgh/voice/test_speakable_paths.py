"""What `speakable` hands to a synthesiser: paths off the tongue, but
not everything with a slash in it (voice/planner.py)."""

from __future__ import annotations

import unittest

from simorgh.voice.planner import speakable


class PathsAreForTheScreen(unittest.TestCase):
    def test_a_real_path_is_not_read_aloud(self):
        spoken, omitted = speakable("it is in simorgh_skills/hot_stocks.py now")
        self.assertIn("a file path that's on screen", spoken)
        self.assertIn("path", omitted)

    def test_a_docs_path_too(self):
        spoken, _ = speakable("check docs/plans/agent-skills-design.md")
        self.assertIn("a file path that's on screen", spoken)

    def test_a_list_of_time_windows_is_not_a_path(self):
        """Live 2026-09-15: "ranks movers over 5m/15m/30m/1h/2h windows"
        was spoken as "ranks movers over a file path that's on screen
        windows". Two or more slash-separated word runs is what a path
        looks like -- and what a list of durations looks like."""
        spoken, omitted = speakable("ranks movers over 5m/15m/30m/1h/2h windows")
        self.assertNotIn("file path", spoken)
        self.assertNotIn("path", omitted)
        self.assertIn("5m", spoken)

    def test_a_shorter_window_list_too(self):
        spoken, _ = speakable("compare 24h/7d")
        self.assertNotIn("file path", spoken)


if __name__ == "__main__":
    unittest.main()
