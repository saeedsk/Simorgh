"""`render_page` (execution/render.py, toolset #1 from the 2026-09-09
game-generation post-mortem): a real headless-Chromium render via
Puppeteer. Unit tests mock the subprocess boundary; a handful of real
end-to-end tests skip themselves when Node/Puppeteer aren't actually
available on the machine running the suite, same pattern as
`RunJsSandboxedTool`'s own tests."""

from __future__ import annotations

import json
import shutil
import socket
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.netsafety import FetchRefused
from simorgh.execution.render import RenderPageTool, render_summary


def _ctx(config: Config, constraints: dict | None = None):
    from simorgh.contracts.protocols import ToolContext

    return ToolContext(
        action_id="a1", task_id=None, scope={}, constraints=constraints or {},
        data_dir=config.repo_root, clock=None, logger=None, ledger=None,
    )


def _private_resolver(host, _port):
    return [(socket.AF_INET, None, None, "", ("127.0.0.1", 0))]


def _public_resolver(host, _port):
    return [(socket.AF_INET, None, None, "", ("93.184.216.34", 0))]


class ResolveTargetTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "page.html").write_text("<html><body>hi</body></html>")
        self.addCleanup(self._tmp.cleanup)

    def _tool(self, **kwargs):
        config = Config(repo_root=self.root)
        return RenderPageTool(config, node_path="/usr/bin/env", node_module_path="/nonexistent", resolver=_public_resolver, **kwargs)

    async def test_a_private_resolving_url_is_refused(self):
        tool = RenderPageTool(
            Config(repo_root=self.root), node_path="/usr/bin/env", node_module_path="/x",
            resolver=_private_resolver,
        )
        result = await tool.run({"target": "http://internal.example/"}, ctx=_ctx(tool._config))
        self.assertFalse(result.ok)
        self.assertIn("SSRF", result.error)

    async def test_a_non_http_scheme_that_is_not_a_repo_path_is_refused(self):
        tool = self._tool()
        result = await tool.run({"target": "javascript:alert(1)"}, ctx=_ctx(tool._config))
        self.assertFalse(result.ok)

    async def test_a_path_outside_readable_roots_is_refused(self):
        tool = self._tool()
        result = await tool.run({"target": "../../etc/passwd"}, ctx=_ctx(tool._config))
        self.assertFalse(result.ok)

    async def test_no_node_found_is_refused(self):
        config = Config(repo_root=self.root)
        tool = RenderPageTool(config, node_path=None, node_module_path="/x")
        result = await tool.run({"target": "docs/page.html"}, ctx=_ctx(config))
        self.assertFalse(result.ok)
        self.assertIn("node", result.error)

    async def test_no_puppeteer_module_path_is_refused(self):
        config = Config(repo_root=self.root)
        tool = RenderPageTool(config, node_path="/usr/bin/env", node_module_path="")
        result = await tool.run({"target": "docs/page.html"}, ctx=_ctx(config))
        self.assertFalse(result.ok)
        self.assertIn("Puppeteer", result.error)

    async def test_a_local_path_is_turned_into_a_file_uri_for_the_driver(self):
        tool = self._tool()
        calls = []
        real_run = __import__("subprocess").run

        def spy(cmd, **kwargs):
            calls.append(cmd)
            payload = json.dumps({"ok": True, "nav_error": None, "title": "t", "text": "hi",
                                   "console_messages": [], "page_errors": [], "failed_requests": []})
            return unittest.mock.Mock(returncode=0, stdout=payload, stderr="")

        with unittest.mock.patch("simorgh.execution.render.subprocess.run", side_effect=spy):
            result = await tool.run({"target": "docs/page.html"}, ctx=_ctx(tool._config))
        self.assertTrue(result.ok, result.error)
        self.assertTrue(calls)
        passed_url = calls[0][2]
        self.assertTrue(passed_url.startswith("file://"))
        self.assertTrue(passed_url.endswith("page.html"))


