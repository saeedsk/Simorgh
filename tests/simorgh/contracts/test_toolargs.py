"""`contracts/toolargs.py`: how a marker's text becomes tool arguments.

One table, shared by the model's marker path and the CLI's `tool`
command, so the two cannot disagree about what an argument means.
"""

from __future__ import annotations

import unittest

from simorgh.contracts.toolargs import args_from_text

class JsonSurvivesATrailingSentenceTestCase(unittest.TestCase):
    """A model routinely closes with a sentence after its JSON.

    `json.loads` raised on the trailing line, so the whole second part
    of a two-part marker fell through to the raw-text branch and the
    tool got a blob of prose where a field belonged. `home_call` reached
    its tool with a service and no target -- the same silent failure the
    marker-truncation fix ended this morning, arriving by a different
    reply shape (observer, 2026-09-10).
    """

    def test_an_object_followed_by_narration_still_merges(self):
        args = args_from_text("home_call",
                              'light.turn_on\n{"entity_id": "light.kitchen"}\nThat should do it.')
        self.assertEqual(args, {"service": "light.turn_on", "entity_id": "light.kitchen"})

    def test_an_array_followed_by_narration_still_lands_in_its_field(self):
        args = args_from_text("browse_page",
                              'https://x.test\n[{"click": "#go"}]\nthen I will read it')
        self.assertEqual(args["actions"], [{"click": "#go"}])

    def test_clean_json_is_unchanged(self):
        self.assertEqual(args_from_text("home_call", 'light.turn_on\n{"entity_id": "k"}'),
                         {"service": "light.turn_on", "entity_id": "k"})

    def test_plain_text_second_parts_are_unchanged(self):
        self.assertEqual(args_from_text("remind", "tomorrow 8am\ncall the dentist"),
                         {"when": "tomorrow 8am", "text": "call the dentist"})

    def test_something_that_only_looks_like_json_is_still_text(self):
        args = args_from_text("remind", "tomorrow\n{not json at all")
        self.assertEqual(args["text"], "{not json at all")


class CastMarkersTestCase(unittest.TestCase):
    def test_every_cast_tool_has_a_marker_shape(self):
        from simorgh.contracts.toolargs import MARKER_ARG_KEY, MARKER_NO_ARGS, args_from_text
        for tool in ("cast_play", "cast_show", "cast_stop", "cast_volume", "cast_use", "cast_setup"):
            self.assertIn(tool, MARKER_ARG_KEY, tool)
        self.assertIn("cast_devices", MARKER_NO_ARGS)
        self.assertEqual(args_from_text("cast_play", "https://www.youtube.com/watch?v=abc123 full"),
                         {"url": "https://www.youtube.com/watch?v=abc123 full"})
        self.assertEqual(args_from_text("cast_devices", ""), {})
