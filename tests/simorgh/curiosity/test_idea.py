import unittest

from simorgh.curiosity.api import Target
from simorgh.curiosity.idea import TargetedIdeaProposer, parse_targeted_idea


class ParseTargetedIdeaTest(unittest.TestCase):
    def test_parses_patch(self):
        idea = parse_targeted_idea("PATCH :: tighten the retry loop")
        self.assertEqual(idea.kind, "patch")
        self.assertEqual(idea.description, "tighten the retry loop")

    def test_parses_research_case_insensitive(self):
        idea = parse_targeted_idea("research :: is there a simpler backoff formula?")
        self.assertEqual(idea.kind, "research")

    def test_ignores_leading_whitespace_and_extra_lines(self):
        idea = parse_targeted_idea("some preamble\n   PATCH ::  add a docstring  \ntrailer")
        self.assertEqual(idea.description, "add a docstring")

    def test_returns_none_when_no_line_matches(self):
        self.assertIsNone(parse_targeted_idea("I think we should just rewrite everything."))

    def test_returns_none_on_empty_text(self):
        self.assertIsNone(parse_targeted_idea(""))


class TargetedIdeaProposerTest(unittest.IsolatedAsyncioTestCase):
    async def test_floor_reply_yields_no_idea(self):
        async def think(purpose, prompt, *, expected=None):
            return "", True, "none"

        proposer = TargetedIdeaProposer()
        idea = await proposer.propose(Target(area="a", subject="m.py"), "", think)
        self.assertIsNone(idea)

    async def test_model_naming_a_different_file_does_not_change_the_subject(self):
        """Spec scenario S2: the model ignores 'don't second-guess the
        target' and states a different path anyway. The proposer only
        ever returns kind/description -- `service.py` is what pins
        `subject` to the originally sampled Target, never anything
        parsed from the reply. This test locks that the parser itself
        has no path-extraction capability to misuse."""
        async def think(purpose, prompt, *, expected=None):
            return "Actually let's look at other_file.py instead.\nPATCH :: refactor the loop", False, "fake"

        proposer = TargetedIdeaProposer()
        idea = await proposer.propose(Target(area="a", subject="sampled_target.py"), "", think)
        self.assertEqual(idea.kind, "patch")
        self.assertNotIn("other_file.py", idea.description)

    async def test_prompt_includes_sampled_subject_and_preview(self):
        seen = {}

        async def think(purpose, prompt, *, expected=None):
            seen["purpose"] = purpose
            seen["prompt"] = prompt
            return "PATCH :: x", False, "fake"

        proposer = TargetedIdeaProposer()
        await proposer.propose(Target(area="a", subject="path/to/m.py"), "def f(): pass", think)
        self.assertEqual(seen["purpose"], "draft")
        self.assertIn("path/to/m.py", seen["prompt"])
        self.assertIn("def f(): pass", seen["prompt"])


if __name__ == "__main__":
    unittest.main()