class DriverResultHandlingTestCase(unittest.IsolatedAsyncioTestCase):
    def _tool(self, root):
        config = Config(repo_root=root)
        return RenderPageTool(config, node_path="/usr/bin/env", node_module_path="/x", resolver=_public_resolver)

    async def test_a_navigation_error_is_reported_as_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = self._tool(Path(tmp))
            payload = json.dumps({"ok": False, "nav_error": "net::ERR_NAME_NOT_RESOLVED", "title": "",
                                   "text": "", "console_messages": [], "page_errors": [], "failed_requests": []})
            with unittest.mock.patch("simorgh.execution.render.subprocess.run",
                                      return_value=unittest.mock.Mock(returncode=0, stdout=payload, stderr="")):
                result = await tool.run({"target": "https://nonexistent.invalid/"}, ctx=_ctx(tool._config))
        self.assertFalse(result.ok)
        self.assertIn("ERR_NAME_NOT_RESOLVED", result.error)

    async def test_page_errors_and_failed_requests_surface_in_metadata_and_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = self._tool(Path(tmp))
            payload = json.dumps({
                "ok": True, "nav_error": None, "title": "Broken Page", "text": "some text",
                "console_messages": ["error: boom"], "page_errors": ["TypeError: x is not a function"],
                "failed_requests": ["https://x/y.js -- net::ERR_ABORTED"],
            })
            with unittest.mock.patch("simorgh.execution.render.subprocess.run",
                                      return_value=unittest.mock.Mock(returncode=0, stdout=payload, stderr="")):
                result = await tool.run({"target": "https://example.com/"}, ctx=_ctx(tool._config))
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["page_errors"], ["TypeError: x is not a function"])
        self.assertEqual(result.metadata["failed_requests"], ["https://x/y.js -- net::ERR_ABORTED"])
        self.assertIn("uncaught JS error", result.output)
        self.assertIn("failed network request", result.output)

    async def test_unparseable_driver_output_is_a_clean_failure_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = self._tool(Path(tmp))
            with unittest.mock.patch("simorgh.execution.render.subprocess.run",
                                      return_value=unittest.mock.Mock(returncode=0, stdout="not json at all", stderr="")):
                result = await tool.run({"target": "https://example.com/"}, ctx=_ctx(tool._config))
        self.assertFalse(result.ok)
        self.assertIn("no parseable result", result.error)

    async def test_a_nonzero_exit_is_a_clean_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = self._tool(Path(tmp))
            with unittest.mock.patch("simorgh.execution.render.subprocess.run",
                                      return_value=unittest.mock.Mock(returncode=1, stdout="", stderr="boom")):
                result = await tool.run({"target": "https://example.com/"}, ctx=_ctx(tool._config))
        self.assertFalse(result.ok)
        self.assertIn("exited 1", result.error)


class RenderSummaryTestCase(unittest.TestCase):
    def test_a_clean_page_says_so(self):
        text = render_summary("https://x/", {"ok": True, "title": "T"}, "body text")
        self.assertIn("no JS errors, console errors, or failed requests", text)
        self.assertIn("body text", text)

    def test_a_failed_navigation_says_why(self):
        text = render_summary("https://x/", {"ok": False, "nav_error": "timeout"}, "")
        self.assertIn("timeout", text)


class RealBrowserSmokeTestCase(unittest.IsolatedAsyncioTestCase):
    """Real end-to-end: actually launches headless Chromium via the
    globally-installed Puppeteer. Skips itself if either isn't present
    on the machine running the suite."""

    def _skip_unless_available(self):
        if not shutil.which("node") or not shutil.which("npm"):
            self.skipTest("node/npm not installed on this machine")
        import subprocess

        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=10)
        if root.returncode != 0 or not root.stdout.strip():
            self.skipTest("no global npm root")
        if not (Path(root.stdout.strip()) / "puppeteer").exists():
            self.skipTest("puppeteer not installed globally on this machine")

    async def test_a_local_page_with_a_thrown_error_is_actually_caught(self):
        self._skip_unless_available()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "broken.html").write_text(
                "<html><body><h1>hi</h1><script>throw new Error('boom');</script></body></html>"
            )
            config = Config(repo_root=root, render_page_timeout_s=15.0)
            tool = RenderPageTool(config)
            result = await tool.run({"target": "docs/broken.html"}, ctx=_ctx(config))
        self.assertTrue(result.ok, result.error)  # navigation itself succeeds
        self.assertTrue(result.metadata["page_errors"])
        self.assertIn("boom", result.metadata["page_errors"][0])
        self.assertIn("hi", result.output)


