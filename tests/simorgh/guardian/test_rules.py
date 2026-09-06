"""Per-rule tables for `simorgh.guardian.rules` (09-guardian.md section
5.1's pipeline). Each rule is a pure function of (Proposal, DecisionContext),
so these are exercised directly, without a Pipeline or a Service."""

import unittest

from simorgh.guardian.api import BudgetStatus, DecisionContext, Proposal, ToolInfo
from simorgh.guardian.config import Config
from simorgh.guardian.posture import Posture
from simorgh.guardian.rules import (
    BudgetRule,
    DenylistRule,
    ImmunityRule,
    ModeRule,
    PausedRule,
    ProtectedRule,
    ReversibilityRule,
    ScopeRule,
    similarity,
)


def _proposal(**overrides) -> Proposal:
    base = dict(
        action_id="a1", tool="read_file", args={}, scope={}, reversibility="read_only",
        rationale="test", proposed_by="test",
    )
    base.update(overrides)
    return Proposal(**base)


def _ctx(**overrides) -> DecisionContext:
    base = dict(
        now=0.0, system_state="running", posture=Posture(level="guarded", baseline="guarded"),
        config=Config(),
    )
    base.update(overrides)
    return DecisionContext(**base)


async def _evaluate(rule, proposal, ctx):
    return await rule.evaluate(proposal, ctx)


class TestPausedRule(unittest.IsolatedAsyncioTestCase):
    async def test_denies_when_paused_or_stopping(self):
        for state in ("paused", "stopping"):
            decision = await _evaluate(PausedRule(), _proposal(), _ctx(system_state=state))
            self.assertEqual(decision.kind, "deny")

    async def test_abstains_when_running(self):
        decision = await _evaluate(PausedRule(), _proposal(), _ctx(system_state="running"))
        self.assertEqual(decision.kind, "abstain")


class TestModeRule(unittest.IsolatedAsyncioTestCase):
    async def test_observe_denies_everything(self):
        decision = await _evaluate(
            ModeRule(), _proposal(), _ctx(config=Config(mode="observe")),
        )
        self.assertEqual(decision.kind, "deny")

    async def test_locked_mode_denies_non_read_only_for_everyone(self):
        ctx = _ctx(config=Config(mode="locked"), tool=ToolInfo("git_commit", read_only=False, reversibility="reversible"))
        decision = await _evaluate(ModeRule(), _proposal(proposed_by="human"), ctx)
        self.assertEqual(decision.kind, "deny")

    async def test_locked_mode_allows_read_only(self):
        ctx = _ctx(config=Config(mode="locked"), tool=ToolInfo("read_file", read_only=True, reversibility="read_only"))
        decision = await _evaluate(ModeRule(), _proposal(), ctx)
        self.assertEqual(decision.kind, "abstain")

    async def test_locked_posture_narrows_only_autonomous_origins(self):
        posture = Posture(level="locked", baseline="guarded")
        ctx = _ctx(posture=posture, tool=ToolInfo("git_commit", read_only=False, reversibility="reversible"))
        autonomous = await _evaluate(ModeRule(), _proposal(origin="curiosity"), ctx)
        human = await _evaluate(ModeRule(), _proposal(origin="human"), ctx)
        self.assertEqual(autonomous.kind, "deny")
        self.assertEqual(human.kind, "abstain")

    async def test_plan_task_mode_denies_non_read_only(self):
        ctx = _ctx(tool=ToolInfo("git_commit", read_only=False, reversibility="reversible"))
        decision = await _evaluate(ModeRule(), _proposal(task_mode="plan"), ctx)
        self.assertEqual(decision.kind, "deny")


class TestProtectedRule(unittest.IsolatedAsyncioTestCase):
    async def test_denies_a_subject_arg_prefix_matching_a_protected_path(self):
        decision = await _evaluate(
            ProtectedRule(), _proposal(args={"subject": "docs/SOUL.md"}), _ctx(),
        )
        self.assertEqual(decision.kind, "deny")

    async def test_denies_a_path_under_a_protected_directory(self):
        decision = await _evaluate(
            ProtectedRule(), _proposal(args={"path": "simorgh/guardian/service.py"}), _ctx(),
        )
        self.assertEqual(decision.kind, "deny")

    async def test_denies_via_scope_paths_too(self):
        decision = await _evaluate(
            ProtectedRule(), _proposal(scope={"paths": ["simorgh/kernel/service.py"]}), _ctx(),
        )
        self.assertEqual(decision.kind, "deny")

    async def test_abstains_for_an_unprotected_path(self):
        decision = await _evaluate(
            ProtectedRule(), _proposal(args={"path": "docs/blueprint/subsystems/09-guardian.md"}), _ctx(),
        )
        self.assertEqual(decision.kind, "abstain")


class TestScopeRule(unittest.IsolatedAsyncioTestCase):
    async def test_always_abstains(self):
        decision = await _evaluate(ScopeRule(), _proposal(), _ctx())
        self.assertEqual(decision.kind, "abstain")


