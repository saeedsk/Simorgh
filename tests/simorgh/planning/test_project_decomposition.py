"""Why 21 projects sat at `0/0 steps`.

Live-caught 2026-09-07, from the creator's ledger: every project showed
`0/0 steps`, and not one task in the whole ledger had a `parent_id`. No
project had ever been decomposed, and three separate breaks meant none
could have been.

1. `Worker._report` sent `"artifacts": []` -- the literal empty list,
   always -- so the plan text never reached Planning, which reads it from
   an artifact blob. Covered in tests/simorgh/orchestration.
2. `parse_steps` accepted only paths under `src/`, the *retired v1* tree.
   The live code is `simorgh/`, so every step naming a real file was
   dropped. That is this file.
3. The plan scaffold never told the model the line format Planning
   parses, so it answered in prose. Covered in
   tests/simorgh/orchestration/test_scaffolds.py.
"""

from __future__ import annotations

import unittest

from simorgh.planning.config import Config
from simorgh.planning.decomposer import DEFAULT_SOURCE_ROOTS, parse_steps


class TestParseStepsAcceptsTheLiveTree(unittest.TestCase):
    def test_a_step_naming_the_live_source_tree_is_kept(self):
        """This is the one that was silently dropped."""
        steps = parse_steps("1. simorgh/kernel/cli.py :: add a --version flag\n", 4)
        self.assertEqual([(s.kind, s.subject) for s in steps], [("patch", "simorgh/kernel/cli.py")])

    def test_a_step_naming_the_retired_v1_tree_is_still_kept(self):
        """`src/` is retired but not deleted; a step naming it should be
        visible rather than vanishing without trace."""
        steps = parse_steps("1. src/memory/store.py :: tidy the exports\n", 4)
        self.assertEqual([s.subject for s in steps], ["src/memory/store.py"])

    def test_a_research_step_needs_no_path(self):
        steps = parse_steps("1. RESEARCH :: where does the version string live\n", 4)
        self.assertEqual([(s.kind, s.subject) for s in steps], [("research", None)])

    def test_a_mixed_plan_keeps_order_and_makes_research_a_dependency(self):
        steps = parse_steps(
            "1. RESEARCH :: where the version lives\n"
            "2. simorgh/kernel/cli.py :: add the flag\n",
            4,
        )
        self.assertEqual([s.kind for s in steps], ["research", "patch"])
        self.assertEqual(steps[1].depends_on, (steps[0].step_id,))

    def test_a_path_outside_every_known_root_is_ignored(self):
        """The filter still has a job: a step must name real source."""
        self.assertEqual(parse_steps("1. /etc/passwd :: nope\n", 4), [])
        self.assertEqual(parse_steps("1. notes.txt :: nope\n", 4), [])

    def test_prose_produces_nothing_which_is_what_the_scaffold_now_prevents(self):
        """`parse_steps` reads two line shapes and ignores everything
        else. That is correct and unchanged -- the fix for the prose was
        to tell the model the format, not to loosen this."""
        self.assertEqual(parse_steps("**1. Locate the CLI entry point.** Check simorgh/cli.py\n", 4), [])

    def test_the_step_count_is_respected(self):
        text = "".join(f"{i}. simorgh/a{i}.py :: change {i}\n" for i in range(1, 9))
        self.assertEqual(len(parse_steps(text, 3)), 3)

    def test_the_roots_are_configurable_and_the_default_leads_with_the_live_tree(self):
        self.assertEqual(DEFAULT_SOURCE_ROOTS[0], "simorgh/")
        self.assertEqual(Config().source_roots, DEFAULT_SOURCE_ROOTS)
        steps = parse_steps("1. other/x.py :: change\n", 4, roots=("other/",))
        self.assertEqual([s.subject for s in steps], ["other/x.py"])


class TestTheScaffoldAndTheParserAgree(unittest.TestCase):
    """The producer and the parser were never told the same thing. This
    is the test that would have caught that."""

    def test_the_plan_scaffold_states_the_format_the_parser_reads(self):
        from simorgh.orchestration import profiles, scaffolds

        rules = scaffolds.render(profiles.PLAN)
        self.assertIn("RESEARCH ::", rules)
        self.assertIn("::", rules)
        self.assertIn("simorgh/", rules)

    def test_an_example_line_from_the_scaffold_actually_parses(self):
        from simorgh.orchestration import profiles, scaffolds

        rules = scaffolds.render(profiles.PLAN)
        example = next(line for line in rules.splitlines() if "::" in line and "RESEARCH" not in line)
        steps = parse_steps(example.strip() + "\n", 4)
        self.assertEqual(len(steps), 1, f"the scaffold's own example does not parse: {example!r}")


if __name__ == "__main__":
    unittest.main()
