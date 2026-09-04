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
# Generously above any real path in this repository -- exists purely to
# refuse an obviously-malformed "path" (a hallucinated multi-KB blob)
# before ever touching the filesystem with it.
_MAX_PATH_CHARS = 500

_DEFAULT_PREVIEW_LIMIT = 150


def preview(text: str, limit: int = _DEFAULT_PREVIEW_LIMIT) -> str:
    """A bounded, single-line-safe preview of a marker payload, for
    console narration and log display -- never the full payload used for
    the real work (safe_read_file, the audit gate, activity-log storage
    all still see the untruncated value; this is display-only).

    Caught live: a confused model emitted a "READ:" marker whose payload
    was really a 27,000-character hallucinated multi-turn transcript
    (embedding fake "READ:"/nothing-was-returned exchanges) rather than a
    real path. Every narration line printed that verbatim -- an
    unbounded, unformatted wall of text -- because nothing between
    parse_marker() and the print() call ever bounded it. Collapsing
    newlines first means even a malformed multi-line payload stays a
    single terminal line.
    """
    collapsed = text.replace("\r\n", " ").replace("\n", " ⏎ ").strip()
    if len(collapsed) > limit:
        return collapsed[:limit] + f"… (+{len(collapsed) - limit} more chars)"
    return collapsed


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

    That "never raises" guarantee is enforced explicitly, not assumed:
    caught live, a confused model's "READ:" payload was really a huge
    (50,000+ character) hallucinated blob, and `Path.is_file()` raised a
    raw `OSError: [Errno 63] File name too long` -- nothing here used to
    catch that, and it crashed the entire CLI process mid-batch. A
    length check up front refuses the obvious case before ever touching
    the filesystem; the try/except below is the second, unconditional
    layer, since a filename can be "too long" (or otherwise invalid) in
    OS- and filesystem-specific ways this function shouldn't have to
    enumerate.
    """
    if len(raw_path) > _MAX_PATH_CHARS:
        return f"[refused: path is {len(raw_path)} chars -- too long to be a real path]"
    try:
        rel = Path(raw_path)
    except ValueError as exc:
        return f"[refused: {raw_path!r} is not a valid path: {exc!r}]"

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

    try:
        resolved_root = repo_root.resolve()
        target = (resolved_root / rel).resolve()
        if resolved_root != target and resolved_root not in target.parents:
            return f"[refused: {raw_path!r} resolves outside the repository]"
        if not target.is_file():
            return f"[refused: {raw_path!r} is not a file]"
        content = target.read_text(errors="replace")
    except OSError as exc:
        return f"[refused: could not read {raw_path!r}: {exc!r}]"

    if len(content) > _MAX_READ_CHARS:
        return content[:_MAX_READ_CHARS] + f"\n...[truncated, {len(content)} chars total]"
    return content


_MAX_LIST_ENTRIES = 300


def safe_list_dir(repo_root: Path, raw_path: str) -> str:
    """List the immediate entries under `raw_path`, subject to the exact
    same boundary as safe_read_file (confined to src/docs/tests, no
    traversal, never raises). An empty path or "." lists the allowed
    top-level roots themselves.

    Caught live: asked to "read your code base and point to gaps in
    your design," Sim's only way to see what files even exist was RUN
    (a sandboxed `os.listdir`) -- but SubprocessSandbox executes in an
    isolated temp directory, not the real repository, so every attempt
    saw nothing and Sim fumbled through several failed workarounds
    before answering from memory alone. READ already lets it look inside
    a file it already knows the path to; this is the missing step
    before that -- discovering the path in the first place -- without
    granting anything READ doesn't already: still read-only, still
    confined to the same three roots, still no traversal.
    """
    raw = raw_path.strip()
    if not raw or raw == ".":
        return "\n".join(f"{name}/" for name in _ALLOWED_READ_ROOTS)

    if len(raw) > _MAX_PATH_CHARS:
        return f"[refused: path is {len(raw)} chars -- too long to be a real path]"
    try:
        rel = Path(raw)
    except ValueError as exc:
        return f"[refused: {raw!r} is not a valid path: {exc!r}]"

    if rel.is_absolute() or ".." in rel.parts:
        return f"[refused: {raw!r} is not a safe relative path]"
    if not rel.parts or rel.parts[0] not in _ALLOWED_READ_ROOTS:
        return (
            f"[refused: {raw!r} is outside the readable areas "
            f"({', '.join(_ALLOWED_READ_ROOTS)})]"
        )

    try:
        resolved_root = repo_root.resolve()
        target = (resolved_root / rel).resolve()
        if resolved_root != target and resolved_root not in target.parents:
            return f"[refused: {raw!r} resolves outside the repository]"
        if not target.is_dir():
            return f"[refused: {raw!r} is not a directory]"
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
    except OSError as exc:
        return f"[refused: could not list {raw!r}: {exc!r}]"

    names: list[str] = []
    for entry in entries:
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        names.append(f"{entry.name}/" if entry.is_dir() else entry.name)
        if len(names) >= _MAX_LIST_ENTRIES:
            names.append(f"... (truncated at {_MAX_LIST_ENTRIES} entries)")
            break
    return "\n".join(names) if names else "[empty directory]"
