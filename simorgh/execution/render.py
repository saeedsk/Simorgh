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
import re
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

# Shared by both drivers: `_resolve_target`/`validate_public_http_url`
# only ever check the URL/hostname they were FIRST given, in Python,
# once. Puppeteer/Chromium then does its OWN, completely independent
# DNS resolution for the real TCP connection -- and for every redirect
# hop, which is never re-validated at all. An attacker who controls DNS
# (a rebinding server answering differently to the two resolutions) or
# who simply 302s a validated URL to `http://127.0.0.1:<port>/` sails
# straight through: confirmed live, both ways, 2026-09-09. This guard
# re-runs the SSRF check inside the driver itself, on every single
# network request (main navigation, every redirect, every subresource),
# immediately before Chromium is allowed to make it -- closing the
# redirect bypass completely and shrinking the DNS-rebinding window from
# "never re-checked" to "re-checked a moment before the real connect".
_REQUEST_GUARD = r"""
const dns = require('dns');

function isPrivateAddress(ip) {
  if (ip.includes(':')) {
    const low = ip.toLowerCase();
    if (low === '::1' || low === '::') return true;
    if (low.startsWith('fe80:')) return true;       // link-local
    if (low.startsWith('fc') || low.startsWith('fd')) return true;  // unique local fc00::/7
    return false;
  }
  const parts = ip.split('.').map(Number);
  if (parts.length !== 4 || parts.some(n => Number.isNaN(n))) return true;  // fail closed
  const [a, b] = parts;
  if (a === 127) return true;                        // loopback
  if (a === 10) return true;                          // RFC1918
  if (a === 172 && b >= 16 && b <= 31) return true;    // RFC1918
  if (a === 192 && b === 168) return true;             // RFC1918
  if (a === 169 && b === 254) return true;             // link-local
  if (a === 100 && b >= 64 && b <= 127) return true;    // CGNAT
  if (a === 0) return true;                             // "this network" / unspecified
  if (a >= 224) return true;                            // multicast + reserved
  return false;
}

async function isAllowedUrl(rawUrl, allowPrivate) {
  let u;
  try { u = new URL(rawUrl); } catch (e) { return false; }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return true;  // not a network fetch
  if (allowPrivate) return true;
  let addrs;
  try {
    addrs = await dns.promises.lookup(u.hostname, {all: true});
  } catch (e) {
    return false;  // unresolvable -- fail closed, same as any other DNS failure
  }
  return addrs.length > 0 && addrs.every(a => !isPrivateAddress(a.address));
}

function installRequestGuard(page, allowPrivate, failedRequests) {
  page.on('request', async (request) => {
    let allowed;
    try {
      allowed = await isAllowedUrl(request.url(), allowPrivate);
    } catch (e) {
      allowed = false;
    }
    if (allowed) {
      request.continue().catch(() => {});
    } else {
      failedRequests.push(`${request.url()} -- blocked: resolves to a private/internal address (SSRF guard)`);
      request.abort('blockedbyclient').catch(() => {});
    }
  });
  return page.setRequestInterception(true);
}
"""

_DRIVER = _REQUEST_GUARD + r"""
const puppeteer = require('puppeteer');

async function main() {
  const [, , url, timeoutMsStr, allowPrivateStr] = process.argv;
  const timeoutMs = parseInt(timeoutMsStr, 10);
  const allowPrivate = allowPrivateStr === '1';
  const browser = await puppeteer.launch({headless: 'new', args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    const consoleMessages = [];
    const pageErrors = [];
    const failedRequests = [];
    page.on('console', m => consoleMessages.push(`${m.type()}: ${m.text()}`));
    page.on('pageerror', e => pageErrors.push(String(e)));
    page.on('requestfailed', r => failedRequests.push(`${r.url()} -- ${r.failure() && r.failure().errorText}`));
    await installRequestGuard(page, allowPrivate, failedRequests);
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
            allow_private = "1" if self._config.render_page_allow_private_networks else "0"
            try:
                completed = subprocess.run(
                    [self._node, str(driver), url, str(int(timeout * 1000)), allow_private],
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


_BROWSE_DRIVER = _REQUEST_GUARD + r"""
const puppeteer = require('puppeteer');

