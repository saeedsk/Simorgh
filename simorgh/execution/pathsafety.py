"""Path-safety boundary, ported from src/cognition/tool_protocol.py's
`_resolve_safe_path`/`safe_read_file`/`safe_list_dir` (08-execution.md
section 5, `pathsafety.py`). Same rules: a plain relative path inside
`repo_root`, under one of `readable_roots`, no traversal, no
credential-shaped names -- never raises, always returns an explicit
refusal string instead.
"""

from __future__ import annotations

from pathlib import Path

_CREDENTIAL_LOOKING_NAMES = (".env", "credentials", "secret", "id_rsa", ".pem")
_MAX_PATH_CHARS = 4096
_MAX_READ_CHARS = 20_000
_MAX_LIST_ENTRIES = 300


def resolve_safe_path(
    repo_root: Path, raw_path: str, *, readable_roots: tuple[str, ...], max_path_chars: int = _MAX_PATH_CHARS
) -> tuple[Path | None, str | None]:
    if len(raw_path) > max_path_chars:
        return None, f"refused: path is {len(raw_path)} chars -- too long to be a real path"
    try:
        rel = Path(raw_path)
    except ValueError as exc:
        return None, f"refused: {raw_path!r} is not a valid path: {exc!r}"

    if rel.is_absolute() or ".." in rel.parts:
        return None, f"refused: {raw_path!r} is not a safe relative path"
    if not rel.parts or rel.parts[0] not in readable_roots:
        return None, f"refused: {raw_path!r} is outside the readable areas ({', '.join(readable_roots)})"
    if any(
        name in part.lower() or part.lower().endswith(".key")
        for part in rel.parts
        for name in _CREDENTIAL_LOOKING_NAMES
    ):
        return None, f"refused: {raw_path!r} looks like a credentials path"

    try:
        resolved_root = repo_root.resolve()
        target = (resolved_root / rel).resolve()
        if resolved_root != target and resolved_root not in target.parents:
            return None, f"refused: {raw_path!r} resolves outside the repository"
    except OSError as exc:
        return None, f"refused: could not resolve {raw_path!r}: {exc!r}"
    return target, None


def safe_read_file(repo_root: Path, raw_path: str, *, readable_roots: tuple[str, ...]) -> str:
    target, refusal = resolve_safe_path(repo_root, raw_path, readable_roots=readable_roots)
    if refusal is not None:
        return f"[{refusal}]"
    if not target.is_file():
        return f"[refused: {raw_path!r} is not a file]"
    try:
        content = target.read_text(errors="replace")
    except OSError as exc:
        return f"[refused: could not read {raw_path!r}: {exc!r}]"
    if len(content) > _MAX_READ_CHARS:
        return content[:_MAX_READ_CHARS] + f"\n...[truncated, {len(content)} chars total]"
    return content


def safe_list_dir(repo_root: Path, raw_path: str, *, readable_roots: tuple[str, ...]) -> str:
    if not raw_path or raw_path == ".":
        return "\n".join(readable_roots)
    target, refusal = resolve_safe_path(repo_root, raw_path, readable_roots=readable_roots)
    if refusal is not None:
        return f"[{refusal}]"
    if not target.is_dir():
        return f"[refused: {raw_path!r} is not a directory]"
    try:
        entries = sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir())
    except OSError as exc:
        return f"[refused: could not list {raw_path!r}: {exc!r}]"
    if len(entries) > _MAX_LIST_ENTRIES:
        entries = entries[:_MAX_LIST_ENTRIES] + [f"...({len(entries) - _MAX_LIST_ENTRIES} more)"]
    return "\n".join(entries)


def in_write_scope(raw_path: str, *, write_scopes: tuple[str, ...]) -> bool:
    return any(raw_path.startswith(scope) for scope in write_scopes) and ".." not in Path(raw_path).parts
