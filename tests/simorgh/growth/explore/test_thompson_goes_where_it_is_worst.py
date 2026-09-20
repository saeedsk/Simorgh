"""Stage 8 item 7: exploring by how little Sim knows.

A score says what is interesting; it says nothing about how sure Sim is
of it, so an area tried twice and an area tried two hundred times score
the same and get treated the same. Thompson sampling asks the other
question: one draw from each target's posterior, lowest draw wins. Sim
goes where it is worst, and a target with few samples draws low often
enough to get looked at without ever being forced.

The acceptance case is the seeded ordering at the bottom.
"""

import random
import unittest

from simorgh.growth.estimate.competence import CompetenceTable
from simorgh.growth.explore.thompson import (
    PRIOR, Unknown, from_posterior, order, pick, unknowns_from,
)
from simorgh.ledger.api import Event


def _rng() -> random.Random:
    return random.Random(20260920)


class TheDraw(unittest.TestCase):
    def test_a_target_with_no_evidence_has_no_opinion(self):
        self.assertEqual((Unknown("x").alpha, Unknown("x").beta), PRIOR)

    def test_something_sim_is_bad_at_draws_low(self):
        bad = Unknown("bad", alpha=1.0, beta=40.0)
        good = Unknown("good", alpha=40.0, beta=1.0)
        rng = _rng()
        lows = sum(1 for _ in range(200) if bad.draw(rng) < good.draw(rng))
        self.assertGreater(lows, 190)

    def test_a_wide_posterior_still_gets_looked_at(self):
        """Two samples and two hundred can have the same mean; only one
        of them is worth going back to."""
        sure = Unknown("sure", alpha=100.0, beta=100.0, samples=200)
        unsure = Unknown("unsure", alpha=1.0, beta=1.0, samples=0)
        rng = _rng()
        wins = sum(1 for _ in range(300) if unsure.draw(rng) < sure.draw(rng))
        self.assertGreater(wins, 60, "the uncertain one comes up often")
        self.assertLess(wins, 240, "but it does not monopolise")

    def test_boredom_widens_rather_than_narrows(self):
        settled = Unknown("settled", alpha=60.0, beta=2.0)
        rng = random.Random(7)
        cold = [settled.draw(rng, temperature=1.0) for _ in range(200)]
        rng = random.Random(7)
        hot = [settled.draw(rng, temperature=8.0) for _ in range(200)]
        self.assertLess(min(cold), 1.0)
        self.assertLess(min(hot), min(cold), "a bored Sim will look somewhere it thinks it knows")

    def test_no_amount_of_boredom_is_evidence(self):
        """Temperature may widen a posterior back towards the prior. It
        may never make one narrower than the evidence supports."""
        target = Unknown("x", alpha=30.0, beta=3.0)
        rng = random.Random(3)
        wide = [target.draw(rng, temperature=100.0) for _ in range(50)]
        self.assertTrue(all(0.0 <= v <= 1.0 for v in wide))


class TheTargetSpace(unittest.TestCase):
    """Repo areas were the whole list. A question nobody can answer and
    a device nothing has probed are unknowns too."""

    def test_everything_unmeasured_shares_the_flat_prior(self):
        found = unknowns_from(questions=["why does the hall light flicker"],
                              stale_facts=["the wifi password"],
                              unprobed_devices=["camera.pool"],
                              unexercised_skills=["word_count"])
        self.assertEqual({u.kind for u in found}, {"question", "fact", "device", "skill"})
        self.assertTrue(all((u.alpha, u.beta) == PRIOR for u in found))

    def test_blank_names_are_not_targets(self):
        self.assertEqual(unknowns_from(questions=["", "   "]), [])

    def test_a_task_type_brings_its_real_posterior(self):
        table = CompetenceTable()
        for seq in range(1, 6):
            table.apply(Event(seq=seq, stream="learn:outcomes", type="outcome", ts=float(seq),
                              trace_id="t", causation_id=None,
                              payload={"task_type": "patch", "succeeded": False, "weight": 1.0,
                                       "cost_usd": 0.0, "duration_s": 1.0}))
        found = unknowns_from(competence=table, task_types=["patch"])
        self.assertEqual(found[0].samples, 5)
        self.assertLess(found[0].mean, 0.5, "five failures is not a flat prior")


class TheOrdering(unittest.TestCase):
    """The acceptance case: a seeded posterior set produces the
    expected exploration order."""

    def setUp(self):
        self.unknowns = [
            Unknown("hopeless", alpha=1.0, beta=80.0, samples=81),     # tried, always fails
            Unknown("shaky", alpha=4.0, beta=8.0, samples=12),         # middling
            Unknown("solid", alpha=90.0, beta=2.0, samples=92),        # known good
            Unknown("untouched"),                                       # no evidence at all
        ]

    def test_the_worst_understood_comes_first_and_the_solid_one_last(self):
        names = [u.name for u in order(self.unknowns, rng=_rng())]
        self.assertEqual(names[0], "hopeless")
        self.assertEqual(names[-1], "solid")

    def test_the_order_is_stable_for_a_seed(self):
        self.assertEqual([u.name for u in order(self.unknowns, rng=_rng())],
                         [u.name for u in order(self.unknowns, rng=_rng())])

    def test_pick_is_the_head_of_the_order(self):
        self.assertEqual(pick(self.unknowns, rng=_rng()).name,
                         order(self.unknowns, rng=_rng())[0].name)

    def test_nothing_to_explore_is_not_an_error(self):
        self.assertIsNone(pick([], rng=_rng()))

    def test_one_hopeless_target_would_take_every_round_without_diversity(self):
        """The reason `recent` is not a detail. A target measured 80
        times that always fails draws tightly around 0.01 and beats a
        flat prior 99 times in 100, so lowest-draw-wins on its own
        finds the worst thing rather than exploring."""
        rng = _rng()
        picks = [pick(self.unknowns, rng=rng).name for _ in range(400)]
        self.assertGreater(picks.count("hopeless"), 350)
        self.assertEqual(picks.count("shaky"), 0)

    def test_with_the_samplers_diversity_the_uncertain_targets_share_the_turns(self):
        rng = _rng()
        recent: list[str] = []
        picks = []
        for _ in range(400):
            got = pick(self.unknowns, rng=rng, recent=recent[-2:])
            picks.append(got.name)
            recent.append(got.name)
        for name in ("hopeless", "shaky", "untouched"):
            self.assertGreater(picks.count(name), 100, f"{name} gets its turn")
        self.assertLess(picks.count("solid"), 10,
                        "what it MAY starve is a target Sim is confidently good at: "
                        "there is nothing to learn there")

    def test_everything_recent_starts_a_fresh_lap(self):
        rng = _rng()
        every = [u.name for u in self.unknowns]
        self.assertIsNotNone(pick(self.unknowns, rng=rng, recent=every))

    def test_a_posterior_triple_converts_as_the_competence_table_gives_it(self):
        self.assertEqual(from_posterior("patch", (3.0, 7.0, 8)).samples, 8)


if __name__ == "__main__":
    unittest.main()
