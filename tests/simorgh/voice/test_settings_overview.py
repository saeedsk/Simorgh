"""`voice set` with no argument shows the settings and their values.

The creator, 2026-09-16, looking at what it printed: "make this visually
pleasant", and then plainly: "when i run `voice set` sim should show
options including their current value in a pleasant and organize
format".

What it printed was one line of thirty-eight semicolons -- every key,
its type, and nothing else. The information to do better was already
there and thrown away: `VOICE_SAFE_KEYS` carries a type, the allowed
range or choices, AND a one-line description for every key, and the
running config carries what each is set to. `describe()` discarded the
help text at the call site (`for k, t, _h in ...`).

The guard that matters most here is the last test. `GROUPS` is a
hand-written list, and a hand-written list that silently loses an entry
is the drift this codebase keeps being bitten by -- a settings screen
that hides a setting is worse than an ugly one that shows it. A new key
in `VOICE_SAFE_KEYS` falls into "Other" rather than disappearing.
"""

from __future__ import annotations

import unittest

from simorgh.contracts.settings import VOICE_SAFE_KEYS
from simorgh.voice import settings
from simorgh.voice.config import Config


class OverviewTestCase(unittest.TestCase):
    def setUp(self):
        self.config = Config()
        self.text = settings.overview(self.config, width=100)

    def test_every_settable_key_is_shown(self):
        """The drift guard: nothing in VOICE_SAFE_KEYS may be missing."""
        missing = [k for k in VOICE_SAFE_KEYS if k not in self.text]
        self.assertEqual(missing, [], f"settings a person cannot see: {missing}")

    def test_a_key_in_no_group_still_appears(self):
        """A key added later, before anyone updates GROUPS."""
        grouped = {k for _t, keys in settings.GROUPS for k in keys}
        ungrouped = [k for k in VOICE_SAFE_KEYS if k not in grouped]
        for key in ungrouped:
            self.assertIn(key, self.text)

    def test_current_values_are_shown(self):
        """The creator's actual ask: not just the options, the values."""
        config = settings.apply(self.config, "tts", "miso")
        config = settings.apply(config, "tts_speed", 1.4)
        text = settings.overview(config, width=100)
        self.assertRegex(text, r"tts\s+miso")
        self.assertRegex(text, r"tts_speed\s+1\.4")

    def test_a_bool_reads_as_on_or_off_not_true_or_false(self):
        text = settings.overview(settings.apply(self.config, "barge_in", False), width=100)
        self.assertRegex(text, r"barge_in\s+off")
        self.assertNotIn("False", text)

    def test_an_empty_value_is_a_dash_not_a_blank(self):
        """An empty column reads as a broken row."""
        self.assertRegex(settings.overview(self.config, width=100), r"miso_reference\s+-")

    def test_the_groups_have_headings(self):
        for title, _keys in settings.GROUPS:
            self.assertIn(title, self.text)

    def test_rows_sit_under_their_heading(self):
        """A heading indented like its rows is not a heading."""
        for line in self.text.splitlines():
            if line.strip() in {t for t, _k in settings.GROUPS}:
                self.assertTrue(line.startswith("  ") and not line.startswith("    "))

    def test_a_hint_is_shown_whole_or_not_at_all(self):
        """Half a hint -- `[on |` -- reads as a broken screen."""
        for width in (48, 60, 80, 100, 120):
            for line in settings.overview(self.config, width=width).splitlines():
                if "[" in line:
                    self.assertIn("]", line, f"hint cut mid-token at width {width}: {line!r}")

    def test_it_fits_the_terminal_it_is_given(self):
        for width in (60, 80, 100, 120):
            for line in settings.overview(self.config, width=width).splitlines():
                self.assertLessEqual(len(line), width, f"line overruns width {width}: {line!r}")

    def test_a_very_narrow_terminal_still_lists_the_keys(self):
        text = settings.overview(self.config, width=40)
        for key in ("tts", "barge_in", "volume"):
            self.assertIn(key, text)

    def test_it_says_how_to_change_one(self):
        self.assertIn("voice set", self.text)


if __name__ == "__main__":
    unittest.main()
