"""Marker text reaches the field the tool needs (live 2026-10-27).

`REMEMBER: When Saeed asks ...` reached `remember` as `{"argument": ...}`
and was refused four times in one turn (`fact` is required); `SPAWN:
<what to do>` reached Guardian without its `brief`."""

import unittest

from simorgh.contracts import toolargs
from simorgh.orchestration.tools import forget_registered, note_schema, to_action_payload


def _args(tool, raw):
    return to_action_payload(action_id="a", task_id="t", call={"tool": tool, "args": {"argument": raw}},
                             rationale="r")["args"]


class MarkerTextReachesItsField(unittest.TestCase):
    def tearDown(self):
        forget_registered()

    def test_remember_takes_the_whole_sentence(self):
        said = "When Saeed asks for a Claude Code agent, start it with authorised=true"
        self.assertEqual(_args("remember", said), {"fact": said})

    def test_remember_still_reads_key_values_and_json(self):
        self.assertEqual(_args("remember", "fact=the gate code is 4411")["fact"], "the gate code is 4411")
        self.assertEqual(_args("remember", '{"fact": "x"}'), {"fact": "x"})

    def test_plain_text_fills_the_one_required_field(self):
        note_schema("spawn", {"type": "object", "required": ["brief"],
                              "properties": {"brief": {"type": "string"}, "member": {"type": "string"}}})
        self.assertEqual(_args("spawn", "find AWS stock products"), {"brief": "find AWS stock products"})

    def test_two_required_fields_are_not_guessed(self):
        note_schema("pair", {"type": "object", "required": ["a", "b"]})
        self.assertEqual(_args("pair", "words"), {"argument": "words"})

    def test_the_contract_table_agrees(self):
        self.assertEqual(toolargs.args_from_text("remember", "Iris likes owls"), {"fact": "Iris likes owls"})


if __name__ == "__main__":
    unittest.main()
