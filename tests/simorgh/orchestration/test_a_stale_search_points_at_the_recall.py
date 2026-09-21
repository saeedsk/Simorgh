"""A failed SEARCH block is told the cheap way back.

Compaction sets old tool results aside and leaves a stub naming a
ref; `recall_result` brings the whole thing back for nothing. A
trial on 2026-09-20 never used it:

    steps 5,6,8,9,14,23  read_file  simorgh/benchmark/runner.py  (638 lines, six overlapping reads)
    step 11              context at 72%: 6 older tool results set aside
    step 19              context at 93%: 7 older tool results set aside
    step 20              refused: block 1's SEARCH text is not in runner.py

The SEARCH text was copied from a read the model could no longer
see. The refusal told it to READ_FILE the region again -- right in
general, and the expensive half of the answer here, in a session
that then ran out of steps.
"""

import unittest

from simorgh.orchestration.session import recall_hint

STALE = "refused: block 1's SEARCH text is not in simorgh/benchmark/runner.py. Nothing was changed."


class _Session:
    def __init__(self, set_aside=()):
        self.set_aside = list(set_aside)


class WhenItSpeaks(unittest.TestCase):
    def test_a_stale_search_with_something_to_recall(self):
        session = _Session([("blob:abc", "read_file")])
        hint = recall_hint(session, STALE)
        self.assertIn("RECALL_RESULT", hint)
        self.assertIn("blob:abc", hint)

    def test_it_names_the_tool_as_well_as_the_ref(self):
        """`read_file -> blob:abc` is choosable; a bare ref is not."""
        hint = recall_hint(_Session([("blob:abc", "read_file")]), STALE)
        self.assertIn("read_file -> blob:abc", hint)


class WhenItStaysQuiet(unittest.TestCase):
    def test_a_different_refusal(self):
        """A hint on every failure is noise, and noise in a tool
        result is read past."""
        session = _Session([("blob:abc", "read_file")])
        for error in ("refused: git add failed", "refused: block 1's SEARCH text appears 3 times",
                      "exit_code=2", ""):
            self.assertEqual(recall_hint(session, error), "", error)

    def test_nothing_was_set_aside(self):
        """A stale SEARCH in a session that never hit the window is
        an ordinary mistake, and saying "recall something" when there
        is nothing to recall sends the model after a tool call that
        cannot help."""
        self.assertEqual(recall_hint(_Session(), STALE), "")

    def test_a_session_with_no_such_attribute_at_all(self):
        self.assertEqual(recall_hint(object(), STALE), "")


class HowMuchItSays(unittest.TestCase):
    def test_the_newest_few_not_all_of_them(self):
        """Twenty refs in a tool result is a wall nobody reads."""
        session = _Session([(f"blob:{i}", "read_file") for i in range(20)])
        hint = recall_hint(session, STALE)
        self.assertIn("20 earlier tool result(s)", hint, "the count is honest")
        self.assertEqual(hint.count("blob:"), 3, "only the newest few are named")
        self.assertIn("blob:19", hint, "and they are the newest")

    def test_a_ref_that_failed_to_write_is_not_offered(self):
        self.assertEqual(recall_hint(_Session([("", "read_file")]), STALE), "")


if __name__ == "__main__":
    unittest.main()
