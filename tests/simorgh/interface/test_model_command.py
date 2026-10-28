"""`/model` (2026-10-27): a command, not a chat turn."""

import unittest

from simorgh.interface import render
from simorgh.interface.parser import parse

LISTED = {"selected": "together", "order": ["together", "claude_code_cli", "floor"], "changed": False,
          "providers": [{"name": "together", "model": "zai-org/GLM-5.3-Flash", "available": True},
                        {"name": "claude_code_cli", "model": "opus", "available": True}]}


class ModelCommand(unittest.TestCase):
    def test_it_parses_as_a_command_and_a_sentence_does_not(self):
        self.assertEqual(parse("/model").name, "model")
        self.assertEqual((parse("/model opus").name, parse("/model opus").args), ("model", "opus"))
        self.assertEqual(parse("model together_strong").name, "model")
        self.assertIsNone(parse("model the kitchen in 3D for me").name)

    def test_the_list_marks_the_one_answering(self):
        text = render.model_choice(LISTED)
        self.assertIn("● together", text)
        self.assertIn("claude_code_cli", text)
        self.assertIn("opus", text)

    def test_a_switch_and_a_refusal_say_so(self):
        switched = render.model_choice({**LISTED, "selected": "claude_code_cli", "changed": True,
                                        "persisted": "/x/simorgh.toml"})
        self.assertIn("thinking with claude_code_cli now (saved to /x/simorgh.toml)", switched)
        self.assertIn("not switched: no provider", render.model_choice({**LISTED, "refused": "no provider called 'x'"}))

    def test_effort_parses_and_shows_the_answering_providers_level(self):
        self.assertEqual((parse("/effort max").name, parse("/effort max").args), ("effort", "max"))
        self.assertEqual(parse("effort high claude_code_cli").name, "effort")
        self.assertIsNone(parse("effort is what counts").name)
        shown = render.effort_choice({**LISTED, "selected": "claude_code_cli",
                                      "providers": [{"name": "claude_code_cli", "model": "opus", "effort": "high"}]})
        self.assertIn("claude_code_cli thinks at high effort", shown)
        self.assertIn("effort high", shown)
        self.assertIn("effort not changed: together has no effort setting",
                      render.effort_choice({**LISTED, "refused": "together has no effort setting"}))


if __name__ == "__main__":
    unittest.main()
