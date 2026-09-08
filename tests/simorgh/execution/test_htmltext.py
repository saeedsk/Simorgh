"""HTML to readable text (`execution/htmltext.py`).

`web_fetch` used to hand the model raw markup. Measured on real pages
(observer, 2026-09-08): 74% markup on a docs page, 87% on an arXiv
abstract, and 99.5% on a JavaScript app that returned 224 usable
characters with `ok=True` and told the model nothing was wrong.
"""

from __future__ import annotations

import unittest

from simorgh.execution.htmltext import html_to_text, looks_like_html

PAGE = """<!doctype html>
<html><head><title>  Ruff  documentation </title>
<style>body{color:red}</style>
<script>var x = "this text must never appear";</script>
</head>
<body>
  <nav><a href="/index">Home</a></nav>
  <h1>Installation</h1>
  <p>Ruff requires Python 3.7 or newer.</p>
  <ul><li>pip install ruff</li><li>uv tool install ruff</li></ul>
  <p>See the <a href="https://docs.astral.sh/ruff/">full documentation</a> for details,
     and the <a href="#anchor">anchor</a> which is not a destination.</p>
  <table><tr><td>version</td><td>0.16.6</td></tr></table>
  <noscript>enable javascript</noscript>
</body></html>
"""

# Sized like a real one: the measured Hugging Face Space was 41,954
# bytes of markup and script around 224 characters of text.
JS_SHELL = (
    '<!doctype html><html><head><title>GAIA Leaderboard</title></head>'
    '<body><div id="root"></div>'
    '<script>window.__DATA__ = {"rows": [' + ",".join(f'{{"i":{n}}}' for n in range(3000)) + ']};</script>'
    "</body></html>"
)


class DetectionTestCase(unittest.TestCase):
    def test_html_is_recognised(self):
        self.assertTrue(looks_like_html(PAGE))
        self.assertTrue(looks_like_html("<html><body>hi</body></html>"))

    def test_json_and_plain_text_pass_through(self):
        self.assertFalse(looks_like_html('{"id": 1, "name": "ruff"}'))
        self.assertFalse(looks_like_html('[1, 2, 3]'))
        self.assertFalse(looks_like_html("# A markdown README\n\nSome prose."))


class ExtractionTestCase(unittest.TestCase):
    def setUp(self):
        self.text, self.shell = html_to_text(PAGE, url="https://docs.astral.sh/ruff/")

    def test_it_is_not_mistaken_for_a_shell(self):
        self.assertFalse(self.shell)

    def test_script_and_style_never_survive(self):
        self.assertNotIn("this text must never appear", self.text)
        self.assertNotIn("color:red", self.text)
        self.assertNotIn("enable javascript", self.text)

    def test_the_title_leads(self):
        self.assertTrue(self.text.startswith("Ruff documentation"), self.text[:80])

    def test_the_content_survives(self):
        self.assertIn("Ruff requires Python 3.7 or newer.", self.text)
        self.assertIn("0.16.6", self.text)

    def test_structure_is_readable(self):
        self.assertIn("# Installation", self.text)
        self.assertIn("- pip install ruff", self.text)

    def test_a_real_link_keeps_its_destination_and_a_fragment_does_not(self):
        self.assertIn("full documentation (https://docs.astral.sh/ruff/)", self.text)
        self.assertIn("anchor", self.text)
        self.assertNotIn("(#anchor)", self.text)

    def test_it_is_much_smaller_than_the_markup(self):
        self.assertLess(len(self.text), len(PAGE))


class JsShellTestCase(unittest.TestCase):
    """The important one: a page with no text must SAY so, not return a
    bare success with nothing in it."""

    def test_a_javascript_shell_is_reported(self):
        text, shell = html_to_text(JS_SHELL, url="https://x.hf.space/")
        self.assertTrue(shell)
        self.assertIn("JavaScript", text)
        self.assertIn("https://x.hf.space/", text)
        self.assertIn("Try an API", text)

    def test_the_shell_message_keeps_whatever_text_there_was(self):
        text, _ = html_to_text(JS_SHELL)
        self.assertIn("GAIA Leaderboard", text, "the title is still useful")

    def test_an_empty_document_is_a_shell_not_a_crash(self):
        text, shell = html_to_text("")
        self.assertTrue(shell)
        self.assertTrue(text.strip())

    def test_the_hrefs_we_keep_do_not_count_as_content(self):
        """A page whose only text is link targets is still contentless;
        counting the hrefs would hide that."""
        from simorgh.execution.htmltext import _visible_chars

        stripped = _visible_chars("x (https://example.com/a-very-long-path) y")
        self.assertLess(stripped, 6, "the href must not be counted as content")
        self.assertGreaterEqual(stripped, 3, "the real words must be")

    def test_a_small_page_with_short_text_is_not_a_shell(self):
        """A short document is just short. Flagging it would report a
        problem that is not there."""
        _text, shell = html_to_text("<html><body><p>Version 0.16.6.</p></body></html>")
        self.assertFalse(shell)

    def test_a_large_page_with_almost_no_text_is_a_shell(self):
        big = "<html><body><div id='root'></div>" + "<!-- " + "x" * 40000 + " -->" + "<p>hi</p></body></html>"
        _text, shell = html_to_text(big)
        self.assertTrue(shell)


class RobustnessTestCase(unittest.TestCase):
    def test_malformed_markup_keeps_what_parsed(self):
        text, _ = html_to_text("<html><body><p>kept<div><span>also kept" + "<b" * 50)
        self.assertIn("kept", text)

    def test_entities_are_decoded(self):
        text, _ = html_to_text("<html><body><p>" + "a &amp; b &lt;c&gt; " * 20 + "</p></body></html>")
        self.assertIn("a & b <c>", text)


if __name__ == "__main__":
    unittest.main()
