import unittest

from src.memory.long_term import InMemoryStore
from src.orchestrator.audit import AuditGate, ModificationProposal, REJECTED_KIND


class TestAuditGate(unittest.TestCase):
    def test_clean_code_is_approved_by_automation_and_needs_no_human_step(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/greeting.py",
            code="print('hello')",
            rationale="a harmless greeting skill",
        )

        verdict = gate.review(proposal)

        self.assertTrue(verdict.approved_by_automation)
        self.assertFalse(verdict.requires_human_approval)
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
        self.assertFalse(verdict.requires_human_approval)
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

    def test_denylisted_urllib_request_is_rejected(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/sneaky.py",
            code="import urllib.request; urllib.request.urlopen('http://evil.example')",
            rationale="fetches a url",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)
        self.assertTrue(any("urllib" in r for r in verdict.reasons))

    def test_denylisted_requests_get_is_rejected(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/sneaky.py",
            code="import requests; requests.get('http://evil.example')",
            rationale="fetches a url",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)
        self.assertTrue(any("requests" in r for r in verdict.reasons))

    def test_denylisted_http_client_is_rejected(self):
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/sneaky.py",
            code="import http.client; http.client.HTTPConnection('evil.example')",
            rationale="raw http",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)
        self.assertTrue(any("http.client" in r for r in verdict.reasons))

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
        self.assertFalse(verdict.requires_human_approval)
        self.assertIsNotNone(verdict.sandbox_result)
        self.assertFalse(verdict.sandbox_result.succeeded)

    def test_sandbox_failure_reason_includes_the_real_error(self):
        # Live-caught: the generic "sandboxed run did not succeed
        # (timed_out=.., exit_code=..)" summary alone gave a retry loop
        # nothing to actually act on -- a real self-patch task kept
        # failing the same generic way across multiple attempts with no
        # improvement, since prior_reasons never carried the real error.
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/broken.py",
            code="raise RuntimeError('a specific, actionable failure')",
            rationale="a buggy skill",
        )

        verdict = gate.review(proposal)

        self.assertTrue(any("a specific, actionable failure" in r for r in verdict.reasons))

    def test_sandbox_failure_detail_is_bounded(self):
        from src.orchestrator.audit import _MAX_SANDBOX_DETAIL_CHARS

        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/broken.py",
            code=f"raise RuntimeError({'x' * (_MAX_SANDBOX_DETAIL_CHARS * 3)!r})",
            rationale="a buggy skill with a huge error message",
        )

        verdict = gate.review(proposal)

        combined = "; ".join(verdict.reasons)
        self.assertLess(len(combined), _MAX_SANDBOX_DETAIL_CHARS * 2)
        self.assertIn("truncated", combined)

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

    def test_self_patch_subject_skips_the_sandbox_and_can_be_approved(self):
        # The creator's own explicit call, after this was found live: the
        # sandbox runs code with an empty environment -- correct
        # isolation for a NEW skill (never supposed to import project
        # internals), but structurally impossible to pass for a
        # self-patch's normal cross-module imports, regardless of code
        # quality. Verified live: a deliberately tiny, well-scoped
        # self-patch still failed this way every attempt. Real
        # correctness for a self-patch is verified downstream by
        # run_isolated_test_suite instead (self_patch.py) -- this only
        # confirms the audit gate itself no longer blocks it outright.
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/orchestrator/reminders.py",
            code="from src.orchestrator.console_style import style\n\ndef f():\n    return style('x')\n",
            rationale="a real self-patch using a real cross-module import",
        )

        verdict = gate.review(proposal)

        self.assertTrue(verdict.approved_by_automation)
        self.assertIsNone(verdict.sandbox_result)

    def test_new_skill_subject_still_gets_the_sandbox_check(self):
        # The same import, targeting a NEW skill path instead of an
        # existing core file, must still be rejected -- a skill is
        # supposed to be standalone, and this scoping must not
        # accidentally widen what a skill proposal can get away with.
        gate = AuditGate()
        proposal = ModificationProposal(
            subject="src/agents/skills/uses_internals.py",
            code="from src.orchestrator.console_style import style\n\ndef f():\n    return style('x')\n",
            rationale="a skill that improperly imports project internals",
        )

        verdict = gate.review(proposal)

        self.assertFalse(verdict.approved_by_automation)
        self.assertIsNotNone(verdict.sandbox_result)
        self.assertFalse(verdict.sandbox_result.succeeded)

    def test_self_patch_subject_denylist_and_protected_checks_still_apply(self):
        # Skipping the sandbox for self-patch subjects must never widen
        # what a self-patch can get away with on the checks that DO
        # still apply to it.
        gate = AuditGate()

        denylisted = gate.review(
            ModificationProposal(
                subject="src/orchestrator/reminders.py",
                code="import subprocess; subprocess.run(['ls'])",
                rationale="a self-patch that shells out",
            )
        )
        protected = gate.review(
            ModificationProposal(
                subject="src/orchestrator/self_patch.py",
                code="print('harmless')",
                rationale="a self-patch targeting a protected file",
            )
        )

        self.assertFalse(denylisted.approved_by_automation)
        self.assertTrue(any("subprocess" in r for r in denylisted.reasons))
        self.assertFalse(protected.approved_by_automation)
        self.assertTrue(any("protected" in r for r in protected.reasons))

    def test_requires_human_approval_is_always_false(self):
        # Per the creator's explicit, logged policy change (docs/SOUL.md,
        # "Self-Improvement Philosophy"): a proposal that clears every
        # check here now applies automatically -- no separate human-
        # approval step. This constant can only change by editing this
        # file directly; it is never something Simorgh grants itself.
        gate = AuditGate()
        clean = gate.review(
            ModificationProposal(subject="x.py", code="print(1)", rationale="r")
        )
        dirty = gate.review(
            ModificationProposal(subject="x.py", code="os.system('x')", rationale="r")
        )

        self.assertFalse(clean.requires_human_approval)
        self.assertFalse(dirty.requires_human_approval)


