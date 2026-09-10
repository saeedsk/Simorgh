"""The index and the scanner (execution/knowledge/index.py, sources.py).

Nothing here touches a network or a real account; every corpus is a
handful of files in a temporary directory. The behaviours worth pinning
are the ones that decide whether the index can be trusted: incremental
by content, credential files never read, a deleted file gone from the
answers, and a scanned PDF recorded as needing OCR rather than as an
empty success."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.execution.knowledge.api import Document, SourceSpec
from simorgh.execution.knowledge.chunk import chunk_text
from simorgh.execution.knowledge.embed import Embedder
from simorgh.execution.knowledge.index import Index, document_id, pack_vector, unpack_vector
from simorgh.execution.knowledge.parse import parse_bytes, title_for
from simorgh.execution.knowledge.sources import is_excluded, scan_source, walk_source


class _Corpus(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.docs = self.root / "docs"
        self.docs.mkdir()
        self.index = Index(self.root / "index.db")
        self.spec = SourceSpec(kind="files", path=str(self.docs), privacy="personal")
        self.index.add_source(self.spec)
        self.embedder = Embedder("hashing")

    def tearDown(self):
        self.index.close()
        self._tmp.cleanup()

    def write(self, name: str, text: str) -> Path:
        path = self.docs / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def scan(self):
        return scan_source(self.index, self.spec, embedder=self.embedder)


class IndexTestCase(_Corpus):
    def test_a_document_id_is_stable_across_runs(self):
        self.assertEqual(document_id("files:/a", "/a/b.md"), document_id("files:/a", "/a/b.md"))

    def test_a_document_id_distinguishes_sources(self):
        self.assertNotEqual(document_id("files:/a", "/x"), document_id("files:/b", "/x"))

    def test_vectors_round_trip_through_the_blob(self):
        values = [0.5, -0.25, 0.125]
        restored = list(unpack_vector(pack_vector(values)))
        for original, back in zip(values, restored):
            self.assertAlmostEqual(original, back, places=6)

    def test_putting_a_document_twice_replaces_rather_than_duplicates(self):
        doc = Document(id="d1", source=self.spec.name, path="/x", title="T", mime="text/plain",
                       sha256="a", bytes=1, mtime=1.0)
        self.index.put_document(doc, chunk_text("# A\n\nfirst\n", doc_id="d1"))
        self.index.put_document(doc, chunk_text("# A\n\nsecond\n", doc_id="d1"))
        self.assertEqual(self.index.stats()["documents"], 1)
        self.assertEqual(len(self.index.chunks_of("d1")), 1)

    def test_deleting_a_document_removes_it_from_the_full_text_index(self):
        self.write("a.md", "# A\n\nunmistakable-token here\n")
        self.scan()
        self.assertTrue(self.index.search_lexical("unmistakable-token"))
        self.index.delete_document(document_id(self.spec.name, str(self.docs / "a.md")))
        self.assertEqual(self.index.search_lexical("unmistakable-token"), [])

    def test_a_query_fts5_cannot_parse_answers_nothing_rather_than_raising(self):
        self.write("a.md", "# A\n\nsomething\n")
        self.scan()
        for query in ("what's the excess?", "NOT", '"unclosed', "AND OR"):
            with self.subTest(query=query):
                self.index.search_lexical(query)  # no raise

    def test_removing_a_source_takes_its_documents_with_it(self):
        self.write("a.md", "# A\n\nbody\n")
        self.scan()
        self.assertEqual(self.index.stats()["documents"], 1)
        self.assertEqual(self.index.remove_source(self.spec.name), 1)
        self.assertEqual(self.index.stats()["documents"], 0)
        self.assertEqual(self.index.sources(), [])


class ExclusionTestCase(unittest.TestCase):
    """A knowledge base that indexes `.env` is a credential leak with a
    search box, and an invisible one: nothing looks wrong until the day
    a question's answer happens to be a password."""

    def test_a_dotenv_is_refused(self):
        excluded, why = is_excluded(Path("/home/me/project/.env"))
        self.assertTrue(excluded)
        self.assertIn("credential", why)

    def test_a_private_key_is_refused(self):
        for name in ("id_rsa", "id_ed25519", "server.pem", "cert.key"):
            with self.subTest(name=name):
                self.assertTrue(is_excluded(Path(f"/home/me/{name}"))[0], name)

    def test_a_git_directory_is_refused(self):
        self.assertTrue(is_excluded(Path("/repo/.git/config"))[0])

    def test_sims_own_state_is_refused(self):
        """Indexing the Ledger would feed Sim's own output back to it as
        if it were the creator's documents."""
        for path in ("/home/me/.simorgh/ledger/x.jsonl", "/repo/workspace/notes.md"):
            with self.subTest(path=path):
                self.assertTrue(is_excluded(Path(path))[0], path)

    def test_an_ordinary_document_is_allowed(self):
        self.assertFalse(is_excluded(Path("/home/me/Documents/policy.pdf"))[0])

    def test_a_source_can_add_its_own_exclusions(self):
        self.assertTrue(is_excluded(Path("/docs/draft.md"), exclude=("**/draft*",))[0])


