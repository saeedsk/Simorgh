"""What a verification actually wrote, and how to read it back.

Every check before 2026-09-09 judged a task from its own prose: the
description, the final answer, and the step summaries. That is enough
to ask "did a write tool run" but not "is the thing it wrote correct",
so a generated `.html` page could carry an unclosed brace or the
model's own trailing commentary through every mechanical gate (both
happened, twice each, in the game trials).

`orchestration/session.py::_put_verify_subject` now sends
`written_paths` (the session's uncommitted + created set) and
`subject`. These helpers turn that into real file content.

The repository root is found the same way `guardian/rules.py` finds it
-- from this file's own location, not from config -- so a check needs
no new wiring, and a test can point it somewhere else by patching
`REPO_ROOT` on this module.
"""

from __future__ import annotations

from pathlib import Path

from ..api import VerifyRequest

REPO_ROOT = Path(__file__).resolve().parents[3]

_MAX_READ_BYTES = 4_000_000


def written_paths(req: VerifyRequest, *, suffixes: tuple[str, ...] = ()) -> list[str]:
    """The repo-relative paths this session wrote, optionally filtered to
    a set of suffixes. `subject` is included when the session named one:
    a task blocked before its write still declares what it was for, and
    a check that only ever looked at `written_paths` would silently pass
    a task whose write never landed."""
    raw = req.subject.get("written_paths") or []
    paths = [str(p) for p in raw if isinstance(p, str) and p]
    subject = req.subject.get("subject")
    if isinstance(subject, str) and subject and subject not in paths:
        paths.append(subject)
    if suffixes:
        paths = [p for p in paths if p.lower().endswith(suffixes)]
    return sorted(dict.fromkeys(paths))


def read_repo_file(path: str) -> str | None:
    """The file's whole text, or None when it cannot be read as text --
    it does not exist (a write that never landed), it escapes the repo,
    or it is binary. None always means "no opinion": a check that cannot
    see the file must skip, never fail, or a task gets blamed for this
    module's blind spot."""
    if not path or Path(path).is_absolute() or ".." in Path(path).parts:
        return None
    try:
        target = (REPO_ROOT / path).resolve()
        target.relative_to(REPO_ROOT.resolve())
    except (ValueError, OSError):
        return None
    try:
        if not target.is_file() or target.stat().st_size > _MAX_READ_BYTES:
            return None
        return target.read_text()
    except (OSError, UnicodeDecodeError):
        return None