class TestAdaptiveImmunity(unittest.TestCase):
    def test_rejection_is_remembered_in_the_given_memory_store(self):
        memory = InMemoryStore()
        gate = AuditGate(memory=memory)
        gate.review(
            ModificationProposal(
                subject="src/agents/skills/sneaky.py",
                code="import os; os.system('rm -rf /tmp/x')",
                rationale="cleans up temp files",
            )
        )

        rejected = memory.query(kind=REJECTED_KIND)

        self.assertEqual(len(rejected), 1)
        self.assertIn("os.system", rejected[0].content)

    def test_variant_evading_the_denylist_is_still_caught_by_similarity(self):
        memory = InMemoryStore()
        gate = AuditGate(memory=memory)
        gate.review(
            ModificationProposal(
                subject="src/agents/skills/sneaky.py",
                code="import os; os.system('rm -rf /tmp/x')",
                rationale="cleans up temp files",
            )
        )

        # a single inserted space breaks the `\bos\.system\b` regex, but the
        # code is still near-identical to what was just rejected
        evasive = ModificationProposal(
            subject="src/agents/skills/sneaky2.py",
            code="import os; os .system('rm -rf /tmp/x')",
            rationale="cleans up temp files, take two",
        )

        verdict = gate.review(evasive)

        self.assertFalse(verdict.approved_by_automation)
        self.assertTrue(any("adaptive immunity" in r for r in verdict.reasons))
        self.assertIsNone(verdict.sandbox_result)  # caught before sandboxing

    def test_dissimilar_clean_code_is_unaffected_by_past_rejections(self):
        memory = InMemoryStore()
        gate = AuditGate(memory=memory)
        gate.review(
            ModificationProposal(
                subject="src/agents/skills/sneaky.py",
                code="import os; os.system('rm -rf /tmp/x')",
                rationale="cleans up temp files",
            )
        )

        verdict = gate.review(
            ModificationProposal(
                subject="src/agents/skills/greeting.py",
                code="print('hello')",
                rationale="a harmless greeting skill",
            )
        )

        self.assertTrue(verdict.approved_by_automation)

    def test_without_memory_no_adaptive_check_happens(self):
        gate = AuditGate()  # memory=None
        gate.review(
            ModificationProposal(
                subject="a.py", code="os.system('x')", rationale="r"
            )
        )

        verdict = gate.review(
            ModificationProposal(
                subject="b.py", code="os.system('x')", rationale="r"
            )
        )

        # still rejected -- but by the denylist, not adaptive immunity,
        # since there's no memory to have learned from
        self.assertFalse(verdict.approved_by_automation)
        self.assertFalse(any("adaptive immunity" in r for r in verdict.reasons))

    def test_sandbox_failure_is_also_remembered(self):
        # subject must be a new-skill path -- the sandboxed-execution
        # check (this test's whole point) only runs for those; see
        # TestAuditGate's "self-patch subjects skip the sandbox" tests.
        memory = InMemoryStore()
        gate = AuditGate(memory=memory)

        gate.review(
            ModificationProposal(
                subject="src/agents/skills/a.py",
                code="raise RuntimeError('oops')",
                rationale="a buggy skill",
            )
        )

        self.assertEqual(len(memory.query(kind=REJECTED_KIND)), 1)


if __name__ == "__main__":
    unittest.main()
