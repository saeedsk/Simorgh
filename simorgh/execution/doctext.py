"""Files that are not plain text, turned into text a model can read.

`read_file` understood source and (since the papers arrived) PDF.
Everything else came back as binary noise or a refusal -- so a
spreadsheet of the very data a task was about, or a screenshot someone
dropped in the repo, was unreachable. This is the same shape as
`pdftext.py`: a dispatcher that returns `(text, problem)` and never
raises, with every heavy dependency imported lazily so a fresh install
with no extras keeps working and simply says what to install.

Magic bytes decide first, extension second. A `.docx` renamed `.bin`
still reads correctly, and a `.csv` that is really a zip does not get
handed to the CSV parser.

Deliberately not here: anything that would run code from the document
(macros, formulas, embedded objects). Text and structure only.
"""

from __future__ import annotations

import csv
import io
import zipfile

_ZIP_MAGIC = b"PK\x03\x04"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF_MAGIC = (b"GIF87a", b"GIF89a")
_WEBP_PREFIX, _WEBP_TAG = b"RIFF", b"WEBP"

_DOCX_MEMBER = "word/document.xml"
_XLSX_MEMBER = "xl/workbook.xml"


def looks_like_docx(data: bytes) -> bool:
    return _zip_has(data, _DOCX_MEMBER)


def looks_like_xlsx(data: bytes) -> bool:
    return _zip_has(data, _XLSX_MEMBER)


def looks_like_image(data: bytes) -> bool:
    head = data[:16]
    return (
        head.startswith(_PNG_MAGIC)
        or head.startswith(_JPEG_MAGIC)
        or head.startswith(_GIF_MAGIC)
        or (head.startswith(_WEBP_PREFIX) and data[8:12] == _WEBP_TAG)
    )


def _zip_has(data: bytes, member: str) -> bool:
    if not data.startswith(_ZIP_MAGIC):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return member in archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def docx_to_text(data: bytes, *, max_chars: int) -> tuple[str, str]:
    try:
        import docx  # type: ignore
    except ImportError:
        return "", "this is a .docx -- install python-docx to read it"
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 -- a corrupt file is a problem, never a crash
        return "", f"this .docx could not be parsed: {exc!r}"
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append("\t".join(cells))
    text = "\n".join(parts)
    return (text[:max_chars], "") if text else ("", "this .docx has no readable text in it")


def xlsx_to_text(data: bytes, *, max_rows: int, max_chars: int) -> tuple[str, str]:
    try:
        from openpyxl import load_workbook  # type: ignore
    except ImportError:
        return "", "this is a .xlsx -- install openpyxl to read it"
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return "", f"this .xlsx could not be parsed: {exc!r}"
    blocks = []
    try:
        for sheet in workbook.worksheets:
            lines = [f"# sheet: {sheet.title}"]
            truncated = False
            for index, row in enumerate(sheet.iter_rows(values_only=True)):
                if index >= max_rows:
                    truncated = True
                    break
                lines.append("\t".join("" if v is None else str(v) for v in row))
            if truncated:
                lines.append(f"...[first {max_rows} rows of this sheet]")
            blocks.append("\n".join(lines))
    finally:
        workbook.close()
    text = "\n\n".join(blocks)
    return (text[:max_chars], "") if text else ("", "this .xlsx has no readable cells")


def csv_to_text(data: bytes, *, max_rows: int, max_chars: int) -> tuple[str, str]:
    raw = data.decode("utf-8", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096]) if raw.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    rows = []
    for index, row in enumerate(csv.reader(io.StringIO(raw), dialect)):
        if index >= max_rows:
            rows.append(f"...[first {max_rows} rows]")
            break
        rows.append("\t".join(row))
    text = "\n".join(rows)
    return (text[:max_chars], "") if text else ("", "this file has no rows")


def image_to_text(data: bytes, *, max_chars: int, ocr: bool = True) -> tuple[str, str]:
    """What a person would say about the picture without describing it:
    its size, mode, and any EXIF worth knowing -- plus OCR'd text when
    tesseract happens to be installed. It does NOT caption the image;
    claiming to know what is in a photo from its bytes would be exactly
    the kind of confident fiction this project keeps catching."""
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return "", "this is an image -- install Pillow to read its dimensions and any text in it"
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        return "", f"this image could not be parsed: {exc!r}"
    lines = [f"image: {image.width}x{image.height} {image.mode} ({image.format or 'unknown format'})"]
    exif = {}
    try:
        raw_exif = image.getexif()
        wanted = {271: "camera_make", 272: "camera_model", 306: "taken_at", 274: "orientation"}
        exif = {name: str(raw_exif.get(tag)) for tag, name in wanted.items() if raw_exif.get(tag)}
    except Exception:  # noqa: BLE001 -- EXIF is a nicety, never a reason to fail
        exif = {}
    if exif:
        lines.append("exif: " + ", ".join(f"{k}={v}" for k, v in exif.items()))
    if ocr:
        text, problem = _ocr(image)
        if text:
            lines.append("--- text found in the image (OCR) ---")
            lines.append(text)
        elif problem:
            lines.append(f"({problem})")
    return "\n".join(lines)[:max_chars], ""


def _ocr(image) -> tuple[str, str]:
    import shutil

    try:
        import pytesseract  # type: ignore
    except ImportError:
        return "", "no OCR: install pytesseract and tesseract to read text in images"
    if not shutil.which("tesseract"):
        return "", "no OCR: pytesseract is installed but the tesseract binary is not on PATH"
    try:
        return (pytesseract.image_to_string(image) or "").strip(), ""
    except Exception as exc:  # noqa: BLE001
        return "", f"OCR failed: {exc!r}"


def document_to_text(data: bytes, *, name: str = "", max_rows: int = 200,
                     max_chars: int = 20_000) -> tuple[str, str] | None:
    """`(text, problem)` for a format this module handles, or None when
    the bytes are somebody else's business (plain text, PDF, source).

    None rather than an empty string on purpose: the caller has its own
    behaviour for ordinary files, and "not mine" must be distinguishable
    from "mine, and empty".
    """
    lowered = (name or "").lower()
    if looks_like_docx(data):
        return docx_to_text(data, max_chars=max_chars)
    if looks_like_xlsx(data):
        return xlsx_to_text(data, max_rows=max_rows, max_chars=max_chars)
    if looks_like_image(data):
        return image_to_text(data, max_chars=max_chars)
    if lowered.endswith((".csv", ".tsv")):
        return csv_to_text(data, max_rows=max_rows, max_chars=max_chars)
    return None
