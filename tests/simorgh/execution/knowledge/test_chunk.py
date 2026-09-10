"""Chunking (execution/knowledge/chunk.py).

Retrieval quality is decided here far more than in the ranking: a chunk
that splits a table down the middle can never answer a question about
that table however well it is scored."""

from __future__ import annotations

import unittest

from simorgh.execution.knowledge.chunk import chunk_text, estimate_tokens, split_sections


class SectionTestCase(unittest.TestCase):
    def test_atx_headings_become_sections(self):
        sections = split_sections("# A\n\nalpha\n\n# B\n\nbeta\n")
        self.assertEqual([s.heading_path for s in sections], ["A", "B"])

    def test_the_heading_trail_nests(self):
        sections = split_sections("# Policy\n\nx\n\n## Cover\n\ny\n\n### Flood\n\nz\n")
        self.assertEqual([s.heading_path for s in sections],
                         ["Policy", "Policy / Cover", "Policy / Cover / Flood"])

    def test_a_sibling_heading_pops_the_trail(self):
        sections = split_sections("# P\n\n## A\n\nx\n\n## B\n\ny\n")
        self.assertEqual(sections[-1].heading_path, "P / B")

    def test_setext_headings_are_recognised_and_not_duplicated(self):
        sections = split_sections("Title\n=====\n\nbody text\n")
        self.assertEqual(sections[0].heading_path, "Title")
        self.assertNotIn("Title", sections[0].text)

    def test_text_before_any_heading_keeps_an_empty_path(self):
        sections = split_sections("preamble\n\n# A\n\nbody\n")
        self.assertEqual(sections[0].heading_path, "")

    def test_page_breaks_advance_the_page_number(self):
        sections = split_sections("# A\n\none\n\f\n# B\n\ntwo\n")
        self.assertEqual([s.page for s in sections], [1, 2])


class ChunkTestCase(unittest.TestCase):
    def test_an_empty_document_yields_no_chunks(self):
        self.assertEqual(chunk_text("   \n\n  ", doc_id="d"), [])

    def test_ordinals_are_dense_and_ordered(self):
        chunks = chunk_text("# A\n\nx\n\n# B\n\ny\n", doc_id="d")
        self.assertEqual([c.ordinal for c in chunks], list(range(len(chunks))))

    def test_every_chunk_carries_its_heading_and_page(self):
        chunks = chunk_text("# Policy\n\n## Cover\n\nFlood is covered.\n", doc_id="d")
        self.assertEqual(chunks[-1].heading_path, "Policy / Cover")
        self.assertEqual(chunks[-1].page, 1)

    def test_a_long_section_is_cut_by_size(self):
        body = "\n".join(f"line {n} with several words in it" for n in range(200))
        chunks = chunk_text(f"# A\n\n{body}\n", doc_id="d", max_tokens=100)
        self.assertGreater(len(chunks), 3)
        for chunk in chunks:
            self.assertLess(chunk.tokens, 400)

    def test_size_cut_chunks_overlap(self):
        body = "\n".join(f"unique-token-{n}" for n in range(60))
        chunks = chunk_text(f"# A\n\n{body}\n", doc_id="d", max_tokens=40, overlap=0.2)
        self.assertGreater(len(chunks), 1)
        tail = chunks[0].text.splitlines()[-1]
        self.assertIn(tail, chunks[1].text, "a fact straddling a cut must be in both")

    def test_zero_overlap_is_honoured(self):
        body = "\n".join(f"tok{n}" for n in range(60))
        chunks = chunk_text(f"# A\n\n{body}\n", doc_id="d", max_tokens=40, overlap=0.0)
        self.assertNotIn(chunks[0].text.splitlines()[-1], chunks[1].text)

    def test_a_table_is_never_split(self):
        """Half a table retrieves and then misleads, which is worse than
        not retrieving at all."""
        table = "\n".join([
            "Item        Amount      Notes",
            "Flood       5000        annual",
            "Fire        10000       annual",
            "Theft       2500        annual",
            "Storm       7500        annual",
        ])
        chunks = chunk_text(f"# Cover\n\nsome intro words here\n\n{table}\n",
                            doc_id="d", max_tokens=15)
        holding = [c for c in chunks if "Flood       5000" in c.text]
        self.assertEqual(len(holding), 1)
        for row in ("Item", "Flood", "Fire", "Theft", "Storm"):
            self.assertIn(row, holding[0].text)

    def test_the_overlap_never_produces_a_chunk_that_is_only_carry(self):
        """A trailing chunk made of one duplicated row and a blank line
        retrieves as a real passage and says nothing."""
        table = "\n".join(f"Row{n}       {n}00        note" for n in range(6))
        chunks = chunk_text(f"# T\n\n{table}\n\n", doc_id="d", max_tokens=12)
        for chunk in chunks:
            self.assertTrue(chunk.text.strip())
            self.assertGreater(len(chunk.text.split()), 2)


class TokenEstimateTestCase(unittest.TestCase):
    def test_it_grows_with_length(self):
        self.assertLess(estimate_tokens("one two"), estimate_tokens("one two three four five"))

    def test_empty_text_is_not_zero_tokens(self):
        # Used as a divisor and a budget; zero invites a divide and a
        # chunk that is "free" to add forever.
        self.assertGreaterEqual(estimate_tokens(""), 1)


class PageNumberTestCase(unittest.TestCase):
    """Page numbers are what makes a citation checkable. `splitlines()`
    consumes a form feed as a line terminator, so every page break used
    to vanish before it could be counted and a 300-page PDF cited page 1
    throughout."""

    def test_a_form_feed_on_its_own_line_advances_the_page(self):
        sections = split_sections("# A\n\none\n\f\n# B\n\ntwo\n")
        self.assertEqual([s.page for s in sections], [1, 2])

    def test_a_form_feed_at_the_end_of_a_line_advances_the_page(self):
        sections = split_sections("# A\n\nlast line of page one\f\n# B\n\ntwo\n")
        self.assertEqual([s.page for s in sections], [1, 2])

    def test_several_pages_count_up(self):
        sections = split_sections("# A\n\nx\n\f\n\f\n\f\n# D\n\ny\n")
        self.assertEqual(sections[-1].page, 4)

    def test_chunks_inherit_their_section_page(self):
        chunks = chunk_text("# A\n\nfirst\n\f\n# B\n\nsecond\n", doc_id="d")
        self.assertEqual({c.heading_path: c.page for c in chunks}, {"A": 1, "B": 2})

    def test_windows_line_endings_do_not_become_stray_carriage_returns(self):
        sections = split_sections("# A\r\n\r\nbody here\r\n")
        self.assertEqual(sections[0].heading_path, "A")
        self.assertNotIn("\r", sections[0].text)
