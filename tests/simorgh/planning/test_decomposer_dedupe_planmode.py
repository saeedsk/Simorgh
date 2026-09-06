import unittest

from simorgh.planning import planmode
from simorgh.planning.decomposer import parse_steps
from simorgh.planning.dedupe import is_duplicate
from simorgh.planning.model import Step


class TestParseSteps(unittest.TestCase):
    def test_parses_a_patch_line(self):
        steps = parse_steps("1. src/orchestrator/foo.py :: fix the thing", 1)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].kind, "patch")
        self.assertEqual(steps[0].subject, "src/orchestrator/foo.py")
        self.assertEqual(steps[0].description, "fix the thing")

    def test_parses_a_research_line(self):
        steps = parse_steps("1. RESEARCH :: is this worth doing", 1)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].kind, "research")
        self.assertIsNone(steps[0].subject)

    def test_research_not_misparsed_as_a_path(self):
        steps = parse_steps("1. RESEARCH :: a question", 1)
        self.assertEqual(steps[0].kind, "research")

    def test_later_patch_depends_on_earlier_research(self):
        text = "1. RESEARCH :: figure out the approach\n2. src/memory/long_term.py :: implement it\n"
        steps = parse_steps(text, 2)
        research_id = steps[0].step_id
        self.assertEqual(steps[1].depends_on, (research_id,))

    def test_skills_dir_targets_excluded(self):
        steps = parse_steps("1. src/agents/skills/rocketry.py :: add a skill", 1)
        self.assertEqual(steps, [])

    def test_non_matching_lines_ignored(self):
        text = "Sure, here's my plan:\n1. src/orchestrator/foo.py :: do it\nHope that helps!"
        steps = parse_steps(text, 1)
        self.assertEqual(len(steps), 1)

    def test_truncates_to_expected(self):
        text = "\n".join(f"{i}. src/a.py :: idea {i}" for i in range(1, 6))
        self.assertEqual(len(parse_steps(text, 3)), 3)


class TestDedupe(unittest.TestCase):
    def test_near_duplicate_pair_is_a_duplicate(self):
        a = ("Add a provider-agnostic capability negotiation layer so orchestrator code queries "
             "what a backend can do (tool-calling, context window, streaming) instead of hardcoding "
             "per-provider assumptions, enabling safer runtime provider switching.")
        b = ("Add a provider-agnostic capability negotiation layer so the orchestrator can query "
             "token limits, tool-support, and cost tier before routing, enabling smarter multi-model "
             "fallback.")
        self.assertTrue(is_duplicate(a, [b], 0.45))

    def test_unrelated_pair_is_not_a_duplicate(self):
        a = "Add embedding-based semantic retrieval instead of relying solely on recency lookup."
        b = "Add a self-model diffing pass that compares current capabilities against a snapshot."
        self.assertFalse(is_duplicate(a, [b], 0.45))

    def test_empty_existing_is_never_a_duplicate(self):
        self.assertFalse(is_duplicate("anything", [], 0.45))


class TestApprovalDecision(unittest.TestCase):
    def test_reject_verdict_is_reject(self):
        self.assertEqual(planmode.approval_decision("reject", "low", "medium"), "reject")

    def test_approve_low_risk_auto_approves(self):
        self.assertEqual(planmode.approval_decision("approve", "low", "medium"), "auto_approve")

    def test_approve_at_threshold_auto_approves(self):
        self.assertEqual(planmode.approval_decision("approve", "medium", "medium"), "auto_approve")

    def test_approve_above_threshold_asks_human(self):
        self.assertEqual(planmode.approval_decision("approve", "high", "medium"), "ask_human")

    def test_revise_is_replan(self):
        self.assertEqual(planmode.approval_decision("revise", "low", "medium"), "replan")

    def test_insufficient_evidence_is_replan(self):
        self.assertEqual(planmode.approval_decision("insufficient_evidence", "low", "medium"), "replan")


class TestComputeDiff(unittest.TestCase):
    def test_added_and_removed(self):
        before = [Step("1", "patch", "keep this", ()), Step("2", "patch", "drop this", ())]
        after = [Step("1", "patch", "keep this", ()), Step("3", "patch", "new one", ())]
        diff = planmode.compute_diff(before, after)
        self.assertEqual(diff["added"], ["new one"])
        self.assertEqual(diff["removed"], ["drop this"])
        self.assertEqual(diff["reordered"], [])

    def test_reordered(self):
        before = [Step("1", "patch", "a", ()), Step("2", "patch", "b", ())]
        after = [Step("2", "patch", "b", ()), Step("1", "patch", "a", ())]
        diff = planmode.compute_diff(before, after)
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(set(diff["reordered"]), {"a", "b"})

    def test_identical_plans_have_empty_diff(self):
        steps = [Step("1", "patch", "a", ())]
        diff = planmode.compute_diff(steps, steps)
        self.assertEqual(diff, {"added": [], "removed": [], "reordered": []})


if __name__ == "__main__":
    unittest.main()