class TestDenylistRule(unittest.IsolatedAsyncioTestCase):
    async def test_denies_os_system(self):
        decision = await _evaluate(
            DenylistRule(), _proposal(args={"code": "import os\nos.system('ls')"}), _ctx(),
        )
        self.assertEqual(decision.kind, "deny")
        self.assertIn("Directive 1", decision.reasons[0])

    async def test_denies_subprocess(self):
        decision = await _evaluate(
            DenylistRule(), _proposal(args={"code": "subprocess.run(['ls'])"}), _ctx(),
        )
        self.assertEqual(decision.kind, "deny")

    async def test_denies_eval(self):
        decision = await _evaluate(DenylistRule(), _proposal(args={"code": "eval(x)"}), _ctx())
        self.assertEqual(decision.kind, "deny")

    async def test_abstains_on_clean_code(self):
        decision = await _evaluate(
            DenylistRule(), _proposal(args={"code": "def f(x):\n    return x + 1\n"}), _ctx(),
        )
        self.assertEqual(decision.kind, "abstain")

    async def test_abstains_when_no_code_arg(self):
        decision = await _evaluate(DenylistRule(), _proposal(args={"path": "x"}), _ctx())
        self.assertEqual(decision.kind, "abstain")


class TestSimilarity(unittest.TestCase):
    def test_finds_the_best_match_at_or_above_threshold(self):
        result = similarity("def f(x):\n    return x + 1\n", ["totally unrelated", "def f(x):\n    return x + 1\n"], 0.85)
        self.assertIsNotNone(result)
        ratio, excerpt = result
        self.assertGreaterEqual(ratio, 0.85)

    def test_returns_none_below_threshold(self):
        result = similarity("abc", ["xyz completely different content here"], 0.85)
        self.assertIsNone(result)


class TestImmunityRule(unittest.IsolatedAsyncioTestCase):
    async def test_denies_code_similar_to_a_past_rejection(self):
        code = "def f(x):\n    return x + 1\n"
        ctx = _ctx(rejected_similarity=lambda c: similarity(c, [code], 0.85))
        decision = await _evaluate(ImmunityRule(), _proposal(args={"code": code}), ctx)
        self.assertEqual(decision.kind, "deny")

    async def test_abstains_when_not_similar(self):
        ctx = _ctx(rejected_similarity=lambda c: None)
        decision = await _evaluate(ImmunityRule(), _proposal(args={"code": "anything"}), ctx)
        self.assertEqual(decision.kind, "abstain")

    async def test_abstains_when_no_code_arg(self):
        decision = await _evaluate(ImmunityRule(), _proposal(), _ctx())
        self.assertEqual(decision.kind, "abstain")


class TestBudgetRule(unittest.IsolatedAsyncioTestCase):
    async def test_abstains_for_non_costing_tools(self):
        decision = await _evaluate(BudgetRule(), _proposal(tool="read_file"), _ctx())
        self.assertEqual(decision.kind, "abstain")

    async def test_abstains_gracefully_when_no_budget_data_has_ever_arrived(self):
        decision = await _evaluate(BudgetRule(), _proposal(tool="draft_patch"), _ctx(budgets={}))
        self.assertEqual(decision.kind, "abstain")

    async def test_denies_when_a_budget_is_exhausted(self):
        ctx = _ctx(budgets={"anthropic": BudgetStatus(provider="anthropic", fraction_used=1.0)})
        decision = await _evaluate(BudgetRule(), _proposal(tool="draft_patch"), ctx)
        self.assertEqual(decision.kind, "deny")

    async def test_abstains_when_budget_is_under_cap(self):
        ctx = _ctx(budgets={"anthropic": BudgetStatus(provider="anthropic", fraction_used=0.5)})
        decision = await _evaluate(BudgetRule(), _proposal(tool="draft_patch"), ctx)
        self.assertEqual(decision.kind, "abstain")


class TestReversibilityRule(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_always_allowed(self):
        decision = await _evaluate(ReversibilityRule(), _proposal(reversibility="read_only"), _ctx())
        self.assertEqual(decision.kind, "allow")

    async def test_reversible_allowed_in_guarded(self):
        decision = await _evaluate(ReversibilityRule(), _proposal(reversibility="reversible"), _ctx())
        self.assertEqual(decision.kind, "allow")

    async def test_reversible_denied_when_locked(self):
        posture = Posture(level="locked", baseline="guarded")
        decision = await _evaluate(
            ReversibilityRule(), _proposal(reversibility="reversible"), _ctx(posture=posture),
        )
        self.assertEqual(decision.kind, "deny")

    async def test_irreversible_escalates_by_default(self):
        decision = await _evaluate(ReversibilityRule(), _proposal(reversibility="irreversible"), _ctx())
        self.assertEqual(decision.kind, "escalate")

    async def test_irreversible_allowed_when_trusted(self):
        decision = await _evaluate(
            ReversibilityRule(), _proposal(reversibility="irreversible"), _ctx(config=Config(mode="trusted")),
        )
        self.assertEqual(decision.kind, "allow")

    async def test_irreversible_denied_when_locked(self):
        posture = Posture(level="locked", baseline="guarded")
        decision = await _evaluate(
            ReversibilityRule(), _proposal(reversibility="irreversible"), _ctx(posture=posture),
        )
        self.assertEqual(decision.kind, "deny")

    async def test_irreversible_allowed_when_human_approval_not_required(self):
        ctx = _ctx(config=Config(irreversible_requires_human=False))
        decision = await _evaluate(ReversibilityRule(), _proposal(reversibility="irreversible"), ctx)
        self.assertEqual(decision.kind, "allow")


if __name__ == "__main__":
    unittest.main()
