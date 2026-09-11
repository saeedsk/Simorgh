"""`trailing_narration`: the model kept talking, and its commentary
became part of the file.

`cognition/parser.py`'s code-bearing markers keep "everything after the
marker" as the payload -- a deliberate trade-off, since a program has
no reliable end delimiter. The cost, live twice on 2026-09-09: the
committed `docs/games/breakout.html` ended with "Note:
apply_source_patch is scoped to src/ or simorgh/, but this path was
explicitly requested; proceeding." *after* `</html>`, and the 3D maze
had "Now let me run the test suite.\n\nRUN_TESTS:" in the same place.
Both passed every mechanical check, because no check ever opened the
file.

Free and purely mechanical: text after the last `</html>` in an HTML
file is never legitimate. For Python the generic `SyntaxCheck` already
catches the resulting parse error; this check exists to say *why* it
happened, because "invalid syntax at line 340" sends the model looking
for a bug in its own code instead of at the prose it appended.
"""

from __future__ import annotations

import ast

from ..api import CheckContext, CheckResult, Feedback, VerifyRequest
from ._files import read_repo_file, repo_root_of, written_paths

_HTML_SUFFIXES = (".html", ".htm")
_PY_SUFFIXES = (".py",)
_HINT = (
    "the marker keeps EVERYTHING after it as the file's content, so end your reply at the "
    "last line of the file itself -- no commentary, no next-step note, no second marker"
)


def html_tail(text: str) -> str:
    """Whatever follows the last `</html>`, stripped. Empty when the file
    ends where it should (or has no `</html>` at all -- a fragment is
    somebody else's problem, not this check's)."""
    lowered = text.lower()
    index = lowered.rfind("</html>")
    if index == -1:
        return ""
    return text[index + len("</html>"):].strip()


def python_prose_tail(text: str) -> str:
    """The trailing prose that makes an otherwise-valid module fail to
    parse, or empty. Conservative by construction: it only reports when
    dropping the tail actually makes the file parse, so a real syntax
    bug in real code is never mislabelled as narration."""
    try:
        ast.parse(text)
        return ""
    except SyntaxError as exc:
        line = exc.lineno or 0
    lines = text.splitlines()
    if line <= 1 or line > len(lines):
        return ""
    head = "\n".join(lines[: line - 1])
    try:
        ast.parse(head)
    except SyntaxError:
        return ""
    tail = "\n".join(lines[line - 1:]).strip()
    return tail


class TrailingNarrationCheck:
    name = "trailing_narration"
    cost = "free"

    def applies(self, req: VerifyRequest) -> bool:
        return bool(written_paths(req, suffixes=_HTML_SUFFIXES + _PY_SUFFIXES))

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        offenders: list[tuple[str, str]] = []
        read_any = False
        for path in written_paths(req, suffixes=_HTML_SUFFIXES + _PY_SUFFIXES):
            text = read_repo_file(path, root=repo_root_of(req))
            if text is None:
                continue
            read_any = True
            tail = html_tail(text) if path.lower().endswith(_HTML_SUFFIXES) else python_prose_tail(text)
            if tail:
                offenders.append((path, tail[:200]))
        if not read_any:
            return CheckResult(status="skipped", detail="none of the written files could be read back")
        if not offenders:
            return CheckResult(status="passed", detail="no commentary after the end of any written file")
        detail = "; ".join(f"{path} has text after the file ends: {tail!r}" for path, tail in offenders)
        return CheckResult(
            status="failed", detail=detail,
            evidence={"files": [p for p, _ in offenders], "tail": offenders[0][1]},
            feedback=Feedback(mechanical_errors=(detail,), revise_hint=_HINT, retryable=True),
        )
