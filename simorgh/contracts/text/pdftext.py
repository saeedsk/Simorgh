"""PDF to readable text.

Two paths needed this and neither had it (observer, 2026-09-08):

- `web_fetch` on a PDF returned the raw bytes decoded as if they were
  text -- a screenful of `%PDF-1.5` and binary stream data, `ok=True`.
  The GAIA observer ranked this its top gap: a benchmark whose questions
  attach papers and reports cannot be answered by a system that cannot
  read one, and the failure looked like a wrong answer rather than a
  missing tool.
- the creator added a `papers/` directory of papers on self-learning AI
  for Sim to read. `read_file` refused every one of them the same way.

`pypdf` does the work when it is installed, `pdfminer.six` when it is
not, and the tool says plainly that it cannot when neither is. That
order is deliberate: pypdf is fast and usually enough, pdfminer is
slower and better at awkward layouts, and an explicit refusal beats
handing the model binary noise under a success.

A scanned PDF is images, not text. There is no OCR here, so a document
that yields almost nothing per page is reported as scanned rather than
returned as a near-empty success -- the same rule `htmltext.py` applies
to a JavaScript shell, for the same reason: a tool that succeeds and
says nothing is a quiet lie.
"""

from __future__ import annotations

import io

MAGIC = b"%PDF-"
# Below this many characters per page, the pages are pictures of text.
# Set low on purpose: a scanned document yields nothing or a handful of
# stray characters per page, while a real one runs into the thousands,
# so the gap is enormous and the line does not need to sit near the
# middle of it. A threshold tuned to the dense case calls a title page
# or a one-page form "scanned", which is a false alarm on a document
# that read perfectly well.
_SCANNED_MAX_CHARS_PER_PAGE = 10
# ...and a document with real text in it is never scanned, however many
# pages the rest of it has.
_SCANNED_MAX_CHARS = 200


def looks_like_pdf(data: bytes) -> bool:
    """A PDF is identified by its bytes, never by the URL's extension --
    plenty of PDFs are served from paths that do not end in `.pdf`."""
    return data[:1024].lstrip()[:5] == MAGIC


def _load() -> tuple[str, object]:
    """`(backend name, module)`, or `("", None)`.

    Both imports are guarded, which is not ceremony: `tests/simorgh/
    test_module_boundaries.py` requires every third-party import in the
    package to sit under an ImportError handler, so that a machine
    without the optional dependency still boots. An unguarded import
    here would make the whole Execution subsystem unimportable on a
    machine with no PDF reader.
    """
    try:
        import pypdf
        return "pypdf", pypdf
    except ImportError:
        pass
    try:
        import pdfminer.high_level as miner
        return "pdfminer", miner
    except ImportError:
        return "", None


def available() -> str:
    """Which extractor we have, or "" for none."""
    return _load()[0]


def _with_pypdf(module, data: bytes, max_pages: int) -> tuple[str, int]:
    reader = module.PdfReader(io.BytesIO(data))
    total = len(reader.pages)
    chunks = []
    for number, page in enumerate(reader.pages[:max_pages], start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 -- one broken page must not lose the rest
            text = ""
        if text.strip():
            chunks.append(f"\n\n--- page {number} ---\n{text.strip()}")
    return "".join(chunks).strip(), total


def _with_pdfminer(module, data: bytes, max_pages: int) -> tuple[str, int]:
    text = module.extract_text(io.BytesIO(data), maxpages=max_pages) or ""
    return text.strip(), text.count("\f") or 1


def pdf_to_text(data: bytes, *, source: str = "", max_pages: int = 100) -> tuple[str, str]:
    """`(text, problem)`.

    `problem` is "" on success, and otherwise names what stopped us, in
    words that tell the model what to do next instead of what went
    wrong internally.
    """
    backend, module = _load()
    if not backend:
        return "", (
            "this is a PDF, and no PDF reader is installed here (pip install pypdf). "
            "Try an HTML version of the same document, or its abstract page."
        )
    try:
        text, pages = (
            _with_pypdf(module, data, max_pages) if backend == "pypdf"
            else _with_pdfminer(module, data, max_pages)
        )
    except Exception as exc:  # noqa: BLE001 -- a malformed PDF is a tool result, not a crash
        return "", f"this PDF could not be parsed ({exc!r}); it may be encrypted or corrupt"

    shown = min(pages, max_pages) or 1
    if len(text) < min(_SCANNED_MAX_CHARS_PER_PAGE * shown, _SCANNED_MAX_CHARS):
        where = f" ({source})" if source else ""
        return text, (
            f"this PDF{where} has {pages} page(s) but yielded only {len(text)} characters of text: "
            "it is scanned images, and there is no OCR here. Look for a text version or a transcript."
        )

    header = f"[{pages} page PDF"
    if pages > max_pages:
        header += f", first {max_pages} pages shown"
    return f"{header}, {len(text)} chars of text via {backend}]\n{text}", ""


__all__ = ["MAGIC", "available", "looks_like_pdf", "pdf_to_text"]
