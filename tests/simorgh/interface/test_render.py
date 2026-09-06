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

    def test_vitals_never_prints_a_raw_dict(self):
        # Live-caught: the old `budget: {...}` line dumped every subsystem's
        # raw metrics payload -- nested braces across the whole terminal
        # width in a panel meant to read at a glance.
        snap = VitalsSnapshot(
            stale=False, workers_busy=1, workers_total=1, bus_published=18, bus_delivered=6,
            budget={"claude_code_cli": {"calls": 8, "max_calls": 500, "exhausted": False}},
        )
        out = render.vitals(snap)
        self.assertNotIn("{", out)
        self.assertNotIn("}", out)

    def test_vitals_renders_a_provider_budget_line(self):
        snap = VitalsSnapshot(
            stale=False,
            budget={"claude_code_cli": {"calls": 8, "max_calls": 500, "exhausted": False},
                    "gemini": {"calls": 3, "max_calls": None, "exhausted": True}},
        )
        out = render.vitals(snap)
        self.assertIn("budget: claude_code_cli 8/500 calls this window", out)
        self.assertIn("budget: gemini 3 calls this window  (exhausted)", out)

    def test_vitals_renders_workers_and_bus_line(self):
        snap = VitalsSnapshot(stale=False, workers_busy=1, workers_total=2, bus_published=18, bus_delivered=6)
        out = render.vitals(snap)
        self.assertIn("workers: 1/2 busy", out)
        self.assertIn("bus: 18 published, 6 delivered", out)

    def test_banner_names_the_system_and_a_real_command(self):
        out = render.banner(enabled=False)
        self.assertIn("SIMORGH", out)
        self.assertIn("status", out)  # a real, always-working command
        self.assertIn("propose <topic>", out)

    def test_banner_auto_uses_no_non_latin_script(self):
        # Live-caught: the Persian name rendered as garbage on the
        # creator's terminal (font without Arabic-script glyphs) and broke
        # monospace centering (right-to-left text). Box-drawing/geometric
        # glyphs are fine; non-Latin script is opt-in only.
        out = render.banner(enabled=False, unicode="auto")
        self.assertNotIn("سیمرغ", out)
        self.assertIn("─", out)
        self.assertIn("◆", out)

    def test_banner_full_opts_into_the_persian_name_off_the_aligned_line(self):
        out = render.banner(enabled=False, unicode="full")
        self.assertIn("سیمرغ", out)
        mark_line = next(line for line in out.splitlines() if "SIMORGH" in line)
        self.assertNotIn("سیمرغ", mark_line)  # never in the centered mark

    def test_banner_off_is_pure_ascii(self):
        out = render.banner(enabled=False, unicode="off")
        self.assertTrue(out.isascii(), [c for c in out if not c.isascii()])
        self.assertIn("SIMORGH", out)

    def test_unicode_mode_honors_explicit_settings(self):
        self.assertEqual(render.unicode_mode("off"), "off")
        self.assertEqual(render.unicode_mode("full"), "full")
        self.assertIn(render.unicode_mode("auto"), ("auto", "off"))

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
