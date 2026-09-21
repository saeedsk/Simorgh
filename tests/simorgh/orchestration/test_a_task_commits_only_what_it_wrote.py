"""A task may commit what it wrote, not what it found.

Live, 2026-09-20, and the worst thing in that evening's log. A GAIA
research case -- a question about how many bird species appear in a
video -- found the creator's uncommitted edits to
`simorgh/interface/service.py` in the working tree, ran the tests on
them, and committed them to `main`:

    404475c interface: import media clips via yt-dlp subprocess callout
    1 file changed, 21 insertions(+), 2 deletions(-)

Authored as the creator. The diff was a hundred percent somebody
else's in-flight work on an approval picker and contained no yt-dlp
code at all, so the message describes nothing that is in it.

Three things went wrong there. A research task was committing code;
it committed a file it had never touched; and it wrote a commit
message about work it had not done. This refuses the middle one,
because the other two need it: work in progress is not an untidy
repository to be helpfully tidied, and a commit message about a diff
its author never made is the honesty rule broken in the most durable
place there is.
"""

import unittest

from simorgh.orchestration.session import commit_of_unwritten_refusal


class _Session:
    def __init__(self, wrote=(), subject="", uncommitted=()):
        self.wrote = set(wrote)
        self.uncommitted = set(uncommitted)
        self.subject = subject


def _why(session, path):
    return commit_of_unwritten_refusal(session, "git_commit", {"path": path})


class WhatMayBeCommitted(unittest.TestCase):
    def test_a_file_this_task_wrote(self):
        self.assertEqual(_why(_Session(wrote={"simorgh/foo.py"}), "simorgh/foo.py"), "")

    def test_the_subject_counts_as_written(self):
        """A patch task names its file up front, and a resumed session
        that lost its write log must not be refused its own commit."""
        self.assertEqual(_why(_Session(subject="simorgh/bar.py"), "simorgh/bar.py"), "")

    def test_a_file_waiting_to_be_committed(self):
        """`uncommitted` is exactly the set this session wrote and has
        not yet committed, which is what a real git_commit is for."""
        self.assertEqual(_why(_Session(uncommitted={"simorgh/x.py"}), "simorgh/x.py"), "")

    def test_a_file_under_a_directory_it_wrote_into(self):
        self.assertEqual(_why(_Session(wrote={"simorgh/growth"}), "simorgh/growth/estimate.py"), "")


class WhatMayNot(unittest.TestCase):
    def test_the_file_the_bird_question_committed(self):
        why = _why(_Session(wrote={"workspace/scratch/birds2/results.md"}),
                   "simorgh/interface/service.py")
        self.assertIn("did not write", why)
        self.assertIn("simorgh/interface/service.py", why)

    def test_a_task_that_wrote_nothing_commits_nothing(self):
        why = _why(_Session(), "simorgh/interface/service.py")
        self.assertIn("refused", why)
        self.assertIn("nothing", why, "the message says what it did write, and it wrote nothing")

    def test_the_refusal_says_what_it_did_write(self):
        """So the model can tell the difference between "you may not
        commit" and "you committed the wrong path"."""
        why = _why(_Session(wrote={"simorgh/a.py", "simorgh/b.py"}), "simorgh/c.py")
        self.assertIn("simorgh/a.py", why)
        self.assertIn("simorgh/b.py", why)

    def test_it_says_to_leave_the_other_work_alone(self):
        why = _why(_Session(), "simorgh/interface/service.py")
        self.assertIn("work in progress", why)

    def test_a_prefix_that_is_not_a_directory_is_not_a_match(self):
        """`simorgh/foo` written must not licence committing
        `simorgh/foobar.py`."""
        self.assertIn("refused", _why(_Session(wrote={"simorgh/foo"}), "simorgh/foobar.py"))


class WhatItLeavesAlone(unittest.TestCase):
    def test_every_other_tool(self):
        session = _Session()
        for tool in ("read_file", "run_tests", "write_file", "worktree_land"):
            self.assertEqual(commit_of_unwritten_refusal(session, tool, {"path": "x.py"}), "", tool)

    def test_a_commit_with_no_path_is_left_to_the_tool(self):
        """`git_commit` requires a path; an empty one is the tool's
        own error to report, not a refusal about authorship."""
        self.assertEqual(_why(_Session(), ""), "")


if __name__ == "__main__":
    unittest.main()
