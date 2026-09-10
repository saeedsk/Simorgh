"""`workspace/`: scratch that survives, and is never mistaken for source.

Every writable directory Sim had was source, so anything it wrote was a
change somebody had to review. An intermediate file, a scratch note, a
half-finished dataset had nowhere to live -- `results/` is tool-written
and PRUNED, so it cannot hold anything meant to last.

The two properties that make this a workspace rather than one more
source directory are both about what does NOT happen to a file written
there, and both are easy to regress by touching the side-effect loop in
`session.py`:

  1. it is never an "uncommitted change", so a scratch note cannot
     block a finished task, and
  2. cleanup never deletes it, which is what "persistent" means.

It is still recorded as WRITTEN, so the verification checks that read
files (`syntax`, `js_syntax`, `render`) can see it.
"""

from __future__ import annotations

import unittest

from simorgh.contracts.scratch import SCRATCH_PREFIX
from simorgh.execution.config import Config
from simorgh.orchestration.session import is_scratch, record_side_effects


class ScratchPathTestCase(unittest.TestCase):
    def test_the_workspace_is_scratch(self):
        self.assertTrue(is_scratch("workspace/notes.md"))
        self.assertTrue(is_scratch("workspace/data/prices.csv"))
        self.assertTrue(is_scratch("./workspace/notes.md"))

    def test_source_is_not_scratch(self):
        for path in ("simorgh/foo.py", "tests/test_x.py", "docs/plan.md", "results/a.json", ""):
            with self.subTest(path=path):
                self.assertFalse(is_scratch(path))

    def test_a_lookalike_directory_is_not_scratch(self):
        # `workspaces/` is somebody else's directory, not this one.
        self.assertFalse(is_scratch("workspaces/x"))
        self.assertFalse(is_scratch("myworkspace/x"))


class ConfigurationTestCase(unittest.TestCase):
    def test_it_is_the_one_directory_that_is_both_readable_and_writable(self):
        config = Config()
        self.assertIn("workspace", config.readable_roots)
        self.assertIn("workspace/", config.write_scopes_source)

    def test_the_scratch_name_is_not_a_settable_key(self):
        # `[execution] workspace_dir = "scratch"` used to be accepted and
        # read by nothing: the scopes below and `contracts.scratch` both
        # said `workspace/` regardless, so the setting produced a
        # directory that was neither writable nor scratch. The name has
        # one definition now, and no key advertises otherwise.
        self.assertFalse(hasattr(Config(), "workspace_dir"))
        self.assertNotIn("workspace_dir", Config.__dataclass_fields__)
        config = Config()
        self.assertIn(SCRATCH_PREFIX.rstrip("/"), config.readable_roots)
        self.assertIn(SCRATCH_PREFIX, config.write_scopes_source)

    def test_no_other_write_scope_is_scratch(self):
        # If a second scratch scope is ever added, `is_scratch` has to
        # learn about it or cleanup will start deleting it.
        scratch = [s for s in Config().write_scopes_source if is_scratch(s)]
        self.assertEqual(scratch, ["workspace/"])

    def test_the_results_directory_stays_read_only(self):
        # results/ is the tool-written twin: readable so data can be
        # analysed, never writable so it cannot be committed.
        config = Config()
        self.assertIn("results", config.readable_roots)
        self.assertNotIn("results/", config.write_scopes_source)

    def test_it_is_gitignored(self):
        """Asked of git, not of the file's text.

        This test used to assert that the line `workspace/` appeared in
        `.gitignore`, and it passed for months while git ignored nothing
        at all: a later `!workspace/` un-ignored the directory, which
        lets git descend back into it, so every scratch file inside was
        untracked and one `git add -A` from being committed. The line
        was there; the behaviour was the opposite of what the line
        promised. Only asking git can tell the difference."""
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]

        def _ignored(relative: str) -> bool:
            done = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", relative],
                                  capture_output=True)
            return done.returncode == 0

        self.assertTrue(_ignored("workspace/scratch-note.md"),
                        "a file written to the scratch workspace must never be committable")
        self.assertTrue(_ignored("workspace/nested/deep/thing.json"))
        # ...and the README stays tracked, so a fresh clone still has
        # the directory and Sim has somewhere to write on its first run.
        self.assertFalse(_ignored("workspace/README.md"))


class SideEffectRoutingTestCase(unittest.TestCase):
    """`session.py::record_side_effects` -- the real function, not a
    copy of it. The sets it fills decide whether cleanup deletes a file
    and whether a finished task is blocked."""

    class _Session:
        def __init__(self):
            self.uncommitted, self.created, self.wrote = set(), set(), set()

    def _route(self, effects):
        session = self._Session()
        record_side_effects(session, effects)
        return session

    def test_a_scratch_file_is_written_but_never_uncommitted(self):
        session = self._route(["file_create:workspace/notes.md"])
        self.assertIn("workspace/notes.md", session.wrote)
        self.assertEqual(session.uncommitted, set(), "scratch must not block finishing a task")
        self.assertEqual(session.created, set(), "cleanup must not delete a persistent workspace")

    def test_a_source_file_still_behaves_exactly_as_before(self):
        session = self._route(["file_create:simorgh/new.py", "file_write:tests/old.py"])
        self.assertEqual(session.uncommitted, {"simorgh/new.py", "tests/old.py"})
        self.assertEqual(session.created, {"simorgh/new.py"})
        self.assertEqual(session.wrote, {"simorgh/new.py", "tests/old.py"})

    def test_a_mixed_attempt_separates_the_two(self):
        session = self._route(["file_write:simorgh/a.py", "file_create:workspace/scratch.json"])
        self.assertEqual(session.uncommitted, {"simorgh/a.py"})
        self.assertEqual(session.wrote, {"simorgh/a.py", "workspace/scratch.json"})

    def test_a_commit_clears_the_uncommitted_record(self):
        session = self._route(["file_create:simorgh/a.py", "git_commit:simorgh/a.py"])
        self.assertEqual(session.uncommitted, set())
        self.assertEqual(session.created, set())
        self.assertIn("simorgh/a.py", session.wrote,
                      "`wrote` only ever grows -- the verification checks still need the path")

    def test_a_discard_clears_it_too(self):
        session = self._route(["file_write:tests/a.py", "git_discard:tests/a.py"])
        self.assertEqual(session.uncommitted, set())

    def test_an_effect_with_no_path_is_ignored(self):
        session = self._route(["run_shell", "file_write:", "run_remote:make"])
        self.assertEqual(session.wrote, set())
        self.assertEqual(session.uncommitted, set())


class ThePromptSaysSoTestCase(unittest.TestCase):
    """A capability nothing tells the model about is an unconnected
    wire: the directory would exist and never be used."""

    def test_the_write_hint_mentions_the_workspace(self):
        from simorgh.orchestration.tools import marker_hint

        self.assertIn("workspace/", marker_hint("apply_source_patch") or "")

    def test_the_hint_says_it_persists(self):
        from simorgh.orchestration.tools import marker_hint

        hint = (marker_hint("apply_source_patch") or "").lower()
        self.assertIn("scratch", hint)
        self.assertTrue("next session" in hint or "survives" in hint)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