class RequestGuardRealTestCase(unittest.IsolatedAsyncioTestCase):
    """Found live, 2026-09-09: `validate_public_http_url` only ever
    checks the URL/hostname it is first handed, in Python, once.
    Puppeteer then does its own, completely independent DNS resolution
    for the real connection AND for every redirect hop, neither of
    which is ever re-validated. A URL that validates as public and then
    302s straight to `http://127.0.0.1:<port>/` used to sail through
    with the internal page's title/body reported back verbatim. The
    fix re-runs the SSRF check inside the Node driver itself, on every
    request (main navigation, every redirect, every subresource), via
    `page.setRequestInterception` -- this proves that actually holds
    against a real redirect, with a real browser."""

    def _skip_unless_available(self):
        if not shutil.which("node") or not shutil.which("npm"):
            self.skipTest("node/npm not installed on this machine")
        import subprocess

        root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=10)
        if root.returncode != 0 or not root.stdout.strip():
            self.skipTest("no global npm root")
        if not (Path(root.stdout.strip()) / "puppeteer").exists():
            self.skipTest("puppeteer not installed globally on this machine")

    async def test_a_redirect_to_a_loopback_address_is_blocked_not_followed(self):
        self._skip_unless_available()
        import http.server
        import threading

        front_port, internal_port = 9391, 9392

        class Front(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{internal_port}/secret")
                self.end_headers()

            def log_message(self, *a):
                pass

        class Internal(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><title>internal</title><body>SHOULD-NEVER-BE-SEEN</body></html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        front_srv = http.server.HTTPServer(("127.0.0.1", front_port), Front)
        internal_srv = http.server.HTTPServer(("127.0.0.1", internal_port), Internal)
        threading.Thread(target=front_srv.serve_forever, daemon=True).start()
        threading.Thread(target=internal_srv.serve_forever, daemon=True).start()
        self.addCleanup(front_srv.shutdown)
        self.addCleanup(internal_srv.shutdown)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # `localhost` really does resolve to 127.0.0.1, so with the
            # tool's normal resolver the front server itself would
            # already be refused by the one-time Python-level check --
            # that's `test_a_private_resolving_url_is_refused` above.
            # This test isolates the thing that check structurally
            # cannot catch: a URL that is (or appears) public at
            # check-time, then redirects somewhere private. `_public_resolver`
            # stands in for a real public host / a rebinding DNS answer
            # at check-time; the redirect step itself is real HTTP,
            # against a real local server, through the real driver.
            config = Config(repo_root=root, render_page_timeout_s=10.0)
            tool = RenderPageTool(config, resolver=_public_resolver)
            result = await tool.run({"target": f"http://localhost:{front_port}/"}, ctx=_ctx(config))
        self.assertFalse(result.ok)
        self.assertNotIn("SHOULD-NEVER-BE-SEEN", result.output)


class ClassifyActionsTestCase(unittest.TestCase):
    """`browse_page`'s action list, before any browser is launched."""

    def test_a_normal_action_list_passes(self):
        from simorgh.execution.render import classify_actions

        self.assertEqual(classify_actions(
            [{"type": ["#q", "hello"]}, {"click": "#go"}, {"wait": "#results"},
             {"screenshot": "after"}, {"scroll": 400}]), "")

    def test_there_is_no_way_to_run_your_own_javascript(self):
        # A JS string inside a JSON argument would be code that
        # Guardian's code/command rules never see -- the entire static
        # analysis layer routed around by a field name.
        from simorgh.execution.render import classify_actions

        for action in ({"evaluate": "fetch('http://x')"}, {"eval": "1"}, {"script": "x"}):
            with self.subTest(action=action):
                self.assertIn("not an allowed action", classify_actions([action]))

    def test_a_credential_looking_field_is_never_typed_into(self):
        from simorgh.execution.render import classify_actions

        for selector in ("#password", "input[name=secret]", "#api_token", "#cvv", "#ssn"):
            with self.subTest(selector=selector):
                refusal = classify_actions([{"type": [selector, "hunter2"]}])
                self.assertIn("credential", refusal)

    def test_common_credential_abbreviations_are_also_refused(self):
        # Found live, 2026-09-09: the original _SECRET_SELECTOR regex
        # (pass|secret|token|otp|cvv|card|ssn) let every one of these
        # ordinary field names straight through -- none of them are
        # adversarial tricks, they're just how real login/payment forms
        # name their fields.
        from simorgh.execution.render import classify_actions

        for selector in ("#pwd", "#pw", "input[name=pw]", "#login_pwd", "#apikey",
                          "#api_key", "#pin", "#bank_account", "#iban", "#security_code"):
            with self.subTest(selector=selector):
                refusal = classify_actions([{"type": [selector, "hunter2"]}])
                self.assertIn("credential", refusal)

    def test_ordinary_words_containing_pw_or_pin_are_not_falsely_refused(self):
        from simorgh.execution.render import classify_actions

        for selector in ("#spawn_area", "#spinner", "#upward_arrow"):
            with self.subTest(selector=selector):
                self.assertEqual(classify_actions([{"type": [selector, "hello"]}]), "")

    def test_a_javascript_url_selector_is_refused(self):
        from simorgh.execution.render import classify_actions

        self.assertIn("not a usable selector", classify_actions([{"click": "javascript:alert(1)"}]))

    def test_too_many_actions_are_refused(self):
        from simorgh.execution.render import classify_actions

        self.assertIn("at most", classify_actions([{"scroll": 1}] * 50))

    def test_a_screenshot_name_cannot_escape_its_directory(self):
        from simorgh.execution.render import classify_actions

        for name in ("../../etc/passwd", "a/b", "with space"):
            with self.subTest(name=name):
                self.assertTrue(classify_actions([{"screenshot": name}]))

    def test_a_malformed_action_is_refused(self):
        from simorgh.execution.render import classify_actions

        self.assertTrue(classify_actions([{"click": "#a", "type": ["#b", "c"]}]))
        self.assertTrue(classify_actions(["click #a"]))
        self.assertTrue(classify_actions("not a list"))

    def test_mutating_actions_are_recognised(self):
        from simorgh.execution.render import mutates

        self.assertTrue(mutates([{"click": "#go"}]))
        self.assertTrue(mutates([{"type": ["#q", "x"]}]))
        self.assertFalse(mutates([{"wait": "#x"}, {"screenshot": "s"}]))


class BrowsePageRealTestCase(unittest.IsolatedAsyncioTestCase):
    """A real browser against a real local page with a form."""

    def _skip_unless_available(self):
        if not shutil.which("node") or not shutil.which("npm"):
            self.skipTest("node/npm not installed")
        import subprocess as sp

        root = sp.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=10)
        if root.returncode != 0 or not (Path(root.stdout.strip()) / "puppeteer").exists():
            self.skipTest("puppeteer not installed globally")

    async def test_typing_and_clicking_actually_changes_the_page(self):
        self._skip_unless_available()
        from simorgh.execution.render import BrowsePageTool

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "form.html").write_text(
                "<html><body><input id='q'><button id='go' "
                "onclick=\"document.getElementById('out').innerText='got: '+"
                "document.getElementById('q').value\">Go</button>"
                "<div id='out'>nothing yet</div></body></html>"
            )
            config = Config(repo_root=root, render_page_timeout_s=20.0)
            result = await BrowsePageTool(config).run(
                {"target": "docs/form.html",
                 "actions": [{"type": ["#q", "almaden"]}, {"click": "#go"}, {"screenshot": "after"}]},
                ctx=_ctx(config))
            self.assertTrue(result.ok, result.error)
            self.assertIn("got: almaden", result.output)
            self.assertEqual(result.metadata["actions_done"], 3)
            self.assertTrue(result.metadata["screenshots"])
            self.assertTrue(Path(result.metadata["screenshots"][0]).is_file())

    async def test_a_selector_that_does_not_exist_stops_and_says_where(self):
        self._skip_unless_available()
        from simorgh.execution.render import BrowsePageTool

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs" / "p.html").write_text("<html><body><p>hi</p></body></html>")
            config = Config(repo_root=root, render_page_timeout_s=20.0)
            result = await BrowsePageTool(config).run(
                {"target": "docs/p.html", "actions": [{"click": "#nope"}]}, ctx=_ctx(config))
        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["actions_done"], 0)
        self.assertIn("nope", result.output)
