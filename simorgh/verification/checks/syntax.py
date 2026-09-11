"""`syntax`: `ast.parse` for the Python this task wrote.

It applied only when the subject carried a `candidate`/`code` string --
which only Learning's `PatchPipeline` ever sets, and that pipeline is
unreachable from a real task (see `fullsuiteran.py`'s own docstring on
the same shape). So the check that catches a syntax error in Sim's own
source had never once run on a real patch: every Python file written by
an ordinary task went unparsed, while the JavaScript equivalent
(`js_syntax`, added 2026-09-09) checked every page. Found by wave-21
observer W21-03.

It now also reads the files the session actually wrote, the same way
the non-Python checks do (`_files.py`). The `candidate` path stays for
the pipeline that populates it.
"""

from __future__ import annotations

import ast

from ..api import CheckContext, CheckResult, VerifyRequest
from ._files import read_repo_file, repo_root_of, written_paths


_PY_SUFFIXES = (".py",)


def _candidate_source(req: VerifyRequest) -> str | None:
    return req.subject.get("candidate") or req.subject.get("code")


def _written_python(req: VerifyRequest) -> list[tuple[str, str]]:
    """`(path, source)` for each Python file this session wrote and that
    can still be read back."""
    out = []
    for path in written_paths(req, suffixes=_PY_SUFFIXES):
        text = read_repo_file(path, root=repo_root_of(req))
        if text is not None:
            out.append((path, text))
    return out


class SyntaxCheck:
    name = "syntax"
    cost = "free"

    def applies(self, req: VerifyRequest) -> bool:
        return _candidate_source(req) is not None or bool(
            written_paths(req, suffixes=_PY_SUFFIXES))

    async def run(self, req: VerifyRequest, ctx: CheckContext) -> CheckResult:
        units: list[tuple[str, str]] = []
        candidate = _candidate_source(req)
        if candidate is not None:
            units.append(("candidate", candidate))
        units.extend(_written_python(req))
        if not units:
            return CheckResult(status="skipped", detail="no readable Python was written")

        failures = []
        for label, source in units:
            try:
                ast.parse(source)
            except SyntaxError as exc:
                failures.append(f"{label}: {exc}")
        if failures:
            joined = "; ".join(failures)
            return CheckResult(
                status="failed",
                detail=f"not valid Python: {joined}",
                evidence={"errors": failures},
            )
        return CheckResult(
            status="passed",
            detail=f"{len(units)} Python file(s) parse" if len(units) > 1
                   else "candidate parses as valid Python",
        )