async function main() {
  const [, , url, timeoutMsStr, actionsJson, shotDir, allowPrivateStr] = process.argv;
  const timeoutMs = parseInt(timeoutMsStr, 10);
  const allowPrivate = allowPrivateStr === '1';
  const actions = JSON.parse(actionsJson);
  const browser = await puppeteer.launch({headless: 'new', args: ['--no-sandbox']});
  const consoleMessages = [], pageErrors = [], failedRequests = [], screenshots = [];
  let done = 0, lastError = null, navError = null;
  try {
    const page = await browser.newPage();
    page.on('console', m => consoleMessages.push(`${m.type()}: ${m.text()}`));
    page.on('pageerror', e => pageErrors.push(String(e)));
    page.on('requestfailed', r => failedRequests.push(`${r.url()} -- ${r.failure() && r.failure().errorText}`));
    await installRequestGuard(page, allowPrivate, failedRequests);
    try {
      await page.goto(url, {waitUntil: 'networkidle0', timeout: timeoutMs});
    } catch (e) { navError = String(e && e.message || e); }
    if (!navError) {
      for (const action of actions) {
        try {
          if (action.click) await page.click(action.click, {timeout: 10000});
          else if (action.type) await page.type(action.type[0], action.type[1], {delay: 5});
          else if (action.press) await page.keyboard.press(action.press);
          else if (action.wait !== undefined) {
            if (typeof action.wait === 'number') await new Promise(r => setTimeout(r, action.wait));
            else await page.waitForSelector(action.wait, {timeout: 10000});
          } else if (action.screenshot) {
            const file = `${shotDir}/${action.screenshot}.png`;
            await page.screenshot({path: file});
            screenshots.push(file);
          } else if (action.scroll) {
            await page.evaluate(y => window.scrollBy(0, y), action.scroll);
          } else { throw new Error('unknown action: ' + JSON.stringify(action)); }
          done += 1;
        } catch (e) { lastError = `${JSON.stringify(action)}: ${String(e && e.message || e)}`; break; }
      }
    }
    const title = navError ? '' : await page.title().catch(() => '');
    const text = navError ? '' : await page.evaluate(() => document.body ? document.body.innerText : '').catch(() => '');
    console.log(JSON.stringify({
      ok: !navError && !lastError, nav_error: navError, last_error: lastError,
      actions_done: done, actions_total: actions.length, title, text,
      console_messages: consoleMessages, page_errors: pageErrors,
      failed_requests: failedRequests, screenshots,
    }));
  } finally { await browser.close(); }
}

