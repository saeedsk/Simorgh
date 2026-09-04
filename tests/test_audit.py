import unittest

from src.orchestrator.audit import AuditGate, ModificationProposal


class TestAuditGate(unittest.TestCase):
    def test_clean_code_is_approved_by_automation_but_still_needs_human(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/greeting.py",
            code="print('hello')",
            rationale="a harmless greeting skill",
        )

        verdict = gate.review(proposal)

        self.assertTrue(verdict.approved_by_automation)
        self.assertTrue(verdict.requires_human_approval)
        self.assertEqual(verdict.reasons, [])
        self.assertTrue(verdict.sandbox_result.succeeded)

    def test_denylisted_subprocess_call_is_rejected_without_running(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/sneaky.py",
            code="import subprocess; subprocess.run(['ls'])",
            rationale="lists files",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)
        self.assertTrue(verdict.requires_human_approval)
        self.assertTrue(any("subprocess" in r for r in verdict.reasons))
        self.assertIsNone(verdict.sandbox_result)

    def test_denylisted_os_system_call_is_rejected(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/sneaky.py",
            code="import os; os.system('echo hi')",
            rationale="prints hi",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)
        self.assertTrue(any("os.system" in r for r in verdict.reasons))

    def test_denylisted_eval_is_rejected(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/sneaky.py",
            code="eval(input())",
            rationale="evaluates user input",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)
        self.assertTrue(any("eval" in r for r in verdict.reasons))

    def test_code_that_fails_in_sandbox_is_not_approved(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/broken.py",
            code="raise RuntimeError('oops')",
            rationale="a buggy skill",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)
        self.assertTrue(verdict.requires_human_approval)
        self.assertIsNotNone(verdict.sandbox_result)
        self.assertFalse(verdict.sandbox_result.succeeded)

    def test_proposal_targeting_soul_py_is_always_rejected(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/orchestrator/soul.py",
            code="print('harmless')",
            rationale="tweak a directive",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)
        self.assertTrue(any("protected" in r for r in verdict.reasons))
        self.assertIsNone(verdict.sandbox_result)

    def test_proposal_targeting_soul_md_is_always_rejected(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="docs/SOUL.md",
            code="",
            rationale="rewrite the constitution",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)

    def test_proposal_targeting_audit_py_itself_is_always_rejected(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/orchestrator/audit.py",
            code="",
            rationale="disable the denylist",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)

    def test_requires_human_approval_is_always_true(self):
        gate = AuditGate()
        clean = gate.review(
            ModificationProposal(subject="x.py", code="print(1)", rationale="r")
        )
        dirty = gate.review(
            ModificationProposal(subject="x.py", code="os.system('x')", rationale="r")
        )

        self.assertTrue(clean.requires_human_approval)
        self.assertTrue(dirty.requires_human_approval)


if __name__ == "__main__":
    unittest.main()
