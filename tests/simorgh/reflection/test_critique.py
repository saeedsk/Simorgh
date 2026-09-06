import unittest

from simorgh.reflection.critique import Critique, floor_critique, parse_critique


class TestFloorCritique(unittest.TestCase):
    def test_floor_uses_mechanical_summary_and_flags_floor(self):
        c = floor_critique("task t1 completed via patch")
        self.assertEqual(c.what_changed, "task t1 completed via patch")
        self.assertIsNone(c.confidence)
        self.assertEqual(c.open_questions, [])
        self.assertIsNone(c.lesson)
        self.assertTrue(c.floor)


class TestParseCritique(unittest.TestCase):
    def test_empty_text_returns_floor(self):
        c = parse_critique("", mechanical_summary="fallback")
        self.assertTrue(c.floor)
        self.assertEqual(c.what_changed, "fallback")

    def test_whitespace_only_returns_floor(self):
        c = parse_critique("   \n  ", mechanical_summary="fallback")
        self.assertTrue(c.floor)

    def test_no_json_object_returns_floor(self):
        c = parse_critique("I think it went fine, no structure here.", mechanical_summary="fallback")
        self.assertTrue(c.floor)

    def test_malformed_json_returns_floor(self):
        c = parse_critique('{"what_changed": "fixed bug", "confidence": }', mechanical_summary="fallback")
        self.assertTrue(c.floor)

    def test_json_array_not_object_returns_floor(self):
        c = parse_critique('["a", "b"]', mechanical_summary="fallback")
        self.assertTrue(c.floor)

    def test_well_formed_json_is_parsed(self):
        text = '{"what_changed": "patched retrieval", "confidence": 0.7, "open_questions": ["did it cover edge case X?"], "lesson": "check index bounds"}'
        c = parse_critique(text, mechanical_summary="fallback")
        self.assertFalse(c.floor)
        self.assertEqual(c.what_changed, "patched retrieval")
        self.assertAlmostEqual(c.confidence, 0.7)
        self.assertEqual(c.open_questions, ["did it cover edge case X?"])
        self.assertEqual(c.lesson, "check index bounds")

    def test_json_embedded_in_narration_is_extracted(self):
        text = 'Sure, here is my critique:\n{"what_changed": "renamed field", "confidence": 0.5, "open_questions": [], "lesson": null}\nHope that helps.'
        c = parse_critique(text, mechanical_summary="fallback")
        self.assertFalse(c.floor)
        self.assertEqual(c.what_changed, "renamed field")
        self.assertIsNone(c.lesson)

    def test_missing_what_changed_falls_back_to_mechanical_summary(self):
        c = parse_critique('{"confidence": 0.3}', mechanical_summary="fallback summary")
        self.assertFalse(c.floor)
        self.assertEqual(c.what_changed, "fallback summary")

    def test_confidence_out_of_range_is_clamped(self):
        c = parse_critique('{"confidence": 1.5}', mechanical_summary="x")
        self.assertAlmostEqual(c.confidence, 1.0)
        c2 = parse_critique('{"confidence": -0.5}', mechanical_summary="x")
        self.assertAlmostEqual(c2.confidence, 0.0)

    def test_non_numeric_confidence_becomes_none(self):
        c = parse_critique('{"confidence": "high"}', mechanical_summary="x")
        self.assertIsNone(c.confidence)

    def test_open_questions_as_single_string_is_coerced_to_list(self):
        c = parse_critique('{"open_questions": "is this right?"}', mechanical_summary="x")
        self.assertEqual(c.open_questions, ["is this right?"])

    def test_open_questions_empty_string_is_coerced_to_empty_list(self):
        c = parse_critique('{"open_questions": ""}', mechanical_summary="x")
        self.assertEqual(c.open_questions, [])

    def test_open_questions_non_list_non_string_becomes_empty_list(self):
        c = parse_critique('{"open_questions": 42}', mechanical_summary="x")
        self.assertEqual(c.open_questions, [])

    def test_open_questions_items_coerced_to_str(self):
        c = parse_critique('{"open_questions": [1, 2]}', mechanical_summary="x")
        self.assertEqual(c.open_questions, ["1", "2"])

    def test_non_string_lesson_becomes_none(self):
        c = parse_critique('{"lesson": 7}', mechanical_summary="x")
        self.assertIsNone(c.lesson)


if __name__ == "__main__":
    unittest.main()