main().catch(e => {
  console.log(JSON.stringify({ok: false, nav_error: String(e && e.message || e), last_error: null,
    actions_done: 0, actions_total: 0, title: '', text: '', console_messages: [],
    page_errors: [], failed_requests: [], screenshots: []}));
  process.exit(0);
});
"""

_MUTATING_ACTIONS = ("click", "type", "press")
# Found live, 2026-09-09: this list originally read
# `pass|secret|token|otp|cvv|card|ssn` and every one of these ordinary,
# real-world field names slipped straight through with no refusal at
# all -- `#pwd`, `#pw`, `input[name=pw]`, `#login_pwd`, `#apikey`,
# `#api_key`, `#pin`, `#bank_account`, `#iban`, `#security_code`. None
# of those are adversarial tricks; they're just how real login and
# payment forms name their fields. This can never be a complete list --
# that's inherent to a name-based heuristic -- but it should at least
# catch the common abbreviations it was clearly trying to.
_SECRET_SELECTOR = re.compile(
    r"pass|pwd|pw\b|secret|token|api[_-]?key|otp|pin\b|cvv|cvc|card|ssn|iban|"
    r"account|routing|security[_-]?code",
    re.I,
)
# ("pw\b"/"pin\b" so we do not also refuse ordinary words like "spawn"
# or "spinner" that merely contain "pw"/"pin" as a substring.)
_MAX_ACTIONS = 20


def classify_actions(actions: list) -> str:
    """`""` when the actions are safe to run, otherwise the refusal.

    Deliberately absent: any `evaluate`/run-JS action. A JS string
    inside a JSON argument would be code Guardian's `code`/`command`
    rules never see -- the whole static-analysis layer routed around by
    a field name.
    """
    if not isinstance(actions, list):
        return "refused: actions must be a list"
    if len(actions) > _MAX_ACTIONS:
        return f"refused: at most {_MAX_ACTIONS} actions per call"
    allowed = {"click", "type", "press", "wait", "screenshot", "scroll"}
    for action in actions:
        if not isinstance(action, dict) or len(action) != 1:
            return f"refused: each action is one key, got {action!r}"
        key, value = next(iter(action.items()))
        if key not in allowed:
            return f"refused: {key!r} is not an allowed action ({', '.join(sorted(allowed))})"
        if key == "type":
            if not isinstance(value, list) or len(value) != 2:
                return "refused: type takes [selector, text]"
            selector, text = str(value[0]), str(value[1])
            # Sim never types a credential into a page. The selector is
            # the honest signal available here -- the text itself could
            # be anything, and guessing at it would be worse.
            if _SECRET_SELECTOR.search(selector):
                return f"refused: {selector!r} looks like a credential field"
            if len(text) > 2000:
                return "refused: that is too much text to type"
        if key in ("click", "wait") and isinstance(value, str):
            if len(value) > 200 or value.lower().startswith("javascript:"):
                return f"refused: {value[:60]!r} is not a usable selector"
        if key == "screenshot" and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(value)):
            return "refused: a screenshot name may only be letters, digits, _ and -"
    return ""


def mutates(actions: list) -> bool:
    return any(isinstance(a, dict) and set(a) & set(_MUTATING_ACTIONS) for a in actions or [])


class BrowsePageTool(RenderPageTool):
    """`render_page` with hands: click, type, wait, scroll, screenshot.

    Shares the whole target-resolution and safety story with its parent
    -- SSRF guard for a URL, `pathsafety` for a local file -- and adds
    only the action loop. `reversible` when the actions can change
    something on the page, `read_only` when they cannot: a click on a
    public page can post, and Guardian should see that difference even
    though the creator's auto-approve currently waves both through.
    """

    name = "browse_page"
    description = (
        "Load a page in a real headless browser and interact with it: click, type, wait, scroll, "
        "screenshot. Reports the same errors as render_page plus what it managed to do."
    )
    read_only = False
    reversibility = "reversible"
    args_schema = {
        "type": "object", "required": ["target"],
        "properties": {"target": {"type": "string"}, "actions": {"type": "array"}},
    }

    async def run(self, args: dict, *, ctx: ToolContext) -> ToolResult:
        import asyncio

        if not self._node:
            return ToolResult(ok=False, error="refused: no `node` executable found on this machine")
        if not self._node_module_path:
            return ToolResult(ok=False, error="refused: could not locate Puppeteer's global node_modules (is it installed?)")
        actions = args.get("actions") or []
        refusal = classify_actions(actions)
        if refusal:
            return ToolResult(ok=False, error=refusal)
        target = str(args["target"]).strip()
        try:
            url = self._resolve_target(target)
        except FetchRefused as exc:
            return ToolResult(ok=False, error=str(exc))

        timeout = min(ctx.constraints.get("timeout_s", self._config.render_page_timeout_s),
                      self._config.render_page_timeout_s)
        shots = Path(self._config.repo_root) / self._config.render_screenshot_dir
        shots.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="simorgh-browse-") as workdir:
            driver = Path(workdir) / "browse_driver.js"
            driver.write_text(_BROWSE_DRIVER)
            allow_private = "1" if self._config.render_page_allow_private_networks else "0"
            try:
                completed = await asyncio.to_thread(
                    subprocess.run,
                    [self._node, str(driver), url, str(int(timeout * 1000)),
                     json.dumps(actions), str(shots), allow_private],
                    capture_output=True, text=True, cwd=workdir,
                    env={"NODE_PATH": self._node_module_path}, timeout=timeout + 15.0,
                    stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired as exc:
                return ToolResult(ok=False, output=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                                  error="timeout", metadata={"duration_s": time.monotonic() - start})
            if completed.returncode != 0:
                return ToolResult(ok=False, error=f"browse process exited {completed.returncode}",
                                  metadata={"stderr": completed.stderr})
            try:
                payload = json.loads(completed.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                return ToolResult(ok=False, error="browse process produced no parseable result",
                                  metadata={"stdout": completed.stdout, "stderr": completed.stderr})

        text = str(payload.get("text") or "")[: self._config.render_page_max_chars]
        ok = bool(payload.get("ok"))
        summary = render_summary(target, payload, text)
        done, total = payload.get("actions_done", 0), payload.get("actions_total", 0)
        if total:
            summary = f"{summary}\nactions: {done}/{total} done"
            if payload.get("last_error"):
                summary += f"\nstopped at: {payload['last_error']}"
        if payload.get("screenshots"):
            summary += "\nscreenshots: " + ", ".join(payload["screenshots"])
        return ToolResult(
            ok=ok, output=summary,
            error=None if ok else (payload.get("nav_error") or payload.get("last_error") or "browse failed"),
            metadata={
                "title": payload.get("title", ""), "actions_done": done, "actions_total": total,
                "screenshots": payload.get("screenshots", []),
                "page_errors": payload.get("page_errors", []),
                "console_messages": payload.get("console_messages", []),
                "failed_requests": payload.get("failed_requests", []),
                "duration_s": time.monotonic() - start,
            },
        )
