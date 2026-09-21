"""How good is this provider, across everything it has served?

Stage 6 item 1 asks for "per-provider quality per purpose". The data
was already here and only askable one task type at a time: a
strategy is keyed `provider:purpose[:edit_mode]`
(`models.Strategy.key`), so "how good is together at drafting" was a
question the table could answer and had no way to be asked.
"""

import unittest

from simorgh.contracts.envelope import Event
from simorgh.growth.estimate.competence import CompetenceTable

T0 = 1_700_000_000.0


def _outcome(table, task_type, succeeded, strategy, i):
    table.apply(Event(stream="learn:outcomes", type="outcome", ts=T0 + i, trace_id="",
                      causation_id=None,
                      payload={"task_type": task_type, "succeeded": succeeded, "strategy": strategy}))


def _seeded() -> CompetenceTable:
    table = CompetenceTable()
    for i in range(10):
        _outcome(table, "patch", i % 5 != 0, "together:draft", i)
    for i in range(6):
        _outcome(table, "research", True, "together:draft", 100 + i)
    for i in range(8):
        _outcome(table, "patch", i % 2 == 0, "gemini:draft", 200 + i)
    return table


def _mean(table, provider, **kw):
    alpha, beta, _n = table.provider_quality(provider, **kw)
    return alpha / (alpha + beta)


class AcrossTaskTypes(unittest.TestCase):
    def test_a_provider_is_judged_on_everything_it_served(self):
        """Ten patches and six researches are sixteen samples, not two
        separate opinions nobody adds up."""
        _alpha, _beta, samples = _seeded().provider_quality("together")
        self.assertAlmostEqual(samples, 16, places=2)

    def test_the_better_provider_scores_higher(self):
        table = _seeded()
        self.assertGreater(_mean(table, "together"), _mean(table, "gemini"))

    def test_a_purpose_narrows_it(self):
        table = CompetenceTable()
        for i in range(6):
            _outcome(table, "patch", True, "together:draft", i)
        for i in range(6):
            _outcome(table, "patch", False, "together:verify", 100 + i)
        self.assertGreater(_mean(table, "together", purpose="draft"),
                           _mean(table, "together", purpose="verify"))

    def test_a_purpose_does_not_match_a_longer_one_by_prefix(self):
        """`draft` must not swallow `drafting`."""
        table = CompetenceTable()
        for i in range(6):
            _outcome(table, "patch", False, "together:drafting", i)
        _a, _b, samples = table.provider_quality("together", purpose="draft")
        self.assertEqual(samples, 0.0)

    def test_an_edit_mode_still_counts_toward_its_purpose(self):
        """`together:draft:whole_file` is a draft."""
        table = CompetenceTable()
        for i in range(6):
            _outcome(table, "patch", True, "together:draft:whole_file", i)
        _a, _b, samples = table.provider_quality("together", purpose="draft")
        self.assertAlmostEqual(samples, 6, places=2)


class WhenItKnowsNothing(unittest.TestCase):
    def test_a_provider_never_used_is_a_flat_prior(self):
        """Not half the time -- no idea. A provider just configured
        must not read as mediocre."""
        self.assertEqual(CompetenceTable().provider_quality("anthropic"), (1.0, 1.0, 0.0))

    def test_and_is_not_listed(self):
        self.assertEqual(CompetenceTable().providers(), [])


class TheListing(unittest.TestCase):
    def test_worst_first(self):
        """The useful question is which one to stop using."""
        self.assertEqual([name for name, _mean, _n in _seeded().providers()],
                         ["gemini", "together"])

    def test_it_carries_the_sample_count(self):
        rows = {name: samples for name, _mean, samples in _seeded().providers()}
        self.assertAlmostEqual(rows["together"], 16, places=2)


if __name__ == "__main__":
    unittest.main()
