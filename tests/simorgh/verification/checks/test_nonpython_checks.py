"""The three checks that judge a non-Python artifact by opening it
(`trailing_narration`, `js_syntax`, `render`), plus the `written_paths`
plumbing they all stand on.

The fixtures are the real 2026-09-09 failures, reduced: an HTML page
whose IIFE is never closed (Sim's own `snake.html`, which shipped and
then failed in the creator's browser with "Unexpected end of input"),
and a page with the model's own commentary appended after `</html>`
(`breakout.html`, whose tail was "Note: apply_source_patch is scoped to
src/ or simorgh/ ...").
"""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.verification.api import CheckContext, VerifyRequest
from simorgh.verification.checks import _files
from simorgh.verification.checks.js_syntax import JsSyntaxCheck, script_bodies
from simorgh.verification.checks.render import RenderCheck
from simorgh.verification.checks.trailing_narration import (
    TrailingNarrationCheck, html_tail, python_prose_tail,
)

GOOD_PAGE = """<!DOCTYPE html>
<html><head><title>Snake</title></head>
<body><canvas id="c"></canvas>
<script>
(() => {
  const c = document.getElementById('c');
  let score = 0;
  function step() { score += 1; }
  setInterval(step, 110);
})();
</script>
</body>
</html>
"""

# The real shape of the bug: the IIFE opened on the first line is never
# closed -- the file just ends after setInterval.
UNCLOSED_IIFE_PAGE = """<!DOCTYPE html>
<html><head><title>Snake</title></head>
<body><canvas id="c"></canvas>
<script>
(() => {
  const c = document.getElementById('c');
  let score = 0;
  function step() { score += 1; }
  setInterval(step, 110);
</script>
</body>
</html>
"""

NARRATED_PAGE = GOOD_PAGE + (
    "\nNote: apply_source_patch is scoped to src/ or simorgh/, but this path was "
    "explicitly requested; proceeding. Next step after this is to verify and commit.\n"
)


class _Result:
    def __init__(self, ok=True, output="", error=None, metadata=None):
        self.ok, self.output, self.error, self.metadata = ok, output, error, metadata or {}


def _ctx(act=None) -> CheckContext:
    async def _noop(*a, **k):
        return _Result()

    return CheckContext(act=act or _noop, think=_noop, review=_noop, clock=None, config=None)


def _req(paths, *, kind="patch", subject="") -> VerifyRequest:
    return VerifyRequest(
        verification_id="v1", task_id="t1", kind=kind,
        subject={"written_paths": list(paths), "subject": subject, "kind": kind,
                 "description": "d", "result": "r", "steps": [], "complete_log": True},
    )


