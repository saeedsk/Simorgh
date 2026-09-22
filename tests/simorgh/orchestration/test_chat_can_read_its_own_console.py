"""`console_tail` is registered, and its description says it is "the ONLY
way to answer a question about Sim's own screen, output or error
messages" -- and no agent listed it, so no chat turn could ever call it.

Live, 2026-09-22: asked "was there any provider timeout in the past 30
minutes?" four minutes after three providers timed out, Sim searched its
memory, found nothing and said it had no log to look at. It did.
"""

import unittest

from simorgh.orchestration import profiles


class TheConsoleIsReachable(unittest.TestCase):
    def test_the_chat_profiles_may_ask_for_it(self):
        for name in ("chat", "voice_chat"):
            self.assertIn("console_tail", profiles.AGENTS[name].tools, name)

    def test_every_registered_tool_is_in_some_agent_or_deliberately_not(self):
        """The wire this test exists for: a registered tool no agent can
        reach. `policy_adopt` is the one exception -- growth proposes it
        and a person approves it, no session ever asks."""
        from simorgh.domains import domain_tools
        from simorgh.execution.config import Config
        from simorgh.execution.tools import builtin_tools

        reachable = {t for agent in profiles.AGENTS.values() for t in agent.tools}
        registered = {t.name for t in builtin_tools(Config()) + domain_tools(Config(), secrets=None)}
        # Deliberately not offered to any agent, each for a reason:
        by_hand = {
            # Setup verbs: they take a password or a pairing code at the
            # terminal, and a model cannot supply either.
            "cam_setup", "cast_setup", "ring_setup", "tv_pair", "cast_use",
            # Proposed by a subsystem, never asked for in a turn.
            "policy_adopt",      # growth, after a measurement, with a person's yes
            "speak",             # initiative decides when Sim speaks unprompted
            "ring_live",         # the dashboard opens a live view, not a sentence
            # The session runner proposes these around a code task.
            "worktree_open", "worktree_land", "worktree_close",
        }
        unreachable = registered - reachable - by_hand
        self.assertEqual(unreachable, set(), f"registered but no agent can ask for: {sorted(unreachable)}")


if __name__ == "__main__":
    unittest.main()
