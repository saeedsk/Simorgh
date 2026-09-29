"""An answer taken from the benchmark itself is not the system's.

Bench wave 2026-09-29, GAIA 72e110e7: web_search "GAIA BASE DDC 633 ...
answer", then "the GAIA ground truth was confirmed as Nigeria across
independent mirrors (AgentRx, aidan.blog)". The prompt now forbids it and
an answer that admits it is scored wrong with the reason."""

from __future__ import annotations

import unittest

from simorgh.benchmark.api import Case
from simorgh.benchmark.runner import Runner, looked_up


class AnAnswerLookedUpIsNotScored(unittest.TestCase):
    def test_the_live_case_is_caught(self):
        answer = ("my own recorded outcome for this exact task says the GAIA ground truth was confirmed as "
                  "Nigeria across independent mirrors. FINAL ANSWER: Nigeria")
        self.assertIn("gaia", looked_up(answer, "gaia-l1"))

    def test_a_question_about_the_gaia_spacecraft_is_not(self):
        self.assertEqual(looked_up("Gaia DR3 gives a parallax of 2.1 mas. FINAL ANSWER: 476", "gaia"), "")
        self.assertEqual(looked_up("The Gaia hypothesis, per Lovelock. FINAL ANSWER: Lovelock", "gaia-l1"), "")

    def test_an_answer_key_by_any_name_is_caught(self):
        self.assertTrue(looked_up("The published answer key says 7. FINAL ANSWER: 7", "bfcl-parallel"))

    def test_an_ordinary_answer_is_left_alone(self):
        self.assertEqual(looked_up("FINAL ANSWER: 3", "gaia"), "")

    def test_the_prompt_forbids_it(self):
        from unittest import mock
        prompt = Runner(mock.MagicMock()).prompt(Case(id="c", question="q?", answer="a", mode="gaia", suite="gaia"))
        self.assertIn("Do not look up this benchmark", prompt)


if __name__ == "__main__":
    unittest.main()
