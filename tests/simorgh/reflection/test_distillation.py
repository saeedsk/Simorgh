"""Turning a solved problem into a skill (reflection/distillation.py).

Sim could always write skills when asked; what it never did was notice
it had just worked something out that will be needed again. The 95120
task is the example -- solved twice on 2026-09-09, from scratch both
times.

Most of these assert the *refusals*, because the failure mode of being
eager here is a skills directory full of near-duplicates nobody trusts.
"""

from __future__ import annotations

import unittest

from simorgh.reflection.distillation import candidate_for, slug_for


class CandidateTestCase(unittest.TestCase):
    def _candidate(self, **over):
        base = dict(
            kind="patch", succeeded=True,
            description="build a page of real for-sale listings for San Jose 95120",
            tools=["search_listings", "apply_source_patch", "git_commit", "render_page"],
        )
        base.update(over)
        return candidate_for(**base)

    def test_a_solved_tool_using_task_is_worth_distilling(self):
        candidate = self._candidate()
        self.assertIsNotNone(candidate)
        self.assertIn("95120", candidate.slug)
        self.assertIn("search_listings", candidate.tools)

    def test_the_description_tells_the_skill_task_what_to_generalise(self):
        candidate = self._candidate()
        self.assertIn("arguments", candidate.description)
        self.assertIn("Do not hard-code", candidate.description)
        self.assertIn("search_listings", candidate.description)

    def test_a_failed_task_is_never_distilled(self):
        self.assertIsNone(self._candidate(succeeded=False))

    def test_a_chat_turn_is_never_distilled(self):
        self.assertIsNone(self._candidate(kind="chat"))

    def test_an_ordinary_edit_is_not_a_technique(self):
        # read, patch, commit is what `patch` already does. There is no
        # skill in it, and proposing one for every edit would bury the
        # ones that matter.
        self.assertIsNone(self._candidate(
            tools=["read_file", "apply_source_patch", "git_commit", "run_tests"]))

    def test_too_few_tools_is_not_a_technique_either(self):
        self.assertIsNone(self._candidate(tools=["search_listings", "git_commit"]))

    def test_a_granted_or_mcp_tool_counts_as_reaching_outside(self):
        for tool in ("x_hh_scrape", "mcp_time_get_current_time"):
            with self.subTest(tool=tool):
                self.assertIsNotNone(self._candidate(
                    tools=[tool, "apply_source_patch", "git_commit"]))

    def test_research_tasks_qualify_too(self):
        self.assertIsNotNone(candidate_for(
            kind="research", succeeded=True, description="what is the weather history for San Jose",
            tools=["web_fetch", "web_search", "run_script"]))


class SlugTestCase(unittest.TestCase):
    def test_a_slug_keeps_the_identifying_number_even_when_it_comes_last(self):
        # Taking the first four words alone named this
        # `page_real_sale_listings`, which describes half the tasks
        # anyone would ever ask for. `95120` is what makes it this one.
        self.assertEqual(
            slug_for("build a page of real for-sale listings for San Jose 95120"),
            "page_real_sale_95120")

    def test_filler_words_are_dropped(self):
        self.assertNotIn("the", slug_for("build the thing with the stuff").split("_"))

    def test_a_collision_gets_a_suffix_rather_than_overwriting(self):
        existing = {"page_real_sale_95120"}
        slug = slug_for("build a page of real for-sale listings for San Jose 95120", existing)
        self.assertEqual(slug, "page_real_sale_95120_2")

    def test_an_empty_description_still_yields_a_name(self):
        self.assertEqual(slug_for(""), "distilled_skill")

    def test_an_existing_skill_of_that_name_is_not_proposed_again_verbatim(self):
        candidate = candidate_for(
            kind="patch", succeeded=True, description="scrape listings and map them",
            tools=["search_listings", "geocode", "apply_source_patch"],
            existing_skills={"scrape_listings_map"})
        self.assertIsNotNone(candidate)
        self.assertNotEqual(candidate.slug, "scrape_listings_map")
