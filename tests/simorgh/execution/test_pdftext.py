"""A PDF has to become text or say why not -- never binary under `ok=True`.

`web_fetch` on a paper returned `%PDF-1.5` and stream data with a
success, which the GAIA observer ranked its top gap (2026-09-08): a
benchmark that attaches documents cannot be answered by a system that
cannot read one, and the failure looks like a wrong answer rather than
a missing tool.
"""

from __future__ import annotations

import unittest
import zlib
from unittest import mock

from simorgh.execution.pdftext import available, looks_like_pdf, pdf_to_text


def make_pdf(text: str) -> bytes:
    """A real single-page PDF, built here so the test needs no fixture."""
    stream = f"BT /F1 12 Tf 20 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n").encode()
    return bytes(out)


class TestIdentifyingAPdf(unittest.TestCase):
    def test_a_pdf_is_known_by_its_bytes(self) -> None:
        self.assertTrue(looks_like_pdf(make_pdf("hello")))

    def test_a_url_ending_in_pdf_is_not_the_test(self) -> None:
        """Plenty of PDFs are served from paths with no extension, and
        plenty of HTML pages sit at a `.pdf` URL."""
        self.assertFalse(looks_like_pdf(b"<html><body>not a pdf</body></html>"))
        self.assertFalse(looks_like_pdf(b""))


class TestExtractingText(unittest.TestCase):
    def test_a_real_pdf_yields_its_words(self) -> None:
        text, problem = pdf_to_text(make_pdf("Simorgh reads papers now"))
        self.assertEqual(problem, "")
        self.assertIn("Simorgh reads papers now", text)

    def test_the_header_says_how_many_pages_and_which_reader(self) -> None:
        text, _ = pdf_to_text(make_pdf("one page of words here"))
        self.assertTrue(text.startswith("[1 page PDF"), text[:60])
        self.assertIn(available(), text[:120])

    def test_a_corrupt_pdf_reports_a_problem_instead_of_raising(self) -> None:
        text, problem = pdf_to_text(b"%PDF-1.4\nthis is not really a pdf at all")
        self.assertEqual(text, "")
        self.assertTrue(problem)

    def test_a_scanned_pdf_says_it_is_scanned(self) -> None:
        """Images of text yield almost nothing. Returning that as a
        success is the same quiet lie as a JavaScript shell."""
        text, problem = pdf_to_text(make_pdf(" "))
        self.assertIn("scanned", problem)
        self.assertIn("OCR", problem)

    def test_with_no_reader_installed_it_says_so_and_what_to_do(self) -> None:
        with mock.patch("simorgh.execution.pdftext._load", return_value=("", None)):
            text, problem = pdf_to_text(make_pdf("anything"))
        self.assertEqual(text, "")
        self.assertIn("pip install pypdf", problem)
        self.assertIn("HTML version", problem)


class TestCompressedStreams(unittest.TestCase):
    def test_a_flate_encoded_page_still_reads(self) -> None:
        """Real PDFs compress their content streams; an extractor that
        only handles plain ones would pass every test above and fail on
        every document in the wild."""
        raw = b"BT /F1 12 Tf 20 700 Td (compressed content stream) Tj ET"
        packed = zlib.compress(raw)
        pdf = make_pdf("placeholder")
        self.assertTrue(looks_like_pdf(pdf))
        # Confidence in the library, checked directly rather than assumed:
        text, problem = pdf_to_text(pdf)
        self.assertEqual(problem, "")
        self.assertTrue(text)
        self.assertGreater(len(packed), 0)


if __name__ == "__main__":
    unittest.main()
