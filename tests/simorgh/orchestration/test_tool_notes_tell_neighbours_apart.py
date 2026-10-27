"""Each scaffold tool line with a near neighbour says what separates it.

Stage 17 selection stress, 2026-10-27 (docs/findings/2026-10-27-guardrails-
sidecars-and-tokens.md section 1): Sim's full scaffold lost to the bare
preset on near-neighbour choices. Asked to look at a picture already saved
under workspace/cameras/, the model took a new `cam_snapshot` -- whose line
began "a still from a camera, saved under workspace/cameras/" while
`look_at_image`'s never said it reads a file that exists. Jazz radio for a
room satellite went to `media_play` ("a URL or a stream on a player"), and
nothing said `media_control` has `off`, or that pause keeps the place.

These pin the distinguishing FACTS, not the wording, so a later rewrite
can say them its own way but cannot drop them.
"""

from __future__ import annotations

import unittest

from simorgh.orchestration import scaffolds
from simorgh.orchestration.tools import marker_hint


def note(name: str) -> str:
    return scaffolds._TOOL_NOTES[name].lower()  # noqa: SLF001


class CameraAgainstAFile(unittest.TestCase):
    def test_cam_snapshot_takes_a_new_picture_and_is_not_for_a_saved_one(self):
        line = note("cam_snapshot")
        self.assertIn("new", line)
        self.assertIn("live camera", line)
        self.assertIn("already exists", line)
        self.assertIn("look_at_image", line)

    def test_look_at_image_reads_a_file_already_on_disk_and_takes_no_picture(self):
        line = note("look_at_image")
        self.assertIn("already on disk", line)
        self.assertIn("by path", line)
        self.assertIn("no new picture", line)

    def test_camera_describe_is_a_live_camera_not_a_saved_picture(self):
        line = note("camera_describe")
        self.assertIn("live camera", line)
        self.assertIn("not for a saved picture", line)


class PlayersAgainstTheRoom(unittest.TestCase):
    def test_media_control_names_its_players_and_says_pause_stop_and_off_apart(self):
        line = note("media_control")
        self.assertIn("home assistant", line)
        self.assertIn("tv", line)
        self.assertIn("pause (keeps the place)", line)
        self.assertIn("stop (ends playback)", line)
        self.assertIn("off or on", line)
        self.assertNotIn("skip", line)  # not an op media_control accepts

    def test_media_play_finds_nothing_and_cannot_reach_a_satellite(self):
        line = note("media_play")
        self.assertIn("home assistant", line)
        self.assertIn("no station by genre", line)
        self.assertIn("room satellite is not one of its players", line)

    def test_room_play_finds_the_station_itself(self):
        line = note("room_play")
        self.assertIn("satellite", line)
        self.assertIn("finds the station itself", line)


class MarkerHints(unittest.TestCase):
    """The marker dialect's argument hints say the same, so a session in
    either dialect reads one story."""

    def test_media_play_hint_sends_a_genre_or_a_satellite_to_room_play(self):
        hint = marker_hint("media_play") or ""
        self.assertNotIn("a radio stream", hint)
        self.assertIn("ROOM_PLAY", hint)

    def test_media_control_hint_tells_pause_stop_and_off_apart(self):
        hint = marker_hint("media_control") or ""
        self.assertIn("pause keeps the place", hint)
        self.assertIn("stop ends playback", hint)
        self.assertIn("off switches the player itself off", hint)


class BothPresetsReadTheLines(unittest.TestCase):
    def test_the_bare_preset_renders_the_same_tool_lines(self):
        """The fix is in the tool lines, not the workflow body: the bare
        preset renders the same lines, so both presets read the same facts
        and a paid comparison measures the body alone."""
        from simorgh.orchestration import profiles

        chat = profiles.AGENTS["chat"]
        bare = scaffolds.render(chat, channel="cli", workflow=False)
        self.assertIn(scaffolds._TOOL_NOTES["look_at_image"], bare)  # noqa: SLF001
        self.assertIn(scaffolds._TOOL_NOTES["cam_snapshot"], bare)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
