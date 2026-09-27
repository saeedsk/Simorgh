"""Stage 13: a spoken turn through a room satellite tells the model where
the person is. The creator, 2026-09-27: "when I say 'play music' on the
board, I expect the music played on the same board that heard the
prompt" -- and the model, told nothing, answered "say 'Sim, play music'"."""

import unittest

from simorgh.orchestration import profiles, scaffolds

_NOTE = "being spoken to through the room satellite"


class ASatelliteTurnIsPlaced(unittest.TestCase):
    def test_a_satellite_turn_says_which_room_and_that_music_plays_there(self):
        out = scaffolds.render(profiles.for_percept("voice"), channel="voice", device="sim-room-1", offered=())
        self.assertIn(_NOTE, out)
        self.assertIn("'sim-room-1'", out)
        self.assertIn("room_play with no room", out)

    def test_the_laptop_and_typed_turns_are_unchanged(self):
        for kw in ({"channel": "voice", "device": "laptop"}, {"channel": "voice", "device": ""},
                   {"channel": "cli", "device": "sim-room-1"}):
            out = scaffolds.render(profiles.for_percept(kw["channel"]), offered=(), **kw)
            self.assertNotIn(_NOTE, out, kw)


if __name__ == "__main__":
    unittest.main()
