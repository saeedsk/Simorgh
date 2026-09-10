"""Walking a source and keeping the index in step with it.

Incremental by content hash, not by mtime: a file that was touched but
not changed must not be re-parsed and re-embedded (on a papers
directory that is minutes of work for no result), and a file whose
mtime went *backwards* -- restored from a backup, synced from another
machine, checked out of git -- must not be missed, which is exactly
what an mtime comparison does.

The exclusions are not a tidiness feature. **A knowledge base that
indexes `.env` is a credential leak with a search box**, and it is a
particularly bad one because the leak is invisible: nothing looks
wrong, and the secret only surfaces the day someone asks a question
whose answer happens to be a password. `pathsafety.looks_like_
credential_path` is the same check the file tools already use, so
there is one answer in the system to "does this path look like a
secret" rather than two that can drift apart.
"""

from __future__ import annotations

import fnmatch
import hashlib
import time
from pathlib import Path

from ..pathsafety import looks_like_credential_path
from .api import Document, ScanReport, SourceSpec
from .chunk import chunk_text
from .index import Index, document_id
from .parse import INDEXABLE_SUFFIXES, parse_bytes, title_for

#: Never walked, whatever a source's globs say. These are directories
#: whose contents are either enormous, entirely derived, or somebody
#: else's private state -- and `.simorgh`/`workspace` include the
#: Ledger, so indexing them would feed Sim's own output back to it as
#: if it were the creator's documents.
ALWAYS_EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages", ".Trash",
    "Library", "AppData", ".cache", ".npm", ".cargo", ".gradle",
    ".simorgh", "workspace", ".sim-quarantine",
})

DEFAULT_EXCLUDED_GLOBS: tuple[str, ...] = (
    "**/.git/**", "**/node_modules/**", "**/*.key", "**/*.pem", "**/.env*",
    "**/id_rsa*", "**/id_ed25519*", "**/*.p12", "**/*.pfx", "**/secrets.*",
    "**/credentials*", "**/*.kdbx",
)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _matches_any(path: Path, patterns) -> bool:
    text = str(path)
    name = path.name
    return any(fnmatch.fnmatch(text, pattern) or fnmatch.fnmatch(name, pattern)
               for pattern in patterns)


def is_excluded(path: Path, *, exclude=()) -> tuple[bool, str]:
    """`(excluded, why)`. The reason travels so a scan report can say
    "12 skipped: credential-looking" rather than a bare count."""
    parts = path.parts
    if looks_like_credential_path(parts):
        return True, "looks like a credential file"
    for part in parts:
        if part in ALWAYS_EXCLUDED_DIRS:
            return True, f"inside {part}/"
    if _matches_any(path, DEFAULT_EXCLUDED_GLOBS):
        return True, "matches a default exclusion"
    if exclude and _matches_any(path, exclude):
        return True, "matches this source's exclude list"
    return False, ""


def walk_source(spec: SourceSpec, *, max_file_bytes: int = 100 * 1024 * 1024,
                max_files: int = 100_000):
    """Every file this source would index, with the ones it refuses and
    why. Yields `(path, problem)` where `problem` is "" for a file to
    index."""
    root = Path(spec.path).expanduser()
    if not root.exists():
        return
    if root.is_file():
        candidates = [root]
    else:
        candidates = sorted(p for p in root.rglob("*") if p.is_file())
    seen = 0
    for path in candidates:
        if seen >= max_files:
            return
        excluded, why = is_excluded(path, exclude=spec.exclude)
        if excluded:
            yield path, why
            continue
        if spec.include and spec.include != ("**/*",) and not _matches_any(path, spec.include):
            yield path, "does not match this source's include list"
            continue
        if path.suffix.lower() not in INDEXABLE_SUFFIXES and path.suffix:
            yield path, f"{path.suffix} is not indexed"
            continue
        try:
            size = path.stat().st_size
        except OSError as exc:
            yield path, f"could not be read ({exc.strerror})"
            continue
        if size > max_file_bytes:
            yield path, f"is {size // (1024 * 1024)} MB, over the limit"
            continue
        seen += 1
        yield path, ""


def scan_source(index: Index, spec: SourceSpec, *, embedder=None, chunk_tokens: int = 400,
                overlap: float = 0.15, max_file_bytes: int = 100 * 1024 * 1024,
                clock=time.time, ocr: bool = False, max_files: int = 100_000) -> ScanReport:
    """Bring the index in step with one source, and return what changed."""
    report = ScanReport()
    seen_paths: set[str] = set()
    known = index.document_paths(spec.name)

    for path, problem in walk_source(spec, max_file_bytes=max_file_bytes, max_files=max_files):
        if problem:
            report.skipped += 1
            if len(report.problems) < 20:
                report.problems.append(f"{path}: {problem}")
            continue

        report.scanned += 1
        text_path = str(path)
        seen_paths.add(text_path)
        doc_id = document_id(spec.name, text_path)

        try:
            data = path.read_bytes()
        except OSError as exc:
            report.failed += 1
            report.problems.append(f"{text_path}: could not be read ({exc.strerror})")
            continue

        digest = sha256_of(data)
        if index.sha_of(doc_id) == digest:
            report.unchanged += 1
            continue

        parsed = parse_bytes(data, name=path.name, ocr=ocr)
        existed = doc_id in {document_id(spec.name, p) for p in known}
        stat = path.stat()
        document = Document(
            id=doc_id, source=spec.name, path=text_path,
            title=title_for(text_path, parsed.text), mime=parsed.mime, sha256=digest,
            bytes=len(data), mtime=stat.st_mtime, pages=parsed.pages, privacy=spec.privacy,
            indexed_at=clock(), status=parsed.status, detail=parsed.detail,
        )

        if parsed.status != "indexed":
            index.put_document(document, [])
            if parsed.status == "needs_ocr":
                report.needs_ocr += 1
            elif parsed.status == "failed":
                report.failed += 1
            else:
                report.skipped += 1
            if parsed.detail and len(report.problems) < 20:
                report.problems.append(f"{text_path}: {parsed.detail}")
            continue

        chunks = chunk_text(parsed.text, doc_id=doc_id, max_tokens=chunk_tokens, overlap=overlap)
        vectors = None
        if embedder is not None:
            vectors = {}
            for chunk in chunks:
                provider, values = embedder.embed(chunk.text)
                vectors[chunk.ordinal] = (provider, values)
        index.put_document(document, chunks, vectors=vectors)
        report.chunks += len(chunks)
        if existed:
            report.updated += 1
        else:
            report.added += 1

    # A file that is gone from the source is gone from the index. Left
    # behind, it goes on answering questions with text that no longer
    # exists anywhere, which is worse than not answering at all.
    for stale in known - seen_paths:
        index.delete_document(document_id(spec.name, stale))
        report.removed += 1

    index.mark_scanned(spec.name, clock())
    return report


def scan_all(index: Index, **kwargs) -> ScanReport:
    total = ScanReport()
    for spec in index.sources():
        total.merge(scan_source(index, spec, **kwargs))
    return total


__all__ = ["ALWAYS_EXCLUDED_DIRS", "DEFAULT_EXCLUDED_GLOBS", "is_excluded", "scan_all",
           "scan_source", "sha256_of", "walk_source"]
