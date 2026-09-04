"""Shared, reviewed helpers for the marker-based tool protocol used
wherever an LLM is given bounded, single-action-per-turn tool access in
this codebase (SkillResearchAgent in src/agents/skills/research.py, and
LogicAgent in src/agents/logic/base.py).

Kept in one place specifically so every caller enforces the exact same
READ safety boundary -- confined to this repository's own tracked source,
no traversal, no credential-shaped names -- rather than each maintaining
its own copy that could drift out of sync with the others.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_CODE_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)

_ALLOWED_READ_ROOTS = ("src", "docs", "tests")
_MAX_READ_CHARS = 20_000
_CREDENTIAL_LOOKING_NAMES = (".env", "secrets", "credentials")


def parse_marker(text: str, markers: tuple[str, ...]) -> tuple[str | None, str]:
    """If `text` (stripped) starts with one of `markers` (each given
    without a trailing colon, matched case-insensitively followed by ':'),
    returns (marker.lower(), payload). Otherwise returns (None, text) --
    the whole stripped text, meaning "no tool call, this is a final
    answer."
    """
    stripped = text.strip()
    for marker in markers:
        prefix = f"{marker}:"
        if stripped[: len(prefix)].upper() == prefix.upper():
            return marker.lower(), stripped[len(prefix) :].strip()
    return None, stripped


def extract_code(text: str) -> str | None:
    """Strip a markdown code fence if the model wrapped its answer in one;
    otherwise use the text as-is. Returns None for empty input.
    """
    match = _CODE_FENCE.search(text)
    stripped = (match.group(1) if match else text).strip()
    return stripped or None


def is_valid_python(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    return True


def safe_read_file(repo_root: Path, raw_path: str) -> str:
    """Read `raw_path` if -- and only if -- it resolves to a plain
    relative path inside `repo_root`, under src/, docs/, or tests/, and
    doesn't look like a credentials file. Read-only; never writes; never
    raises -- returns a "[refused: ...]" string on any problem, so a
    caller can always feed the result straight back into a prompt without
    a try/except of its own.
    """
    rel = Path(raw_path)
    if rel.is_absolute() or ".." in rel.parts:
        return f"[refused: {raw_path!r} is not a safe relative path]"
    if not rel.parts or rel.parts[0] not in _ALLOWED_READ_ROOTS:
        return (
            f"[refused: {raw_path!r} is outside the readable areas "
            f"({', '.join(_ALLOWED_READ_ROOTS)})]"
        )
    if any(
        name in part.lower() or part.lower().endswith(".key")
        for part in rel.parts
        for name in _CREDENTIAL_LOOKING_NAMES
    ):
        return f"[refused: {raw_path!r} looks like a credentials path]"

    resolved_root = repo_root.resolve()
    target = (resolved_root / rel).resolve()
    if resolved_root != target and resolved_root not in target.parents:
        return f"[refused: {raw_path!r} resolves outside the repository]"
    if not target.is_file():
        return f"[refused: {raw_path!r} is not a file]"

    try:
        content = target.read_text(errors="replace")
    except OSError as exc:
        return f"[refused: could not read {raw_path!r}: {exc!r}]"

    if len(content) > _MAX_READ_CHARS:
        return content[:_MAX_READ_CHARS] + f"\n...[truncated, {len(content)} chars total]"
    return content
