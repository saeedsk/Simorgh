"""`render_page`: a real headless-Chromium render via Puppeteer (toolset
#1 from the 2026-09-09 game-generation post-mortem). `SyntaxCheck`
(verification/checks/syntax.py) only parses Python; nothing in the
pipeline ever actually *ran* a generated page the way a browser does.
That gap was directly how the unclosed-IIFE bug in Sim's own generated
`snake.html` went undetected until a human opened it, and how a leaked-
narration bug (cognition/parser.py's code-bearing-marker design) sat in
committed `breakout.html`/`3d_maze.html` past every mechanical check.

This tool loads a URL (SSRF-guarded, same as `web_fetch`) or a repo-
local file (same `pathsafety`/`readable_roots` boundary every other
file-reading tool uses) in real headless Chromium via the Puppeteer
npm package already installed globally on this machine, and reports
back what a person opening it would actually see: the page title, the
visible text, any `console.error`/`pageerror` events, and any failed
network requests -- the things a syntax check structurally cannot see
(a runtime TypeError, a 404'd script, a layout that never renders).

Puppeteer is a Node package installed globally (`npm ls -g puppeteer`),
not a Python dependency, so this shells out to `node` running a small
driver script -- the same shape as `RunJsSandboxedTool`, plus one
environment variable (`NODE_PATH`, pointed at the global node_modules
dir) so `require('puppeteer')` can resolve without a full inherited
environment. Read-only: the driver never writes anything the caller
didn't already ask to load.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from simorgh.contracts.protocols import ToolContext, ToolResult

from . import pathsafety
from .config import Config
from .netsafety import FetchRefused, validate_public_http_url

_DRIVER = r"""
const puppeteer = require('puppeteer');

