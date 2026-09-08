"""GAIA's quasi-exact match and BFCL's call match.

The scorer is the part of a benchmark that must not drift. A scorer
looser than the published one produces a number nobody can compare to
anybody else's, which is the whole reason to run a standard benchmark.
"""

from __future__ import annotations

import unittest

from simorgh.benchmark.scoring import (
    ANSWER_FORMAT, final_answer, matches, normalise, parse_calls, score, score_calls, score_case,
)


class FinalAnswerTestCase(unittest.TestCase):
    def test_it_reads_the_labelled_line(self):
        self.assertEqual(final_answer("Thinking...\nFINAL ANSWER: 42"), "42")

    def test_the_last_such_line_wins(self):
        text = "The format is FINAL ANSWER: <answer>\nSo:\nFINAL ANSWER: Paris"
        self.assertEqual(final_answer(text), "Paris")

    def test_markdown_emphasis_is_stripped(self):
        self.assertEqual(final_answer("**FINAL ANSWER: 7**"), "7")

    def test_a_plain_last_line_is_used_when_the_label_is_missing(self):
        self.assertEqual(final_answer("I looked it up.\nParis"), "Paris")

    def test_empty_text_is_empty(self):
        self.assertEqual(final_answer(""), "")
        self.assertEqual(final_answer("   \n  "), "")

    def test_the_prompt_asks_for_the_shape_the_scorer_wants(self):
        self.assertIn("FINAL ANSWER:", ANSWER_FORMAT)
        self.assertIn("comma separated list", ANSWER_FORMAT)


class QuasiExactMatchTestCase(unittest.TestCase):
    def test_numbers_ignore_formatting(self):
        for given in ("1234", "1,234", "$1234", "1234.0", " 1234 "):
            self.assertTrue(matches(given, "1234"), given)

    def test_a_different_number_is_wrong(self):
        self.assertFalse(matches("1235", "1234"))

    def test_strings_ignore_case_articles_and_punctuation(self):
        self.assertTrue(matches("The Louvre.", "louvre"))
        self.assertTrue(matches("New York", "new york"))

    def test_a_different_string_is_wrong(self):
        self.assertFalse(matches("Berlin", "Paris"))

    def test_lists_match_element_wise_in_order(self):
        self.assertTrue(matches("a, b, c", "a,b,c"))
        self.assertTrue(matches("1, 2, 3", "1,2,3"))
        self.assertFalse(matches("c, b, a", "a,b,c"))
        self.assertFalse(matches("a, b", "a,b,c"))

    def test_an_empty_expectation_never_matches(self):
        self.assertFalse(matches("anything", ""))

    def test_normalise_rounds_floats_without_collapsing_them(self):
        self.assertEqual(normalise("3.0"), "3")
        self.assertNotEqual(normalise("3.14159"), normalise("3.1416"))

    def test_score_returns_the_extracted_answer(self):
        correct, answer = score("blah\nFINAL ANSWER: 42", "42")
        self.assertTrue(correct)
        self.assertEqual(answer, "42")


class FunctionCallScoringTestCase(unittest.TestCase):
    EXPECTED = '[{"find_restaurants": {"location": ["San Francisco", "SF"], "cuisine": ["Italian"]}}]'

    def test_a_matching_call_scores(self):
        reply = '[{"name": "find_restaurants", "arguments": {"location": "SF", "cuisine": "Italian"}}]'
        correct, _ = score_calls(reply, self.EXPECTED)
        self.assertTrue(correct)

    def test_a_wrong_function_does_not(self):
        reply = '[{"name": "find_hotels", "arguments": {"location": "SF", "cuisine": "Italian"}}]'
        self.assertFalse(score_calls(reply, self.EXPECTED)[0])

    def test_a_wrong_argument_does_not(self):
        reply = '[{"name": "find_restaurants", "arguments": {"location": "Berlin", "cuisine": "Italian"}}]'
        self.assertFalse(score_calls(reply, self.EXPECTED)[0])

    def test_an_extra_argument_does_not(self):
        reply = '[{"name": "find_restaurants", "arguments": {"location": "SF", "cuisine": "Italian", "vegan": true}}]'
        self.assertFalse(score_calls(reply, self.EXPECTED)[0])

    def test_parallel_calls_match_in_any_order(self):
        expected = '[{"f": {"x": ["1"]}}, {"g": {"y": ["2"]}}]'
        reply = '[{"name": "g", "arguments": {"y": "2"}}, {"name": "f", "arguments": {"x": "1"}}]'
        self.assertTrue(score_calls(reply, expected)[0])

    def test_a_missing_call_does_not(self):
        expected = '[{"f": {"x": ["1"]}}, {"g": {"y": ["2"]}}]'
        self.assertFalse(score_calls('[{"name": "f", "arguments": {"x": "1"}}]', expected)[0])

    def test_an_omittable_argument_may_be_left_out(self):
        expected = '[{"f": {"x": ["1"], "note": ["", "anything"]}}]'
        self.assertTrue(score_calls('[{"name": "f", "arguments": {"x": "1"}}]', expected)[0])

    def test_calls_are_read_out_of_a_fenced_block(self):
        reply = 'Here you go:\n```json\n[{"name": "f", "arguments": {"x": "1"}}]\n```\nDone.'
        self.assertEqual(parse_calls(reply), [("f", {"x": "1"})])

    def test_prose_with_no_json_yields_nothing(self):
        self.assertEqual(parse_calls("I would call find_restaurants."), [])
        self.assertFalse(score_calls("I would call find_restaurants.", self.EXPECTED)[0])

    def test_the_mode_chooses_the_scorer(self):
        self.assertTrue(score_case("FINAL ANSWER: 42", "42", mode="gaia")[0])
        self.assertTrue(score_case('[{"name": "f", "arguments": {}}]', '[{"f": {}}]', mode="bfcl")[0])
        self.assertFalse(score_case("FINAL ANSWER: 42", '[{"f": {}}]', mode="bfcl")[0])


if __name__ == "__main__":
    unittest.main()
