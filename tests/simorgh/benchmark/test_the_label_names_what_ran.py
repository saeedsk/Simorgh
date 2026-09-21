"""A score belongs to the model that produced it.

The creator's GAIA run, 2026-09-20. The card said:

    gaia-l1 . zai-org/GLM-5.3-Flash
    overall  20.0%  1/5

and the log, during the same run, said:

    thinking moved from together_strong to floor
    thinking moved from floor to together
    thinking moved from together to gemini
    thinking moved from gemini to together_strong

An unknown share of that 20% was Gemini and the offline floor. A pass
rate under the wrong model's name is worse than no pass rate, because
a number gets compared against other models' numbers and a missing one
does not.

Cognition had always named the provider in its reply and nothing
carried it further, so the runner could not check its own headline.
`task.step` carries it now.
"""

import unittest

from simorgh.benchmark.api import RunRecord


class WhatActuallyServed(unittest.TestCase):
    def test_the_creators_run_would_have_said_so(self):
        record = RunRecord(model="zai-org/GLM-5.3-Flash",
                           providers=["floor", "gemini", "together", "together_strong"])
        self.assertEqual(record.served_by_others,
                         ["floor", "gemini", "together", "together_strong"])

    def test_a_clean_run_says_nothing(self):
        """Silence is the good case, so it has to be reachable."""
        record = RunRecord(model="together/glm-4.6", providers=["together"])
        self.assertEqual(record.served_by_others, [])

    def test_a_provider_naming_the_model_is_the_same_thing(self):
        """`together` served `together/glm-4.6`. The label is a model
        id and the provider is a gateway; neither is a substring
        accident worth warning about."""
        self.assertEqual(RunRecord(model="together/glm-4.6", providers=["together"]).served_by_others, [])
        self.assertEqual(RunRecord(model="gemini-2.5-pro", providers=["gemini"]).served_by_others, [])

    def test_the_floor_is_always_worth_naming(self):
        """The offline floor answers without a model at all. It is the
        one that most needs saying and the easiest to miss."""
        record = RunRecord(model="together/glm-4.6", providers=["together", "floor"])
        self.assertEqual(record.served_by_others, ["floor"])

    def test_nothing_recorded_is_not_a_warning(self):
        """An old run, or one whose steps carried no provider. Absence
        of evidence is not a failover."""
        self.assertEqual(RunRecord(model="m", providers=[]).served_by_others, [])

    def test_it_survives_the_summary_round_trip(self):
        """History is rebuilt from a summary payload, and a warning
        that vanishes on reload is a warning nobody sees twice."""
        record = RunRecord(model="zai-org/GLM-5.3-Flash", providers=["floor", "gemini"])
        back = RunRecord.from_payload(record.to_payload())
        self.assertEqual(back.providers, ["floor", "gemini"])
        self.assertEqual(back.served_by_others, ["floor", "gemini"])


class TheCardSaysIt(unittest.TestCase):
    def test_the_warning_is_printed_and_names_the_others(self):
        from simorgh.interface import benchmarkchart

        record = RunRecord(model="zai-org/GLM-5.3-Flash", providers=["floor", "gemini"])
        text = benchmarkchart.summary(record.to_payload(), enabled=False)
        self.assertIn("gemini", text)
        self.assertIn("floor", text)
        self.assertIn("not only", text)


if __name__ == "__main__":
    unittest.main()
