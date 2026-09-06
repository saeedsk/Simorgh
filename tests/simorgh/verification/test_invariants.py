"""`invariant_violations` -- a generalization of `check_main_py_invariants`
from `src/orchestrator/self_patch.py` (see checks/invariants.py), plus a
v2 prefix (`simorgh/execution/`, `simorgh/guardian/`)."""

import unittest

from simorgh.verification.checks.invariants import invariant_violations
from simorgh.verification.config import VerificationConfig

_TABLE = VerificationConfig().invariants


class TestInvariantViolations(unittest.TestCase):
    def test_main_py_missing_audit_gate_is_flagged(self):
        content = "def apply_proposal(p):\n    return p\n"
        missing = invariant_violations("src/main.py", content, _TABLE)
        self.assertIn("AuditGate(", missing)
        self.assertIn("audit_gate.review(", missing)

    def test_main_py_with_all_wiring_present_is_clean(self):
        content = "gate = AuditGate()\naudit_gate.review(x)\napply_proposal(y)\n"
        self.assertEqual(invariant_violations("src/main.py", content, _TABLE), [])

    def test_v2_execution_prefix_requires_verifier_call(self):
        missing = invariant_violations("simorgh/execution/service.py", "def run():\n    pass\n", _TABLE)
        self.assertIn("verifier.verify(", missing)

    def test_v2_guardian_prefix_requires_pipeline(self):
        missing = invariant_violations("simorgh/guardian/service.py", "def run():\n    pass\n", _TABLE)
        self.assertIn("Pipeline(", missing)

    def test_unrelated_path_has_no_table_entry(self):
        self.assertEqual(invariant_violations("simorgh/persona/service.py", "anything at all", _TABLE), [])


if __name__ == "__main__":
    unittest.main()
