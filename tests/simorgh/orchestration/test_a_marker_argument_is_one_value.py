"""A single-valued marker argument loses the prose after it (GAIA,
2026-09-19: a URL with the model's next sentence in it failed three times)."""

import unittest

from simorgh.orchestration.tools import to_action_payload


def _args(tool, raw):
    return to_action_payload(action_id="a", task_id="t", call={"tool": tool, "args": {"argument": raw}},
                             rationale="r")["args"]


class AMarkerArgumentIsOneValue(unittest.TestCase):
    def test_a_url_is_its_first_token(self):
        self.assertEqual(_args("web_fetch", "https://en.wikipedia.org/wiki/Moon\nThere is no tool result yet"),
                         {"url": "https://en.wikipedia.org/wiki/Moon"})
        self.assertEqual(_args("web_fetch", "  https://a.example/x  trailing words"), {"url": "https://a.example/x"})

    def test_a_path_is_its_first_line_and_may_hold_spaces(self):
        self.assertEqual(_args("read_file", "workspace/My Notes/a.md\nthen summarise it"),
                         {"path": "workspace/My Notes/a.md"})

    def test_other_arguments_are_untouched(self):
        self.assertEqual(_args("web_search", "moon perigee\nminimum")["query"], "moon perigee\nminimum")
