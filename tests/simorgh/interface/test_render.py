import re
import unittest

from simorgh.interface import render
from simorgh.interface.vitals import VitalsSnapshot

_ESC = re.compile(r"\x1b\[[^m]*")


class RenderTestCase(unittest.TestCase):
    def test_no_color_env_disables_color(self):
        import os

        old = os.environ.get("NO_COLOR")
        os.environ["NO_COLOR"] = "1"
        try:
            self.assertFalse(render.color_enabled("auto"))
        finally:
            if old is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = old

    def test_style_off_returns_plain_text(self):
        self.assertEqual(render.style("hi", "red", enabled=False), "hi")

    def test_style_on_wraps_in_sgr(self):
        out = render.style("hi", "red", enabled=True)
        self.assertIn("hi", out)
        self.assertTrue(out.startswith("\x1b[31m"))

    def test_never_emits_cursor_control_sequences(self):
        """Milestone 94: every escape sequence this module can emit must
        be a plain SGR color code (`\\x1b[<digits>m`), never a
        cursor-movement/erase/scroll-region sequence."""
        text = render.notice("info", "hello", "src", enabled=True)
        text += render.checklist([("done", "a"), ("doing", "b")], title="t")
        text += render.vitals(VitalsSnapshot(mood=0.2, energy=0.1, load=0.3, stale=False))
        text += render.diff_block(["+added", "-removed", " same"], enabled=True)
        text += render.banner(enabled=True)
        for match in _ESC.finditer(text):
            self.assertTrue(match.group(0).lstrip("\x1b[").isdigit() or match.group(0) == "\x1b[",
                             f"non-SGR escape sequence found: {match.group(0)!r}")

    def test_vitals_honestly_reports_no_data_yet(self):
        self.assertIn("no data", render.vitals(VitalsSnapshot()))

    def test_vitals_renders_real_snapshot(self):
        snap = VitalsSnapshot(mood=0.5, energy=0.2, load=0.1, memory_records=3, stale=False)
        out = render.vitals(snap)
        self.assertIn("mood", out)
        self.assertIn("3", out)

    def test_banner_names_the_system_and_a_real_command(self):
        out = render.banner(enabled=False)
        self.assertIn("SIMORGH", out)
        self.assertIn("سیمرغ", out)
        self.assertIn("status", out)  # a real, always-working command
        self.assertIn("propose <topic>", out)

    def test_banner_disabled_color_has_no_escape_sequences(self):
        out = render.banner(enabled=False)
        self.assertNotIn("\x1b[", out)

    def test_banner_every_line_fits_a_normal_terminal_width(self):
        # No wide-terminal assumption -- a redirected/piped session (this
        # trial's own earlier mistake: buffered, hard to eyeball) still
        # gets something readable in a standard 80-column window.
        for line in render.banner(enabled=False).splitlines():
            self.assertLessEqual(len(line), 80, repr(line))


if __name__ == "__main__":
    unittest.main()
