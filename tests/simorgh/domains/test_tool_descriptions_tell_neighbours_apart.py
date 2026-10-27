"""The descriptions the model sees say what separates near-neighbour tools.

Stage 17 selection stress, 2026-10-27 (docs/findings/2026-10-27-guardrails-
sidecars-and-tokens.md section 1). A native-dialect session is shown each
tool's own `description`; these are the facts that tell `cam_snapshot`
from `look_at_image`, `media_play` from `room_play`, and `media_control`'s
pause from its stop and its off. They pin facts, not wording.
"""

from __future__ import annotations

import unittest

from simorgh.domains.home.cameras import CamSnapshotTool
from simorgh.domains.media.roomplay import RoomPlayTool
from simorgh.domains.media.tools import MediaControlTool, MediaPlayTool


class CamSnapshot(unittest.TestCase):
    def test_takes_a_new_picture_from_a_live_camera(self):
        text = CamSnapshotTool.description.lower()
        self.assertTrue(text.startswith("takes a new still from a live camera"), text)

    def test_sends_a_saved_picture_to_look_at_image(self):
        text = CamSnapshotTool.description.lower()
        self.assertIn("already exists", text)
        self.assertIn("look_at_image", text)


class MediaControl(unittest.TestCase):
    def test_says_whose_players_and_what_each_op_does(self):
        text = MediaControlTool.description.lower()
        self.assertIn("home assistant media player", text)
        self.assertIn("pause (holds the place", text)
        self.assertIn("stop (ends playback)", text)
        self.assertIn("off or on (switches the player", text)
        self.assertIn("room_play", text)

    def test_every_op_it_describes_is_one_it_accepts(self):
        ops = set(MediaControlTool.args_schema["properties"]["op"]["enum"])
        for op in ("pause", "resume", "next", "previous", "stop", "off", "on", "mute", "volume"):
            self.assertIn(op, ops)
        # "skip" read like an op and is not one: a call with op=skip is
        # refused as unknown.
        self.assertNotIn("skip", MediaControlTool.description.lower())


class MediaPlay(unittest.TestCase):
    def test_finds_no_station_and_cannot_reach_a_satellite(self):
        text = MediaPlayTool.description.lower()
        self.assertNotIn("a radio stream", text)
        self.assertIn("home assistant media player", text)
        self.assertIn("cannot find a radio station by genre", text)
        self.assertIn("room_play", text)


class RoomPlay(unittest.TestCase):
    def test_finds_the_station_and_is_out_of_media_plays_reach(self):
        text = RoomPlayTool.description.lower()
        self.assertIn("finds the radio station itself", text)
        self.assertIn("media_play cannot reach it", text)


if __name__ == "__main__":
    unittest.main()
