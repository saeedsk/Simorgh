"""`invariant_violations` (see checks/invariants.py): a path prefix maps to
the symbols a candidate for that path must still contain. The shipped
table covers `simorgh/execution/` and `simorgh/guardian/`; the first two
tests use a table of their own to pin the function itself."""

import unittest

from simorgh.verification.checks.invariants import invariant_violations
from simorgh.verification.config import VerificationConfig

_TABLE = VerificationConfig().invariants
_OWN = {"pkg/main.py": ["AuditGate(", "audit_gate.review(", "apply_proposal("]}


class TestInvariantViolations(unittest.TestCase):
    def test_missing_symbols_are_flagged(self):
        content = "def apply_proposal(p):\n    return p\n"
        missing = invariant_violations("pkg/main.py", content, _OWN)
        self.assertIn("AuditGate(", missing)
        self.assertIn("audit_gate.review(", missing)

    def test_with_all_wiring_present_is_clean(self):
        content = "gate = AuditGate()\naudit_gate.review(x)\napply_proposal(y)\n"
        self.assertEqual(invariant_violations("pkg/main.py", content, _OWN), [])

    def test_the_shipped_table_no_longer_names_the_retired_v1_entry_point(self):
        self.assertNotIn("src/main.py", _TABLE)

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
