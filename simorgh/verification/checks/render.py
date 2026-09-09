"""`render`: open the page in a real browser and see whether it works.

`js_syntax` proves the script parses. That is not the same as the page
working: a `TypeError` on the first frame, a canvas that is never
found, a library used before it loads -- all parse perfectly and all
leave the user with a blank rectangle. `render_page` (Puppeteer,
headless Chromium) reports what a person opening the file would
actually hit, and this check fails the verification on it.

Expensive by cost class (it launches a browser, ~1.5s), so it runs
last, after the free and cheap checks have already had their say.

Two deliberate leniencies:

- A **failed network request** is reported in the detail but does not
  fail the check on its own. A page that pulls Three.js from a CDN
  fails that request on a machine with no network, and refusing to
  verify offline would be a worse bug than the one this catches.
  Same-origin (`file://`) failures DO fail: those are the page's own
  missing files.
- **No browser, no opinion.** If Puppeteer or Node is absent the check
  skips. It never fails a task for the machine's missing optional
  dependency.
"""

from __future__ import annotations

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest
from ._files import written_paths

_HTML_SUFFIXES = (".html", ".htm")
_UNAVAILABLE = ("no `node` executable", "could not locate Puppeteer")


class RenderCheck:
    name = "render"
    cost = "expensive"

    def applies(self, req: VerifyRequest) -> bool:
        return bool(written_paths(req, suffixes=_HTML_SUFFIXES))

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        paths = written_paths(req, suffixes=_HTML_SUFFIXES)
        failures: list[str] = []
        warnings: list[str] = []
        rendered = 0
        for path in paths:
            result = await ctx.act("render_page", {"target": path})
            error = result.error or ""
            if any(marker in error for marker in _UNAVAILABLE):
                return CheckResult(status="skipped", detail=f"no headless browser available: {error}")
            if error == "timeout":
                return CheckResult(status="insufficient", detail="the render did not answer in time")
            if not result.ok:
                failures.append(f"{path} did not render: {error}")
                continue
            rendered += 1
            metadata = result.metadata or {}
            for message in metadata.get("page_errors") or []:
                failures.append(f"{path}: uncaught {message}")
            for message in metadata.get("console_messages") or []:
                if str(message).startswith("error:"):
                    failures.append(f"{path}: console.{message}")
            for request in metadata.get("failed_requests") or []:
                text = str(request)
                if text.startswith("file://"):
                    failures.append(f"{path}: missing local file {text}")
                else:
                    warnings.append(f"{path}: {text}")

        if not rendered and not failures:
            return CheckResult(status="skipped", detail="no page could be rendered")
        if failures:
            joined = "; ".join(failures[:5])
            return CheckResult(
                status="failed", detail=f"the page does not run cleanly in a browser: {joined}",
                evidence={"failures": failures, "warnings": warnings},
                feedback=Feedback(
                    mechanical_errors=tuple(failures[:5]),
                    revise_hint="open the page's own logic: the error above happens on load, so the page "
                                "is broken for anyone who opens it -- fix it and rewrite the whole file",
                    retryable=True,
                ),
            )
        detail = f"{rendered} page(s) rendered with no JS errors"
        if warnings:
            detail += f" ({len(warnings)} external request(s) failed -- offline or a bad CDN URL)"
        return CheckResult(status="passed", detail=detail, evidence={"warnings": warnings})
