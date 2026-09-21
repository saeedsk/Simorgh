"""Two searches must not buy silence on a commit that never happened.

`claimed_to_commit` bounces a reply that says work was committed when
nothing committed it. Its guard was `any(step.tool for step in
session.steps)` -- if ANY tool had run all session, the rule said
nothing.

A trial on 2026-09-21 ran two `search_code` calls, made no edit at
all, and ended:

    The task is finished. To summarise what was done and committed:

Verification caught it ("this task's product is a change to a file
and no file was changed") so nothing landed, but the sentence a human
reads still said the work was committed. Reading a file is not
committing one, and that distinction is the whole rule.
"""

import unittest

from simorgh.orchestration.stophook import COMMITTING_TOOLS, claimed_to_commit

CLAIM = "The task is finished. To summarise what was done and committed: the change is committed to main."


class _Step:
    def __init__(self, tool, ok=True):
        self.tool, self.ok = tool, ok


class _Session:
    def __init__(self, *steps):
        self.steps = list(steps)


class WhatCountsAsCommitting(unittest.TestCase):
    def test_reading_and_searching_do_not(self):
        for tool in ("search_code", "read_file", "run_tests", "web_fetch"):
            self.assertNotIn(tool, COMMITTING_TOOLS, tool)

    def test_the_ones_that_do(self):
        for tool in ("git_commit", "worktree_land", "apply_skill"):
            self.assertIn(tool, COMMITTING_TOOLS, tool)


class WhenTheClaimIsBounced(unittest.TestCase):
    def test_the_trial_that_found_this(self):
        session = _Session(_Step("search_code"), _Step("search_code"))
        self.assertIn("committed", claimed_to_commit(CLAIM, session))

    def test_a_session_that_did_nothing_at_all(self):
        self.assertIn("committed", claimed_to_commit(CLAIM, _Session()))

    def test_a_commit_that_was_refused_is_not_a_commit(self):
        session = _Session(_Step("git_commit", ok=False))
        self.assertIn("committed", claimed_to_commit(CLAIM, session))

    def test_edits_without_a_commit_still_count_as_a_false_claim(self):
        """Writing a file and saying you committed it is the original
        2026-09-15 case: "finished with uncommitted changes" in the
        same turn as "the file is committed"."""
        session = _Session(_Step("replace_in_file"))
        self.assertIn("committed", claimed_to_commit(CLAIM, session))


class WhenItStaysQuiet(unittest.TestCase):
    def test_a_real_commit(self):
        self.assertEqual(claimed_to_commit(CLAIM, _Session(_Step("git_commit"))), "")

    def test_landing_a_worktree_counts(self):
        self.assertEqual(claimed_to_commit(CLAIM, _Session(_Step("worktree_land"))), "")

    def test_a_reply_that_claims_nothing(self):
        session = _Session(_Step("search_code"))
        self.assertEqual(claimed_to_commit("I read the file and found the table.", session), "")

    def test_no_text(self):
        self.assertEqual(claimed_to_commit("", _Session()), "")


if __name__ == "__main__":
    unittest.main()
