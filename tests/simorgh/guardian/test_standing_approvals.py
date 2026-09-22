"""\"Approve once for all similar cases\" (the creator, 2026-09-22, on
Initiative's motion-notice escalations): answering "always" approves
that kind of action from then on -- the same tool, asked by the same
requester, for the same rule's reason. Never offered for `rules/`
writes, physical actions or skills; listable and revocable."""

import unittest
from types import SimpleNamespace

from simorgh.guardian.service import NEVER_STANDING, standing_key


class TheKey(unittest.TestCase):
    def test_same_tool_and_requester_and_rule_is_the_same_kind_whatever_the_arguments(self):
        a = SimpleNamespace(tool="notify", requester="", requester_channel="initiative")
        self.assertEqual(standing_key(a, "person"), "notify|initiative|person")
        b = SimpleNamespace(tool="notify", requester="Ira", requester_channel="voice")
        self.assertNotEqual(standing_key(a, "person"), standing_key(b, "person"))

    def test_the_protected_physical_and_skill_asks_never_stand(self):
        self.assertEqual(NEVER_STANDING, frozenset({"protected", "physical", "human_only"}))


if __name__ == "__main__":
    unittest.main()
