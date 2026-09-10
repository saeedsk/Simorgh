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
_TYPE_ATTR = re.compile(r"""\btype\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<bare>[^\s"'>]+))""", re.I)
_NO_NODE = "no `node` executable"

# `new Function(body)` compiles `body` as a plain function body -- it has
# no opinion at all about non-JS content a page legitimately embeds in a
# <script> tag:
#   - `type="module"`: `import`/`export` are only legal at a module's top
#     level, never inside a Function body, so ANY real ES module script
#     -- valid or not -- throws `Cannot use import statement outside a
#     module` here. Live-checked, 2026-09-09: `new
#     Function("import {x} from './m.js'; console.log(x);")` fails even
#     though the script is fine.
#   - `type="application/json"` / `application/ld+json`: JSON-LD
#     structured data is one of the most common non-`src=` script bodies
#     on the web (schema.org markup), and `{"a": 1}` is not a valid
#     function body (`Unexpected token ':'`) even though it is perfectly
#     valid JSON.
#   - any other non-JS `type` (a client-side template body -- Handlebars,
#     `text/x-template`, etc.) is not JavaScript at all.
# An empty/missing `type`, or an explicit JS mimetype, is the only case
# this check has any business judging.
_JS_TYPES = frozenset({
    "", "text/javascript", "application/javascript", "application/ecmascript",
    "text/ecmascript", "application/x-javascript",
})


def _script_type(attrs: str) -> str:
    match = _TYPE_ATTR.search(attrs or "")
    if not match:
        return ""
    return (match.group("dq") or match.group("sq") or match.group("bare") or "").strip().lower()


# A `</script>` inside a JS string literal ends the tag as far as the
# HTML parser -- and this regex -- is concerned; that is genuinely how
# HTML works, which is why the idiom for embedding one is `<\/script>`.
# But a page that writes the literal anyway (inside a template string,
# say) has its body cut mid-string, and this check reported perfectly
# fine JavaScript as broken (W21-03).
#
# The discriminator is deliberately NOT "do the braces balance". An
# unclosed IIFE -- the live 2026-09-09 `snake.html` failure this whole
# check exists to catch -- is unbalanced too, so skipping on that would
# switch the check off for exactly its founding case. What truncation at
# a `</script>` leaves behind and a genuinely-unclosed function does not
# is an UNTERMINATED STRING LITERAL: the cut lands inside the quotes.
# snake.html's strings were all closed; it just ran out of braces.
#
# So: skip a body that ends inside an open quote, judge everything else.
# Scanning is single-pass and quote-aware enough to not be fooled by
# escapes or by quotes inside comments, which is as far as this check
# needs to go (a real answer needs a tokenizer, and the cost of being
# wrong here is one skipped check, not a wrong verdict).
def ends_inside_a_string(body: str) -> bool:
    quote = ""          # the character that would close the open literal
    comment = ""        # "" | "//" | "/*"
    index, length = 0, len(body)
    while index < length:
        char = body[index]
        if comment == "//":
            if char == "\n":
                comment = ""
        elif comment == "/*":
            if char == "*" and body[index + 1: index + 2] == "/":
                comment, index = "", index + 1
        elif quote:
            if char == "\\":
                index += 1                      # whatever follows is escaped
            elif char == quote:
                quote = ""
            elif quote != "`" and char == "\n":
                # Only a template literal may span lines; a broken '...'
                # or "..." ends at the newline rather than staying open.
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == "/" and body[index + 1: index + 2] in ("/", "*"):
            comment, index = "/" + body[index + 1], index + 1
        index += 1
    return bool(quote)


def script_bodies(html: str) -> list[str]:
    """Every inline `<script>` body in the document this check can form
    an opinion about. A `src=` script has no body of ours to check (it
    is a CDN library, and `RenderCheck` is the one that notices when it
    fails to load); a non-JS `type` (a module, JSON-LD, a template) is
    real content this check cannot parse as a function body without
    mislabelling it broken -- see `_JS_TYPES`."""
    bodies = []
    for match in _SCRIPT_BLOCK.finditer(html or ""):
        attrs = match.group("attrs") or ""
        if _SRC_ATTR.search(attrs):
            continue
        if _script_type(attrs) not in _JS_TYPES:
            continue
        body = (match.group("body") or "").strip()
        if body and not ends_inside_a_string(body):
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