class _RepoFixture(unittest.IsolatedAsyncioTestCase):
    """Writes real files into a temp tree and points `_files.REPO_ROOT`
    at it, so the checks read from disk exactly as they do in
    production."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "docs" / "games").mkdir(parents=True)
        patcher = unittest.mock.patch.object(_files, "REPO_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def write(self, rel: str, text: str) -> str:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return rel


class TestWrittenPaths(_RepoFixture):
    def test_subject_is_included_even_when_no_write_landed(self):
        req = _req([], subject="docs/games/x.html")
        self.assertEqual(_files.written_paths(req), ["docs/games/x.html"])

    def test_suffix_filter_selects_only_matching_files(self):
        req = _req(["a.py", "b.html", "c.js"])
        self.assertEqual(_files.written_paths(req, suffixes=(".html", ".js")), ["b.html", "c.js"])

    def test_a_path_escaping_the_repo_reads_as_none(self):
        self.assertIsNone(_files.read_repo_file("../../etc/passwd"))
        self.assertIsNone(_files.read_repo_file("/etc/passwd"))

    def test_a_missing_file_reads_as_none_not_an_error(self):
        self.assertIsNone(_files.read_repo_file("docs/games/never_written.html"))


class TestTrailingNarrationCheck(_RepoFixture):
    async def test_commentary_after_the_closing_html_tag_fails(self):
        path = self.write("docs/games/breakout.html", NARRATED_PAGE)
        result = await TrailingNarrationCheck().run(_req([path]), _ctx())
        self.assertEqual(result.status, "failed")
        self.assertIn("apply_source_patch is scoped", result.detail)
        self.assertTrue(result.feedback.retryable)

    async def test_a_clean_page_passes(self):
        path = self.write("docs/games/snake.html", GOOD_PAGE)
        result = await TrailingNarrationCheck().run(_req([path]), _ctx())
        self.assertEqual(result.status, "passed")

    async def test_a_file_that_cannot_be_read_skips_rather_than_failing(self):
        result = await TrailingNarrationCheck().run(_req(["docs/games/gone.html"]), _ctx())
        self.assertEqual(result.status, "skipped")

    async def test_python_prose_after_the_code_is_named_as_such(self):
        path = self.write("tools/x.py", "def f():\n    return 1\n\nNow let me run the test suite.\n")
        result = await TrailingNarrationCheck().run(_req([path]), _ctx())
        self.assertEqual(result.status, "failed")
        self.assertIn("Now let me run", result.detail)

    async def test_a_genuine_python_syntax_error_is_not_blamed_on_narration(self):
        # Dropping the failing line does not make this parse, so it is a
        # real bug in real code -- SyntaxCheck's business, not this one's.
        path = self.write("tools/y.py", "def f(:\n    return 1\n")
        result = await TrailingNarrationCheck().run(_req([path]), _ctx())
        self.assertEqual(result.status, "passed")

    def test_html_tail_ignores_a_fragment_with_no_closing_tag(self):
        self.assertEqual(html_tail("<div>hi</div>"), "")

    def test_python_prose_tail_is_empty_for_valid_code(self):
        self.assertEqual(python_prose_tail("x = 1\n"), "")

    def test_applies_only_to_html_and_python(self):
        self.assertFalse(TrailingNarrationCheck().applies(_req(["notes.md"])))
        self.assertTrue(TrailingNarrationCheck().applies(_req(["a.html"])))


class TestJsSyntaxCheck(_RepoFixture):
    def _acting(self, calls, *, ok=True, error=None, metadata=None):
        async def _act(tool, args):
            calls.append((tool, args))
            return _Result(ok=ok, error=error, metadata=metadata)
        return _act

    async def test_an_unclosed_iife_fails_the_verification(self):
        # The exact bug that shipped in snake.html on 2026-09-09.
        path = self.write("docs/games/snake.html", UNCLOSED_IIFE_PAGE)
        calls: list = []
        act = self._acting(calls, ok=False, error="exit_code=1",
                           metadata={"stderr": "SyntaxError: Unexpected end of input"})
        result = await JsSyntaxCheck().run(_req([path]), _ctx(act))
        self.assertEqual(result.status, "failed")
        self.assertIn("Unexpected end of input", result.detail)
        self.assertTrue(calls, "the check must actually run the script through node")

    async def test_valid_javascript_passes(self):
        path = self.write("docs/games/snake.html", GOOD_PAGE)
        result = await JsSyntaxCheck().run(_req([path]), _ctx())
        self.assertEqual(result.status, "passed")

    async def test_no_node_on_the_machine_skips_rather_than_failing(self):
        path = self.write("docs/games/snake.html", GOOD_PAGE)
        act = self._acting([], ok=False, error="refused: no `node` executable found on this machine")
        result = await JsSyntaxCheck().run(_req([path]), _ctx(act))
        self.assertEqual(result.status, "skipped")

    async def test_the_body_travels_as_a_json_literal_so_quotes_cannot_break_out(self):
        path = self.write("docs/games/q.html", '<html><body><script>const s = "</scr" + "ipt>";</script></body></html>')
        calls: list = []
        await JsSyntaxCheck().run(_req([path]), _ctx(self._acting(calls)))
        self.assertTrue(calls)
        code = calls[0][1]["code"]
        # The probe must be `new Function("<body as a JSON string>");` --
        # the body's own quotes escaped, and no raw `</script>` able to
        # terminate anything downstream.
        self.assertTrue(code.startswith("new Function(\""))
        self.assertTrue(code.endswith("\");"))
        self.assertNotIn('</script>', code)
        self.assertIn('\\"', code)

    def test_a_src_script_has_no_body_to_check(self):
        html = '<script src="https://cdn/three.js"></script><script>let x=1;</script>'
        self.assertEqual(script_bodies(html), ["let x=1;"])

    def test_a_module_script_is_not_treated_as_a_plain_function_body(self):
        # `import`/`export` are only legal at a module's top level, so
        # `new Function(body)` throws on ANY real ES module -- valid or
        # not. Confirmed live in node, 2026-09-09:
        # new Function("import {x} from './m.js';") ->
        #   "Cannot use import statement outside a module".
        html = '<script type="module">import {x} from "./m.js"; console.log(x);</script>'
        self.assertEqual(script_bodies(html), [])

    def test_json_ld_is_not_treated_as_javascript(self):
        # `{"a": 1}` is valid JSON and invalid as a function body
        # (`Unexpected token ':'`, confirmed live in node) -- JSON-LD
        # structured data is one of the most common non-src= script
        # bodies on the real web.
        html = '<script type="application/ld+json">{"@type": "WebSite", "name": "x"}</script>'
        self.assertEqual(script_bodies(html), [])

    def test_a_plain_javascript_type_is_still_checked(self):
        html = '<script type="text/javascript">let x = 1;</script>'
        self.assertEqual(script_bodies(html), ["let x = 1;"])

    async def test_a_module_script_does_not_fail_the_verification(self):
        path = self.write(
            "docs/games/mod.html",
            '<html><body><script type="module">import {x} from "./m.js";</script></body></html>',
        )
        result = await JsSyntaxCheck().run(_req([path]), _ctx())
        self.assertEqual(result.status, "skipped")

    def test_applies_to_js_and_html_only(self):
        self.assertTrue(JsSyntaxCheck().applies(_req(["a.js"])))
        self.assertTrue(JsSyntaxCheck().applies(_req(["a.html"])))
        self.assertFalse(JsSyntaxCheck().applies(_req(["a.py"])))


class TestRenderCheck(_RepoFixture):
    def _acting(self, *, ok=True, error=None, metadata=None):
        async def _act(tool, args):
            return _Result(ok=ok, error=error, metadata=metadata or {})
        return _act

    async def test_a_runtime_error_on_load_fails(self):
        path = self.write("docs/games/x.html", GOOD_PAGE)
        act = self._acting(metadata={"page_errors": ["TypeError: c.getContext is not a function"]})
        result = await RenderCheck().run(_req([path]), _ctx(act))
        self.assertEqual(result.status, "failed")
        self.assertIn("TypeError", result.detail)

    async def test_a_clean_render_passes(self):
        path = self.write("docs/games/x.html", GOOD_PAGE)
        result = await RenderCheck().run(_req([path]), _ctx(self._acting()))
        self.assertEqual(result.status, "passed")

    async def test_a_failed_cdn_request_is_a_warning_not_a_failure(self):
        # Verifying offline must not fail a page that pulls Three.js.
        path = self.write("docs/games/x.html", GOOD_PAGE)
        act = self._acting(metadata={"failed_requests": ["https://cdnjs.cloudflare.com/three.js -- net::ERR_FAILED"]})
        result = await RenderCheck().run(_req([path]), _ctx(act))
        self.assertEqual(result.status, "passed")
        self.assertIn("external request", result.detail)

    async def test_a_missing_local_file_does_fail(self):
        path = self.write("docs/games/x.html", GOOD_PAGE)
        act = self._acting(metadata={"failed_requests": ["file:///repo/docs/games/missing.js -- net::ERR_FILE_NOT_FOUND"]})
        result = await RenderCheck().run(_req([path]), _ctx(act))
        self.assertEqual(result.status, "failed")

    async def test_no_browser_skips_rather_than_failing(self):
        path = self.write("docs/games/x.html", GOOD_PAGE)
        act = self._acting(ok=False, error="refused: could not locate Puppeteer's global node_modules")
        result = await RenderCheck().run(_req([path]), _ctx(act))
        self.assertEqual(result.status, "skipped")

    async def test_console_error_calls_fail(self):
        path = self.write("docs/games/x.html", GOOD_PAGE)
        act = self._acting(metadata={"console_messages": ["error: canvas missing", "log: fine"]})
        result = await RenderCheck().run(_req([path]), _ctx(act))
        self.assertEqual(result.status, "failed")
        self.assertIn("canvas missing", result.detail)
