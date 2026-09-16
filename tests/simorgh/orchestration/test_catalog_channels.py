"""The skill catalog is not sent where it cannot be used.

It rides in `task_rules` on EVERY think call. A spoken turn will never
ask for "create new skills" or "build an MCP server", so on voice it is
pure cost: 157 tokens per call for two bundled skills, ~710 at ten, and
past that the 3000-char cap silently drops entries.

The creator, 2026-09-16: "we should make the charge zero when the skills
are not needed ... our system should have the concept of being frugal
where ever it is possible."

Voice and typed chat cannot be told apart by profile -- `for_percept`
returns VOICE_CHAT or CHAT and both are named "chat" -- but the Session
carries the channel it arrived on.
"""

from __future__ import annotations

import types
import unittest


def _runner(channels=("", "cli", "http"), cards=("skill-creator", "mcp-builder")):
    from simorgh.orchestration.session import SessionRunner

    runner = object.__new__(SessionRunner)
    runner._skills_channels = channels
    runner._skills_catalog_max_chars = 3000
    runner._skills = lambda: [
        types.SimpleNamespace(name=n, description=f"what {n} does", allowed_profiles=())
        for n in cards
    ]
    return runner


def _session(channel):
    return types.SimpleNamespace(channel=channel, profile=types.SimpleNamespace(name="chat"))


class WhoPaysForTheCatalog(unittest.TestCase):
    def test_a_voice_turn_carries_none_of_it(self):
        self.assertEqual(_runner()._catalog(_session("voice")), "", "a spoken turn pays nothing")

    def test_a_typed_turn_still_gets_it(self):
        said = _runner()._catalog(_session(""))
        self.assertIn("skill-creator", said)
        self.assertIn("mcp-builder", said)

    def test_the_cli_and_http_channels_get_it(self):
        for channel in ("cli", "http"):
            self.assertIn("skill-creator", _runner()._catalog(_session(channel)), channel)

    def test_an_empty_allow_list_charges_nobody(self):
        self.assertEqual(_runner(channels=())._catalog(_session("")), "")
        self.assertEqual(_runner(channels=())._catalog(_session("voice")), "")

    def test_voice_can_be_opted_in_deliberately(self):
        said = _runner(channels=("", "voice"))._catalog(_session("voice"))
        self.assertIn("skill-creator", said, "the allow-list is a choice, not a ban")

    def test_no_skills_means_no_block_even_on_an_allowed_channel(self):
        self.assertEqual(_runner(cards=())._catalog(_session("")), "")

    def test_a_session_without_a_channel_attribute_is_treated_as_typed(self):
        """Task sessions are built without a channel; they must keep it."""
        bare = types.SimpleNamespace(profile=types.SimpleNamespace(name="chat"))
        self.assertIn("skill-creator", _runner()._catalog(bare))


if __name__ == "__main__":
    unittest.main()
