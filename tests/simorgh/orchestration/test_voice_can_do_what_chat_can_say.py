"""The voice profile must carry the tools people say out loud.

`VOICE_CHAT` is a hand-written tool list and `CHAT` is another, so the
two drift and nothing notices -- both are even named "chat", which is
why the difference is invisible at a glance.

The creator, 2026-09-16, by voice: "remind me in 5 minutes." There was
no `remind` in `VOICE_CHAT`, so the model reached for `start_task` --
the only tool it had that could wait -- and the reminder was queued as a
background task that sat behind `auto off` instead of firing. Sim then
had to explain that its own reminder was not running.

Thirty-one tools were missing from voice that typed chat had, and they
were exactly the spoken ones: `remind`, all five `home_*` (CHAT's own
comment calls "turn the kitchen light off" the most ordinary chat
request there is), `cal_list`, the mail pair, the media trio, the energy
pair and the knowledge-base trio.

This had happened before and been half-fixed: `profiles.py` carries a
note that "Play jazz on the Mac" by voice got "I can't start Apple Music
from here" -- "true of this profile and of nothing else" -- and the
Music tools alone were added back on 2026-09-15. The rest stayed
missing. A test, rather than a third round of this.

What stays out of voice stays out on purpose: a spoken turn has six
steps and is answered, not built.
"""

from __future__ import annotations

import unittest

from simorgh.orchestration import profiles

#: Said out loud in this house, and answerable in one short turn.
SPOKEN = (
    "remind",                                                    # "remind me in 5 minutes"
    "home_find", "home_state", "home_describe", "home_call", "home_undo",   # "turn the light off"
    "cal_list",                                                  # "what's on today"
    "mail_search", "mail_read",                                  # "did the plumber reply"
    "media_now", "media_control", "media_play",                  # "pause the telly"
    "energy_status", "energy_report",                            # "what's it costing me"
    "kb_search", "kb_ask", "kb_open",                            # "what does my policy say"
)

#: Building, not answering. A six-step spoken turn should not reach these.
BUILDING = (
    "apply_source_patch", "replace_in_file", "install_package", "run_script",
    "run_python_sandboxed", "run_js_sandboxed",
)


class VoiceHasTheSpokenToolsTestCase(unittest.TestCase):
    def setUp(self):
        self.voice = set(profiles.for_percept("voice").tools)
        self.typed = set(profiles.for_percept("chat").tools)

    def test_every_spoken_request_has_its_tool(self):
        missing = sorted(t for t in SPOKEN if t not in self.voice)
        self.assertEqual(missing, [], f"a voice turn cannot answer: {missing}")

    def test_remind_in_particular(self):
        """The one that sent a reminder into the task queue."""
        self.assertIn("remind", self.voice)

    def test_the_lights_in_particular(self):
        """CHAT's own comment: the most ordinary request there is."""
        for tool in ("home_find", "home_state", "home_call"):
            self.assertIn(tool, self.voice)

    def test_building_tools_stay_out_of_a_spoken_turn(self):
        present = sorted(t for t in BUILDING if t in self.voice)
        self.assertEqual(present, [], f"voice should not build: {present}")

    def test_a_spoken_turn_is_still_short(self):
        """Widening the tools must not widen the turn."""
        self.assertEqual(profiles.for_percept("voice").max_steps, 6)

    def test_typed_chat_is_unchanged_by_this(self):
        self.assertTrue(set(SPOKEN) <= self.typed, "typed chat had these all along")

    def test_what_voice_lacks_is_only_ever_building_or_browsing(self):
        """The guard against a fourth round: anything typed chat has and
        voice does not must be deliberate, not drift."""
        allowed_absent = set(BUILDING) | {
            "geocode", "list_dir", "propose_mcp_server", "render_page", "search_listings",
            "sec_findings", "sec_posture", "sec_show",
        }
        surprise = sorted((self.typed - self.voice) - allowed_absent)
        self.assertEqual(surprise, [], f"missing from voice with no reason given: {surprise}")


if __name__ == "__main__":
    unittest.main()
