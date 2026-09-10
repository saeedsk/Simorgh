"""Bytes to text, with the page numbers a citation needs.

Nothing new is parsed here. `execution/pdftext.py` and
`execution/doctext.py` already turn a PDF, a DOCX, a spreadsheet, a CSV
and an image into text for `read_file`, and using anything else would
mean two answers to "what does this document say" that could disagree.
What this adds is the part indexing needs and reading one file does
not: a *status*, so a document that produced no text says why.

The parser ladder, best first: Docling (layout-aware, absent here),
PyMuPDF, then the existing pypdf/pdfminer path, then plain text. Each
rung is optional and the one below always answers.

`needs_ocr` is the status that matters most. A scanned PDF parses
perfectly and yields nothing, and recording that as a successful index
of an empty document is how a corpus quietly develops a hole exactly
where the interesting paperwork is.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Extensions read as plain text without any parser at all.
TEXT_SUFFIXES = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".org", ".text", ".log",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".js", ".ts", ".sh", ".sql", ".html", ".htm", ".xml", ".tex",
})

#: Extensions the existing document parsers handle.
DOC_SUFFIXES = frozenset({".pdf", ".docx", ".xlsx", ".csv", ".tsv",
                          ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"})

INDEXABLE_SUFFIXES = TEXT_SUFFIXES | DOC_SUFFIXES


@dataclass(frozen=True)
class Parsed:
    text: str
    pages: int = 0
    #: `indexed` | `needs_ocr` | `failed` | `skipped`
    status: str = "indexed"
    detail: str = ""
    mime: str = ""
    backend: str = ""


def _mime_for(name: str) -> str:
    import mimetypes

    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def _pymupdf_text(data: bytes) -> tuple[str, int] | None:
    """PyMuPDF keeps reading order far better than pypdf on a
    two-column layout, which is most of a papers directory. Absent
    here; the guard is on the import so the boundary checker is
    satisfied and the fallback is the existing path."""
    try:
        import fitz  # noqa: PLC0415 -- optional, layout-aware PDF reader
    except ImportError:
        return None
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            pages = [page.get_text("text") for page in document]
        return ("\f".join(pages), len(pages))
    except Exception:  # noqa: BLE001 -- fall through to the next rung
        return None


def parse_bytes(data: bytes, *, name: str = "", max_pages: int = 200,
                max_chars: int = 2_000_000, ocr: bool = False) -> Parsed:
    """The whole ladder. Never raises: a document that cannot be read is
    a `Parsed` saying so, because one unreadable file must not stop a
    scan of ten thousand."""
    suffix = Path(name).suffix.lower()
    mime = _mime_for(name)

    if not data:
        return Parsed("", status="skipped", detail="the file is empty", mime=mime)

    if suffix == ".pdf" or data[:5] == b"%PDF-":
        via_pymupdf = _pymupdf_text(data)
        if via_pymupdf is not None:
            text, pages = via_pymupdf
            backend = "pymupdf"
        else:
            from ..pdftext import pdf_to_text

            text, problem = pdf_to_text(data, source=name, max_pages=max_pages)
            if problem and not text:
                status = "needs_ocr" if "scan" in problem.lower() or "image" in problem.lower() else "failed"
                return Parsed("", status=status, detail=problem, mime=mime, backend="pypdf")
            pages = max(text.count("\f") + 1, 1)
            backend = "pypdf"
        if not text.strip():
            return Parsed("", pages=pages, status="needs_ocr", mime=mime, backend=backend,
                          detail="this PDF has no extractable text -- it is a scan, and OCR is "
                                 "off (set [knowledge] ocr) or unavailable")
        return Parsed(text[:max_chars], pages=pages, mime=mime, backend=backend)

    if suffix in DOC_SUFFIXES:
        from ..doctext import document_to_text

        try:
            answer = document_to_text(data, name=name, max_chars=max_chars)
        except Exception as exc:  # noqa: BLE001
            return Parsed("", status="failed", detail=f"could not be parsed ({exc!r})", mime=mime)
        if answer is not None:
            text, problem = answer
            if not text.strip():
                status = "needs_ocr" if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp") \
                    else "failed"
                return Parsed("", status=status, mime=mime, backend="doctext",
                              detail=problem or "no text could be read from this file")
            return Parsed(text[:max_chars], pages=1, mime=mime, backend="doctext", detail=problem)

    if suffix in TEXT_SUFFIXES or not suffix:
        text = _decode(data)
        if not text.strip():
            return Parsed("", status="skipped", detail="the file has no text in it", mime=mime)
        return Parsed(text[:max_chars], pages=1, mime=mime or "text/plain", backend="plaintext")

    return Parsed("", status="skipped", mime=mime,
                  detail=f"{suffix or 'this file type'} is not indexed")


def title_for(path: str, text: str) -> str:
    """A document's own first heading, or its filename.

    A filename is a poor title and a first heading is usually a good
    one, but a heading taken from the wrong place is worse than either
    -- so only a heading in the first few lines counts.
    """
    for line in (text or "").splitlines()[:8]:
        stripped = line.strip()
        if stripped.startswith("#"):
            candidate = stripped.lstrip("#").strip()
            if candidate:
                return candidate[:200]
    return Path(path).stem.replace("_", " ").replace("-", " ").strip()[:200] or path


__all__ = ["DOC_SUFFIXES", "INDEXABLE_SUFFIXES", "Parsed", "TEXT_SUFFIXES", "parse_bytes",
           "title_for"]
