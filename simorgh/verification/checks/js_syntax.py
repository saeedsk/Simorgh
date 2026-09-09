"""`js_syntax`: the JavaScript half of `SyntaxCheck`.

`SyntaxCheck` runs `ast.parse`, so it has an opinion about Python and
none at all about anything else. Live cost, 2026-09-09: Sim generated
`snake.html` whose IIFE was never closed -- the file simply ended after
`setInterval(step,110);` -- and the page was committed, verified, and
reported as done. A human opened it and got `Uncaught SyntaxError:
Unexpected end of input`. Nothing in the pipeline had ever asked
whether the JavaScript parsed.

Parse only, never execute: each script body is wrapped in
`new Function(<body>)`, which compiles it and throws on a syntax error
without running a line of it. The wrapping happens inside the sandbox
payload, and the body travels as a JSON string literal, so a body
containing quotes, backticks or `</script>` cannot break out of it.

Skips itself (never fails) when `run_js_sandboxed` reports no Node on
the machine -- a missing optional runtime must not block a task.
"""

from __future__ import annotations

import json
import re

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest
from ._files import read_repo_file, written_paths

_JS_SUFFIXES = (".js", ".mjs")
_HTML_SUFFIXES = (".html", ".htm")
_SCRIPT_BLOCK = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", re.S | re.I)
_SRC_ATTR = re.compile(r"\bsrc\s*=", re.I)
_NO_NODE = "no `node` executable"


def script_bodies(html: str) -> list[str]:
    """Every inline `<script>` body in the document. A `src=` script has
    no body of ours to check (it is a CDN library, and `RenderCheck` is
    the one that notices when it fails to load)."""
    bodies = []
    for match in _SCRIPT_BLOCK.finditer(html or ""):
        if _SRC_ATTR.search(match.group("attrs") or ""):
            continue
        body = (match.group("body") or "").strip()
        if body:
            bodies.append(body)
    return bodies


def _probe(body: str) -> str:
    """A Node program that compiles `body` and prints nothing on success."""
    return f"new Function({json.dumps(body)});"


class JsSyntaxCheck:
    name = "js_syntax"
    cost = "cheap"

    def applies(self, req: VerifyRequest) -> bool:
        return bool(written_paths(req, suffixes=_JS_SUFFIXES + _HTML_SUFFIXES))

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        units: list[tuple[str, str]] = []  # (label, body)
        for path in written_paths(req, suffixes=_JS_SUFFIXES + _HTML_SUFFIXES):
            text = read_repo_file(path)
            if text is None:
                continue
            if path.lower().endswith(_HTML_SUFFIXES):
                units.extend(
                    (f"{path} script #{i}", body) for i, body in enumerate(script_bodies(text), start=1)
                )
            else:
                units.append((path, text))
        if not units:
            return CheckResult(status="skipped", detail="no readable JavaScript in the written files")

        failures: list[str] = []
        for label, body in units:
            result = await ctx.act("run_js_sandboxed", {"code": _probe(body)})
            if result.ok:
                continue
            detail = f"{result.error or ''} {(result.metadata or {}).get('stderr', '')}".strip()
            if _NO_NODE in detail or _NO_NODE in (result.error or ""):
                return CheckResult(status="skipped", detail="node is not available to check JavaScript")
            if result.error == "timeout":
                return CheckResult(status="insufficient", detail="the JavaScript syntax check did not answer in time")
            failures.append(f"{label}: {_first_error_line(detail)}")

        if not failures:
            return CheckResult(status="passed", detail=f"{len(units)} script(s) parse as valid JavaScript")
        joined = "; ".join(failures)
        return CheckResult(
            status="failed", detail=f"invalid JavaScript: {joined}",
            evidence={"failures": failures},
            feedback=Feedback(
                mechanical_errors=(joined,),
                revise_hint="fix the JavaScript syntax error and rewrite the whole file -- "
                            "'Unexpected end of input' means a brace, bracket or paren is never closed",
                retryable=True,
            ),
        )


def _first_error_line(detail: str) -> str:
    for line in (detail or "").splitlines():
        stripped = line.strip()
        if "Error" in stripped:
            return stripped[:200]
    return (detail or "unknown error").strip()[:200]