async function main() {
  const [, , url, timeoutMsStr] = process.argv;
  const timeoutMs = parseInt(timeoutMsStr, 10);
  const browser = await puppeteer.launch({headless: 'new', args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    const consoleMessages = [];
    const pageErrors = [];
    const failedRequests = [];
    page.on('console', m => consoleMessages.push(`${m.type()}: ${m.text()}`));
    page.on('pageerror', e => pageErrors.push(String(e)));
    page.on('requestfailed', r => failedRequests.push(`${r.url()} -- ${r.failure() && r.failure().errorText}`));
    let navError = null;
    try {
      await page.goto(url, {waitUntil: 'networkidle0', timeout: timeoutMs});
    } catch (e) {
      navError = String(e && e.message || e);
    }
    const title = navError ? '' : await page.title().catch(() => '');
    const text = navError ? '' : await page.evaluate(() => document.body ? document.body.innerText : '').catch(() => '');
    console.log(JSON.stringify({
      ok: !navError, nav_error: navError, title, text,
      console_messages: consoleMessages, page_errors: pageErrors, failed_requests: failedRequests,
    }));
  } finally {
    await browser.close();
  }
}

main().catch(e => {
  console.log(JSON.stringify({ok: false, nav_error: String(e && e.message || e),
    title: '', text: '', console_messages: [], page_errors: [], failed_requests: []}));
  process.exit(0);
});
"""


class RenderPageTool:
    name = "render_page"
    description = (
        "Load a URL or a repo-local file in real headless Chromium and report back its title, "
        "visible text, console errors, uncaught exceptions, and failed network requests."
    )
    read_only = True
    reversibility = "read_only"
    args_schema = {"type": "object", "required": ["target"], "properties": {"target": {"type": "string"}}}

    _UNSET = object()

    def __init__(self, config: Config, *, node_path: str | None = _UNSET,
                 node_module_path: str | None = _UNSET, resolver=None) -> None:
        self._config = config
        self._node = shutil.which("node") if node_path is self._UNSET else node_path
        self._node_module_path = (
            self._discover_node_modules() if node_module_path is self._UNSET else node_module_path
        )
        self._resolver = resolver or socket.getaddrinfo

    def _discover_node_modules(self) -> str:
        if self._config.render_page_node_path:
            return self._config.render_page_node_path
        npm = shutil.which("npm")
        if not npm:
            return ""
        try:
            completed = subprocess.run(
                [npm, "root", "-g"], capture_output=True, text=True, timeout=10.0, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return completed.stdout.strip() if completed.returncode == 0 else ""

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        if not self._node:
            return ToolResult(ok=False, error="refused: no `node` executable found on this machine")
        if not self._node_module_path:
            return ToolResult(ok=False, error="refused: could not locate Puppeteer's global node_modules (is it installed?)")

        target = str(args["target"]).strip()
        try:
            url = self._resolve_target(target)
        except FetchRefused as exc:
            return ToolResult(ok=False, error=str(exc))

        timeout = min(ctx.constraints.get("timeout_s", self._config.render_page_timeout_s),
                      self._config.render_page_timeout_s)
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="simorgh-render-") as workdir:
            driver = Path(workdir) / "render_driver.js"
            driver.write_text(_DRIVER)
            try:
                completed = subprocess.run(
                    [self._node, str(driver), url, str(int(timeout * 1000))],
                    capture_output=True, text=True, cwd=workdir,
                    env={"NODE_PATH": self._node_module_path}, timeout=timeout + 5.0,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired as exc:
                return ToolResult(
                    ok=False, output=(exc.stdout or ""), error="timeout",
                    metadata={"stderr": exc.stderr or "", "duration_s": time.monotonic() - start},
                )
            if completed.returncode != 0:
                return ToolResult(
                    ok=False, error=f"render process exited {completed.returncode}",
                    metadata={"stderr": completed.stderr, "duration_s": time.monotonic() - start},
                )
            try:
                payload = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.stdout.strip() else {}
            except (json.JSONDecodeError, IndexError):
                return ToolResult(
                    ok=False, error="render process produced no parseable result",
                    metadata={"stdout": completed.stdout, "stderr": completed.stderr},
                )
            ok = bool(payload.get("ok"))
            text = str(payload.get("text") or "")[: self._config.render_page_max_chars]
            return ToolResult(
                ok=ok,
                output=render_summary(target, payload, text),
                error=None if ok else (payload.get("nav_error") or "render failed"),
                metadata={
                    "title": payload.get("title", ""),
                    "console_messages": payload.get("console_messages", []),
                    "page_errors": payload.get("page_errors", []),
                    "failed_requests": payload.get("failed_requests", []),
                    "duration_s": time.monotonic() - start,
                },
            )

    def _resolve_target(self, target: str) -> str:
        if target.startswith(("http://", "https://")):
            validate_public_http_url(
                target, allow_private=self._config.render_page_allow_private_networks, resolver=self._resolver)
            return target
        resolved, refusal = pathsafety.resolve_safe_path(
            self._config.repo_root, target, readable_roots=self._config.readable_roots)
        if refusal:
            raise FetchRefused(refusal)
        return resolved.as_uri()


def render_summary(target: str, payload: dict, text: str) -> str:
    if not payload.get("ok"):
        return f"render of {target!r} failed: {payload.get('nav_error') or 'unknown error'}"
    lines = [f"rendered {target!r}: title={payload.get('title', '')!r}"]
    page_errors = payload.get("page_errors") or []
    if page_errors:
        lines.append(f"{len(page_errors)} uncaught JS error(s): " + "; ".join(page_errors[:5]))
    console_errors = [m for m in (payload.get("console_messages") or []) if m.startswith("error:")]
    if console_errors:
        lines.append(f"{len(console_errors)} console.error() call(s): " + "; ".join(console_errors[:5]))
    failed = payload.get("failed_requests") or []
    if failed:
        lines.append(f"{len(failed)} failed network request(s): " + "; ".join(failed[:5]))
    if not page_errors and not console_errors and not failed:
        lines.append("no JS errors, console errors, or failed requests observed")
    lines.append("--- visible text ---")
    lines.append(text)
    return "\n".join(lines)
