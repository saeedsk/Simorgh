"""Stage 7 item 3: a plan is typed JSON, validated, and refused by name
when it is wrong.

The regex form read two line shapes and ignored everything else, so a
planner answering in prose produced no steps and nobody could tell that
from "there are no steps" -- which is how 21 of the creator's projects
came to sit at 0/0. A household goal also has no repo path in it, which
the line format could not express at all."""

from __future__ import annotations

import unittest

from simorgh.planning.decomposer import parse_plan, parse_steps

HOUSEHOLD = """
{"nodes": [
  {"id": "a", "kind": "research", "description": "find which day the bins go out",
   "acceptance": ["the day is named", "the source is a council page or the calendar"]},
  {"id": "b", "kind": "action", "description": "set a weekly reminder the evening before",
   "depends_on": ["a"], "acceptance": ["a reminder exists for that weekday"]},
  {"id": "c", "kind": "wait", "description": "wait for the first one to fire", "depends_on": ["b"]}
]}
"""


class ATypedPlan(unittest.TestCase):
    def test_a_household_goal_decomposes_without_a_repo_path(self):
        steps, problem = parse_plan(HOUSEHOLD)
        self.assertEqual(problem, "")
        self.assertEqual(len(steps), 3)
        self.assertIn("bins", steps[0].description)
        self.assertIn("done when: the day is named", steps[0].why)
        self.assertEqual(steps[1].depends_on, (steps[0].step_id,), "edges survive the id rewrite")
        self.assertIsNone(steps[0].subject)

    def test_the_acceptance_criteria_travel_with_the_step(self):
        steps, _ = parse_plan(HOUSEHOLD)
        self.assertIn("a reminder exists for that weekday", steps[1].why)

    def test_an_invalid_plan_says_what_is_wrong(self):
        for text, expected in (
            ("I would start by looking at the calendar.", "no JSON object"),
            ('{"nodes": []}', "no `nodes`"),
            ('{"nodes": [{"kind": "wander", "description": "x"}]}', "unknown node kind"),
            ('{"nodes": [{"id": "a", "kind": "action", "description": "x", "depends_on": ["ghost"]}]}',
             "which is not a node in this plan"),
            ('{"nodes": [{"kind": "action", "description": "  "}]}', "no description"),
        ):
            with self.subTest(text=text[:30]):
                steps, problem = parse_plan(text)
                self.assertEqual(steps, [])
                self.assertIn(expected, problem)

    def test_the_line_format_still_parses(self):
        """A planner that answers in the old shape still decomposes."""
        old = "1. simorgh/memory/store.py :: add the fact store\n2. RESEARCH :: what does the council publish?"
        self.assertEqual(len(parse_steps(old, 5)), 2)

    def test_a_plan_longer_than_asked_for_is_cut_not_refused(self):
        many = '{"nodes": [' + ", ".join(
            f'{{"id": "n{i}", "kind": "research", "description": "step {i}"}}' for i in range(10)) + "]}"
        steps, problem = parse_plan(many, expected=3)
        self.assertEqual(problem, "")
        self.assertEqual(len(steps), 3)


if __name__ == "__main__":
    unittest.main()
