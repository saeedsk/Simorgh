"""Path-safety boundary, ported from src/cognition/tool_protocol.py's
`_resolve_safe_path`/`safe_read_file`/`safe_list_dir` (08-execution.md
section 5, `pathsafety.py`). Same rules: a plain relative path inside
`repo_root`, under one of `readable_roots`, no traversal, no
credential-shaped names -- never raises, always returns an explicit
refusal string instead.
"""

from __future__ import annotations

from pathlib import Path

from .pdftext import looks_like_pdf, pdf_to_text

_CREDENTIAL_LOOKING_NAMES = (".env", "credentials", "secret", "id_rsa", ".pem")
_MAX_PATH_CHARS = 4096
_MAX_READ_CHARS = 20_000
# A hard stop so a pathological file cannot be slurped into memory. Far
# above any source file; this is a guard, not a policy.
_MAX_FILE_BYTES = 8_000_000
# A PDF's bytes are mostly fonts and images, so the cap that protects
# against a huge *text* file refuses ordinary papers: three in `papers/`
# are over 8 MB and one is 17 MB. What matters is how much text comes
# out, and `pdf_to_text`'s page limit already bounds that.
_MAX_PDF_BYTES = 60_000_000
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


def read_source(repo_root: Path, raw_path: str, *, readable_roots: tuple[str, ...]) -> tuple[str, str]:
    """`(text, refusal)` -- the file's WHOLE content, uncapped.

    The capping belongs to the caller, because how much to return
    depends on whether a line range was asked for. Slicing a
    pre-capped string was the 2026-09-08 bug: everything past
    `_MAX_READ_CHARS` became unreachable by any range, so 61% of
    `execution/tools.py` could not be read at all and `read_file`
    reported the file as 433 lines instead of 1101."""
    target, refusal = resolve_safe_path(repo_root, raw_path, readable_roots=readable_roots)
    if refusal is not None:
        return "", f"[{refusal}]"
    if not target.is_file():
        return "", f"[refused: {raw_path!r} is not a file]"
    try:
        size = target.stat().st_size
        if size > _MAX_FILE_BYTES:
            with target.open("rb") as handle:
                is_pdf = looks_like_pdf(handle.read(1024))
            cap = _MAX_PDF_BYTES if is_pdf else _MAX_FILE_BYTES
            if size > cap:
                return "", f"[refused: {raw_path!r} is larger than {cap // 1_000_000} MB]"
        data = target.read_bytes()
        # The creator added `papers/` -- papers on self-learning AI, for
        # Sim to read -- and `read_file` returned binary noise for every
        # one of them. A PDF becomes its text here, so the rest of the
        # read path (capping, line ranges, numbering) works on a PDF
        # exactly as it works on source (2026-09-08).
        if looks_like_pdf(data):
            text, problem = pdf_to_text(data, source=raw_path)
            if problem and not text:
                return "", f"[{problem}]"
            return (f"[{problem}]\n\n{text}" if problem else text), ""
        return data.decode(errors="replace"), ""
    except OSError as exc:
        return "", f"[refused: could not read {raw_path!r}: {exc!r}]"


def safe_read_file(repo_root: Path, raw_path: str, *, readable_roots: tuple[str, ...]) -> str:
    content, refusal = read_source(repo_root, raw_path, readable_roots=readable_roots)
    if refusal:
        return refusal
    if len(content) > _MAX_READ_CHARS:
        # Say how much is left AND how to get it. The old marker gave a
        # char count with no way to act on it.
        total_lines = len(content.splitlines())
        shown = content[:_MAX_READ_CHARS]
        seen_lines = len(shown.splitlines())
        return shown + (
            f"\n...[truncated at {_MAX_READ_CHARS} of {len(content)} chars; "
            f"you have seen lines 1-{seen_lines} of {total_lines}. "
            f"Read the rest with {raw_path}:{seen_lines + 1}-{total_lines}]"
        )
    return content


def safe_read_lines(repo_root: Path, raw_path: str, *, start: int, end: int,
                    readable_roots: tuple[str, ...]) -> str:
    """Lines `start`..`end` (1-based, inclusive) of a file, numbered.

    Reads the real file and slices BY LINE, so any part of any file is
    reachable and the reported total is the true one."""
    content, refusal = read_source(repo_root, raw_path, readable_roots=readable_roots)
    if refusal:
        return refusal
    lines = content.splitlines()
    total = len(lines)
    if start > total:
        return f"[lines {start}-{end} are past the end; {raw_path} has {total} lines]"
    chunk = lines[start - 1:end]
    numbered = "\n".join(f"{start + i:5d}| {line}" for i, line in enumerate(chunk))
    if len(numbered) > _MAX_READ_CHARS:
        kept = numbered[:_MAX_READ_CHARS].rsplit("\n", 1)[0]
        last = start + kept.count("\n")
        return (
            f"[lines {start}-{last} of {total} in {raw_path}, cut to fit]\n{kept}"
            f"\n...[ask for {raw_path}:{last + 1}-{end} to continue]"
        )
    return f"[lines {start}-{start + len(chunk) - 1} of {total} in {raw_path}]\n{numbered}"


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
