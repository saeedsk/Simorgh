"""Iris, mid-conversation: "But, I mean..." got QUIET, then "Sim, I was
talking to you." (live 2026-09-15). A trailing fragment from the person
Sim is already talking with is a pause, not someone else's words."""

import unittest

from simorgh.orchestration import profiles, scaffolds


class APauseInAConversation(unittest.TestCase):
    def test_the_voice_rules_say_so(self):
        text = scaffolds.render(profiles.CHAT, channel="voice")
        self.assertIn("a conversation you are already in", text)
        self.assertIn('"Go on"', text)
        # The general rule for other people's trailing sentences still stands.
        self.assertIn("a sentence that trails off is not an invitation: QUIET", text)


if __name__ == "__main__":
    unittest.main()
