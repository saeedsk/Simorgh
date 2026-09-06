import unittest

from simorgh.curiosity.projectproposal import OpenEndedProjectProposer, parse_goal


class ParseGoalTest(unittest.TestCase):
    def test_parses_goal_line(self):
        self.assertEqual(parse_goal("GOAL :: build a real backoff policy"), "build a real backoff policy")

    def test_case_insensitive(self):
        self.assertEqual(parse_goal("goal :: x"), "x")

    def test_returns_none_without_goal_line(self):
        self.assertIsNone(parse_goal("no goal here"))

    def test_returns_none_on_empty_match(self):
        self.assertIsNone(parse_goal("GOAL ::    "))


class OpenEndedProjectProposerTest(unittest.IsolatedAsyncioTestCase):
    async def test_floor_reply_yields_no_goal(self):
        async def think(purpose, prompt, *, expected=None):
            return "", True, "none"

        proposer = OpenEndedProjectProposer()
        self.assertIsNone(await proposer.propose(["a.py"], think))

    async def test_files_are_included_in_prompt(self):
        seen = {}

        async def think(purpose, prompt, *, expected=None):
            seen["prompt"] = prompt
            seen["purpose"] = purpose
            return "GOAL :: ship it", False, "fake"

        proposer = OpenEndedProjectProposer()
        goal = await proposer.propose(["a.py", "b.py"], think)
        self.assertEqual(goal, "ship it")
        self.assertEqual(seen["purpose"], "plan")
        self.assertIn("a.py", seen["prompt"])
        self.assertIn("b.py", seen["prompt"])

    async def test_empty_file_list_still_prompts(self):
        async def think(purpose, prompt, *, expected=None):
            self.assertIn("(none found)", prompt)
            return "GOAL :: x", False, "fake"

        proposer = OpenEndedProjectProposer()
        self.assertEqual(await proposer.propose([], think), "x")


if __name__ == "__main__":
    unittest.main()
