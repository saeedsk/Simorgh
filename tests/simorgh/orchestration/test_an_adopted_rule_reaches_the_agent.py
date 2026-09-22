"""`rules/<agent>.md` follows the agent's body (stage 8 item 5).

Nothing read `rules/`, so an adopted policy changed nothing Sim did.
"""

import tempfile
import unittest
from pathlib import Path

from simorgh.orchestration import profiles


class ARule(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.rules = Path(tmp.name)

    def test_it_follows_its_own_agents_body_only(self):
        (self.rules / "patch.md").write_text("- Run the whole suite before committing.\n<!-- adopted 2026-09-22 -->\n")
        agents = profiles.load(rules=self.rules)
        self.assertTrue(agents["patch"].body.endswith("- Run the whole suite before committing."))
        self.assertNotIn("adopted 2026-09-22", agents["patch"].body, "a note for people reached the prompt")
        self.assertNotIn("Lessons adopted", agents["research"].body)

    def test_no_rules_no_change(self):
        self.assertEqual(profiles.load(rules=self.rules)["patch"].body, profiles.load(rules=None)["patch"].body)


if __name__ == "__main__":
    unittest.main()
