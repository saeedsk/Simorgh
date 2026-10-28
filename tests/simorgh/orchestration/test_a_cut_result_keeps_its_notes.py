"""A tool result cut for the model keeps its closing notes (live 2026-10-28).

Execution appends "full data: results/<id>.json (200 rows)" after a
listing, and `mail_search` its own "Stopped at the limit" note. The cut at
8000 characters kept the listing's head and dropped both, so asked for the
noisiest senders of the month Sim counted the 67 lines it could see, three
turns running."""

import unittest

from simorgh.orchestration.session import SessionRunner

LISTING = "200 message(s):\n" + "\n".join(f"  [g:INBOX:{i}] 27 Oct  Sender {i} <s{i}@x>  Deal" for i in range(200))
NOTES = "\n\nStopped at the limit of 200: older matches were not fetched.\n\nfull data: results/abc.json (200 rows)"


class ACutResultKeepsItsNotes(unittest.TestCase):
    def test_the_file_and_the_limit_survive_the_cut(self):
        shown = SessionRunner._bound_for_model(LISTING + NOTES)
        self.assertLess(len(shown), len(LISTING))
        self.assertTrue(shown.endswith("full data: results/abc.json (200 rows)"))
        self.assertIn("Stopped at the limit of 200", shown)
        self.assertIn("count, rank or filter with code over that file", shown)

    def test_a_long_result_with_no_file_is_cut_as_before(self):
        shown = SessionRunner._bound_for_model(LISTING)
        self.assertIn("READ_FILE: path:START-END", shown)

    def test_a_short_result_is_untouched(self):
        self.assertEqual(SessionRunner._bound_for_model("ok" + NOTES), "ok" + NOTES)


if __name__ == "__main__":
    unittest.main()