class WalkTestCase(_Corpus):
    def test_credential_files_are_reported_as_skipped_with_a_reason(self):
        self.write("a.md", "# A\n\nbody\n")
        self.write(".env", "SECRET=hunter2")
        seen = {path.name: problem for path, problem in walk_source(self.spec)}
        self.assertEqual(seen["a.md"], "")
        self.assertIn("credential", seen[".env"])

    def test_an_unindexable_extension_is_skipped(self):
        self.write("a.zip", "x")
        seen = {path.name: problem for path, problem in walk_source(self.spec)}
        self.assertIn("not indexed", seen["a.zip"])

    def test_an_oversized_file_is_skipped_with_its_size(self):
        self.write("big.md", "x" * 5000)
        seen = {path.name: problem for path, problem in walk_source(self.spec, max_file_bytes=100)}
        self.assertIn("over the limit", seen["big.md"])

    def test_an_include_list_narrows_the_walk(self):
        self.write("keep.md", "a")
        self.write("skip.txt", "b")
        spec = SourceSpec(path=str(self.docs), include=("*.md",))
        seen = {path.name: problem for path, problem in walk_source(spec)}
        self.assertEqual(seen["keep.md"], "")
        self.assertIn("include", seen["skip.txt"])


class ScanTestCase(_Corpus):
    def test_a_first_scan_adds_and_indexes(self):
        self.write("policy.md", "# Policy\n\n## Cover\n\nFlood is covered up to 5000.\n")
        report = self.scan()
        self.assertEqual((report.added, report.updated, report.removed), (1, 0, 0))
        self.assertGreater(report.chunks, 0)

    def test_a_credential_file_is_never_read_into_the_index(self):
        self.write("a.md", "# A\n\nbody\n")
        self.write(".env", "PASSWORD=hunter2")
        self.scan()
        self.assertEqual(self.index.search_lexical("hunter2"), [])

    def test_an_unchanged_file_is_not_reparsed(self):
        self.write("a.md", "# A\n\nbody\n")
        self.scan()
        report = self.scan()
        self.assertEqual((report.added, report.updated, report.unchanged), (0, 0, 1))

    def test_a_touched_but_unchanged_file_is_still_unchanged(self):
        """Incremental by content hash, not mtime: re-parsing and
        re-embedding a papers directory because something touched it is
        minutes of work for no result."""
        path = self.write("a.md", "# A\n\nbody\n")
        self.scan()
        import os
        os.utime(path, (path.stat().st_atime + 1000, path.stat().st_mtime + 1000))
        self.assertEqual(self.scan().unchanged, 1)

    def test_a_changed_file_is_updated(self):
        self.write("a.md", "# A\n\noriginal text\n")
        self.scan()
        self.write("a.md", "# A\n\nreplaced text\n")
        report = self.scan()
        self.assertEqual((report.added, report.updated), (0, 1))
        self.assertTrue(self.index.search_lexical("replaced"))
        self.assertEqual(self.index.search_lexical("original"), [])

    def test_a_file_whose_mtime_went_backwards_is_still_noticed(self):
        """Restored from a backup, synced from another machine, checked
        out of git -- an mtime comparison misses every one of these."""
        path = self.write("a.md", "# A\n\noriginal\n")
        self.scan()
        self.write("a.md", "# A\n\nrestored\n")
        import os
        old = path.stat().st_mtime - 100_000
        os.utime(path, (old, old))
        self.assertEqual(self.scan().updated, 1)
        self.assertTrue(self.index.search_lexical("restored"))

    def test_a_deleted_file_stops_answering(self):
        """Left behind, it goes on answering with text that no longer
        exists anywhere -- worse than not answering at all."""
        path = self.write("a.md", "# A\n\ndistinctive-content\n")
        self.scan()
        path.unlink()
        report = self.scan()
        self.assertEqual(report.removed, 1)
        self.assertEqual(self.index.search_lexical("distinctive-content"), [])

    def test_a_scanned_pdf_is_recorded_as_needing_ocr_not_as_empty_success(self):
        """A corpus that records a scan as a successful index of nothing
        develops a hole exactly where the interesting paperwork is."""
        minimal_pdf = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                       b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
        (self.docs / "scan.pdf").write_bytes(minimal_pdf)
        report = self.scan()
        document = self.index.find_document(str(self.docs / "scan.pdf"))
        self.assertIsNotNone(document)
        self.assertIn(document.status, ("needs_ocr", "failed"))
        self.assertTrue(document.detail, "a status with no reason is unactionable")
        self.assertEqual(report.added, 0)

    def test_the_scan_records_when_it_ran(self):
        self.write("a.md", "# A\n\nx\n")
        self.assertEqual(self.index.last_scan(self.spec.name), 0.0)
        self.scan()
        self.assertGreater(self.index.last_scan(self.spec.name), 0.0)

    def test_privacy_travels_from_the_source_onto_the_document(self):
        spec = SourceSpec(path=str(self.docs), privacy="sensitive")
        self.index.add_source(spec)
        self.write("health.md", "# Results\n\nblood pressure normal\n")
        scan_source(self.index, spec, embedder=self.embedder)
        document = self.index.find_document(str(self.docs / "health.md"))
        self.assertEqual(document.privacy, "sensitive")

    def test_an_unreadable_file_does_not_stop_the_scan(self):
        self.write("good.md", "# A\n\nreadable\n")
        bad = self.write("bad.md", "# B\n\nx\n")
        bad.chmod(0o000)
        try:
            report = self.scan()
        finally:
            bad.chmod(0o644)
        self.assertGreaterEqual(report.added, 1)
        self.assertTrue(self.index.search_lexical("readable"))


class ParseTestCase(unittest.TestCase):
    def test_plain_text_parses(self):
        parsed = parse_bytes(b"# Title\n\nbody", name="a.md")
        self.assertEqual(parsed.status, "indexed")
        self.assertIn("body", parsed.text)

    def test_an_empty_file_is_skipped_with_a_reason(self):
        self.assertEqual(parse_bytes(b"", name="a.md").status, "skipped")

    def test_an_unknown_binary_type_is_skipped_not_failed(self):
        parsed = parse_bytes(b"\x00\x01", name="a.zip")
        self.assertEqual(parsed.status, "skipped")
        self.assertIn("not indexed", parsed.detail)

    def test_a_title_comes_from_the_first_heading(self):
        self.assertEqual(title_for("/x/a_b.md", "# Real Title\n\nbody"), "Real Title")

    def test_a_heading_far_down_the_document_is_not_the_title(self):
        text = "\n".join(["body"] * 20 + ["# Late Heading"])
        self.assertEqual(title_for("/x/my_file.md", text), "my file")

    def test_without_a_heading_the_filename_is_tidied(self):
        self.assertEqual(title_for("/x/my-tax-return.pdf", "no headings here"), "my tax return")
