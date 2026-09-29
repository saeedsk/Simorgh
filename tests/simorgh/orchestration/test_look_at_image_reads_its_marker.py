"""`LOOK_AT_IMAGE: ...` reaches the tool as `{paths, question}`.

Bench wave 2026-09-29: with no marker mapping every call arrived as
`{"argument": ...}` and failed the tool's schema. These are the five
shapes the model actually wrote, in the order it tried them."""

from __future__ import annotations

import unittest

from simorgh.orchestration.tools import to_action_payload

PNG = "workspace/benchmark/9318445f/9318445f.png"


def _args(argument: str) -> dict:
    return to_action_payload(action_id="a", task_id="t", rationale="r",
                             call={"tool": "look_at_image", "args": {"argument": argument}})["args"]


class LookAtImageReadsItsMarker(unittest.TestCase):
    def test_every_shape_the_model_tried(self):
        cases = {
            f"{PNG} — List every fraction in the image": ([PNG], "List every fraction in the image"),
            f"paths={PNG} question=List every fraction using a / slash": ([PNG], "List every fraction using a / slash"),
            f"paths: {PNG}": ([PNG], ""),
            PNG: ([PNG], ""),
            f'{{"paths": ["{PNG}"], "question": "Read the fractions."}}': ([PNG], "Read the fractions."),
        }
        for argument, (paths, question) in cases.items():
            with self.subTest(argument=argument):
                self.assertEqual(_args(argument), {"paths": paths, "question": question})

    def test_several_paths_keep_their_order(self):
        got = _args("workspace/scratch/col.png workspace/scratch/samps.png -- read the three fractions")
        self.assertEqual(got["paths"], ["workspace/scratch/col.png", "workspace/scratch/samps.png"])
        self.assertEqual(got["question"], "read the three fractions")

    def test_it_is_read_only(self):
        payload = to_action_payload(action_id="a", task_id="t", rationale="r",
                                    call={"tool": "look_at_image", "args": {"argument": PNG}})
        self.assertEqual(payload["reversibility"], "read_only")


if __name__ == "__main__":
    unittest.main()


class AJsonObjectIsTheArguments(unittest.TestCase):
    """`people` has several fields and no marker mapping: until 2026-09-29
    its JSON went through as {"argument": "<json>"} and failed the schema."""

    def _args(self, tool, argument):
        return to_action_payload(action_id="a", task_id="t", rationale="r",
                                 call={"tool": tool, "args": {"argument": argument}})["args"]

    def test_people_from_a_json_object(self):
        self.assertEqual(self._args("people", '{"action": "set_role", "name": "Ira", "role": "child"}'),
                         {"action": "set_role", "name": "Ira", "role": "child"})

    def test_a_fenced_object_too(self):
        fenced = '```json\n{"action": "grant", "name": "Soodeh", "permission": "interest_shares"}\n```'
        self.assertEqual(self._args("people", fenced)["permission"], "interest_shares")

    def test_prose_is_left_for_the_tool_to_refuse(self):
        self.assertEqual(self._args("people", "set_role Ira child"), {"argument": "set_role Ira child"})
