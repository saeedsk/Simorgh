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
