"""Path-safety boundary, ported from src/cognition/tool_protocol.py's
`_resolve_safe_path`/`safe_read_file`/`safe_list_dir` (08-execution.md
section 5, `pathsafety.py`). Same rules: a plain relative path inside
`repo_root`, under one of `readable_roots`, no traversal, no
credential-shaped names -- never raises, always returns an explicit
refusal string instead.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Iterable

from .doctext import document_to_text
from .pdftext import looks_like_pdf, pdf_to_text

# What a credential file actually looks like, as opposed to what a
# credential file's name contains. The old rule was a substring test
# over every path segment, and it hid Sim's own source from Sim:
# `simorgh/kernel/secrets.py` and its test were unreadable, all three
# `simorgh/contracts/schema/world.env.*.json` schemas matched on the
# ".env" inside "world.env.query", and even `docs/secrets-design.md`
# was refused. `search_code` skipped the same files, so Sim could not
# grep for a symbol defined in its own secret store (observer,
# 2026-09-10).
#
# This is deliberately narrower than what it replaces. A `.py` or `.md`
# named after secrets is source ABOUT secrets, not a secret; a `.json`
# or `.env` or `.pem` by the same name is the thing itself. Secrets in
# this system live in the environment or a 0600 TOML, never in tracked
# source, so the file types that can still hide one are the ones still
# refused.

#: Extensions that hold data rather than source. A credential word in
#: one of these is a credential file.
_DATA_EXTENSIONS = frozenset({
    "", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".txt", ".env",
})
#: Extensions that ARE a credential, whatever the file is called.
_SECRET_EXTENSIONS = frozenset({".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"})
#: Words that name a credential store when they name a data file.
_CREDENTIAL_WORDS = ("credential", "secret", "password", "passwd", "token")
#: Files that are a private key by name alone.
_KEY_FILENAMES = frozenset({"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".pgpass"})
#: A directory called this holds credentials whatever is inside it.
_CREDENTIAL_DIRECTORIES = frozenset({"secrets", "credentials", ".ssh", ".gnupg", ".aws"})

_MAX_PATH_CHARS = 4096
_MAX_READ_CHARS = 20_000
# A hard stop so a pathological file cannot be slurped into memory. Far
# above any source file; this is a guard, not a policy.
# Files at the repository root that any read tool may open. Reading
# them is safe; whether they may be WRITTEN is a separate question that
# `write_scopes_source` and Guardian's protected list answer -- and
# simloader.py and sim.sh are protected there precisely because they are
# the mechanism that undoes a bad change.
ROOT_FILES: frozenset[str] = frozenset({
    "README.md", "CLAUDE.md", "requirements.txt", "simorgh.toml", "simloader.py", "sim.sh",
})

_MAX_FILE_BYTES = 8_000_000
# A PDF's bytes are mostly fonts and images, so the cap that protects
# against a huge *text* file refuses ordinary papers: three in `papers/`
# are over 8 MB and one is 17 MB. What matters is how much text comes
# out, and `pdf_to_text`'s page limit already bounds that.
_MAX_PDF_BYTES = 60_000_000
_MAX_LIST_ENTRIES = 300


def _is_dotenv(name: str) -> bool:
    """`.env`, `.env.local`, `prod.env` -- but not `world.env.query.v1.json`,
    which is a schema with the word in the middle of its name."""
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def looks_like_credential_path(parts: Iterable[str]) -> bool:
    """True if any path segment looks like a credentials file/dir name.

    Shared by `resolve_safe_path` (so `read_file`/`list_dir` refuse these
    outright) and `search_code`'s own file walk (both the `rg` and
    pure-Python backends) -- without this second use, `search_code`
    could grep the contents of a `.env` or `credentials.json` sitting
    anywhere under `readable_roots` even though `read_file` refuses the
    very same path by name. Found live, 2026-09-08: a `tools/.env` and a
    `tools/credentials.json` were both unreadable via `read_file` but
    their secret contents came back verbatim from `search_code`, via
    ripgrep AND the pure-Python fallback."""
    segments = [str(part).strip().lower() for part in parts if str(part).strip()]
    if not segments:
        return False
    if any(segment in _CREDENTIAL_DIRECTORIES for segment in segments[:-1]):
        return True
    name = segments[-1]
    if name in _KEY_FILENAMES or _is_dotenv(name):
        return True
    suffix = PurePosixPath(name).suffix
    if suffix in _SECRET_EXTENSIONS:
        return True
    if suffix in _DATA_EXTENSIONS and any(word in name for word in _CREDENTIAL_WORDS):
        return True
    return name in _CREDENTIAL_DIRECTORIES


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
    # A single named file at the repo root is allowed alongside the
    # readable directories. Without this, `readable_roots` holds
    # directories only and README.md, requirements.txt, simloader.py and
    # sim.sh were readable by nothing -- Sim could not read its own
    # bootloader, and a chat session spent its whole budget hunting for
    # a README it was standing on (observer, 2026-09-08).
    if len(rel.parts) == 1 and rel.parts[0] in ROOT_FILES:
        pass
    elif not rel.parts or rel.parts[0] not in readable_roots:
        return None, (f"refused: {raw_path!r} is outside the readable areas "
                      f"({', '.join(readable_roots)}, and these files at the root: {', '.join(ROOT_FILES)})")
    if looks_like_credential_path(rel.parts):
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
        # Same treatment for the other formats that are not plain text:
        # a spreadsheet of the very data a task is about, or a
        # screenshot in the repo, used to come back as binary noise
        # (doctext.py). `None` means "not one of mine" -- distinct from
        # "mine, and empty".
        handled = document_to_text(data, name=raw_path)
        if handled is not None:
            text, problem = handled
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
        # Show the END of the file rather than nothing. A model that
        # guesses a line range past the end learns only the length, then
        # spends another step guessing again -- three steps in a row went
        # this way on 2026-09-09 while it was trying to edit a file it
        # had just shortened. Answering with the tail turns a wasted
        # step into a useful one, and says plainly what it did.
        tail = lines[max(0, total - 40):]
        first = total - len(tail) + 1
        numbered = "\n".join(f"{first + i:5d}| {line}" for i, line in enumerate(tail))
        return (f"[lines {start}-{end} are past the end; {raw_path} has {total} lines. "
                f"Here are the last {len(tail)}:]\n{numbered}")
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
