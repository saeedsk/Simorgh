import unittest

from simorgh.contracts.envelope import Event
from simorgh.learning.competence import CompetenceTable


def _outcome_event(seq, task_type, succeeded, strategy=None, weight=1.0, confidence=None):
    payload = {"task_type": task_type, "succeeded": succeeded, "weight": weight,
               "verdict": "pass" if succeeded else "fail", "cost_usd": 0.01, "duration_s": 1.0}
    if strategy:
        payload["strategy"] = strategy
    if confidence is not None:
        payload["stated_confidence"] = confidence
    return Event(stream="learn:outcomes", type="outcome", ts=1.0, trace_id="t", causation_id=None,
                 payload=payload, seq=seq)


class TestCompetenceTable(unittest.TestCase):
    def test_no_samples_defaults_to_neutral_prior(self):
        table = CompetenceTable()
        self.assertEqual(table.success_rate("patch"), 0.5)
        self.assertEqual(table.samples("patch"), 0)
        self.assertEqual(table.suggest("patch", explore_bonus=0.1, min_samples_for_trust=5), [])

    def test_success_rate_uses_laplace_smoothing(self):
        table = CompetenceTable()
        for i in range(3):
            table.apply(_outcome_event(i + 1, "patch", True))
        # p = (3 + 1) / (3 + 2) = 0.8
        self.assertAlmostEqual(table.success_rate("patch"), 0.8)
        self.assertEqual(table.samples("patch"), 3)

    def test_apply_is_idempotent_with_rebuild(self):
        table_a = CompetenceTable()
        events = [_outcome_event(i + 1, "patch", i % 2 == 0) for i in range(10)]
        for e in events:
            table_a.apply(e)

        table_b = CompetenceTable()
        for e in events:
            table_b.apply(e)

        self.assertEqual(table_a.state(), table_b.state())

    def test_blocked_negative_sample_uses_partial_weight(self):
        table = CompetenceTable()
        table.apply(_outcome_event(1, "patch", False, weight=0.5))
        stats = table.get("patch")
        self.assertEqual(stats.n, 1)
        self.assertEqual(stats.successes_w, 0.0)

    def test_suggest_ranks_strategies_and_applies_shrinkage(self):
        table = CompetenceTable()
        # strategy A: 10/10 successes (well-sampled, high confidence)
        for i in range(10):
            table.apply(_outcome_event(i + 1, "patch", True, strategy="a"))
        # strategy B: 1/1 success (under-sampled -- should shrink toward 0.5)
        table.apply(_outcome_event(11, "patch", True, strategy="b"))

        scores = table.suggest("patch", explore_bonus=0.0, min_samples_for_trust=5)
        by_key = {s.strategy: s for s in scores}
        self.assertGreater(by_key["a"].success_rate, by_key["b"].success_rate)
        # b's raw Laplace rate would be (1+1)/(1+2) = 0.667, shrunk toward 0.5
        self.assertLess(by_key["b"].success_rate, 0.667)

    def test_suggest_exploration_bonus_favors_under_sampled_strategy(self):
        table = CompetenceTable()
        for i in range(20):
            table.apply(_outcome_event(i + 1, "patch", True, strategy="well_known"))
        table.apply(_outcome_event(21, "patch", True, strategy="rare"))

        # With a large exploration bonus, the under-sampled "rare" strategy
        # can out-rank the well-established one despite a lower raw rate.
        scores = table.suggest("patch", explore_bonus=5.0, min_samples_for_trust=1)
        self.assertEqual(scores[0].strategy, "rare")

    def test_calibration_with_no_confidence_data_is_neutral(self):
        table = CompetenceTable()
        table.apply(_outcome_event(1, "patch", True))
        self.assertEqual(table.calibration("patch"), 0.5)

    def test_calibration_perfect_when_confidence_matches_outcome(self):
        table = CompetenceTable()
        table.apply(_outcome_event(1, "patch", True, confidence=1.0))
        table.apply(_outcome_event(2, "patch", False, confidence=0.0))
        self.assertAlmostEqual(table.calibration("patch"), 1.0)

    def test_calibration_worst_when_confidence_is_inverted(self):
        table = CompetenceTable()
        table.apply(_outcome_event(1, "patch", False, confidence=1.0))
        self.assertAlmostEqual(table.calibration("patch"), 0.0)

    def test_state_and_load_round_trip(self):
        table = CompetenceTable()
        for i in range(5):
            table.apply(_outcome_event(i + 1, "patch", i % 2 == 0, strategy="a", confidence=0.6))
        state = table.state()

        restored = CompetenceTable()
        restored.load(state)

        self.assertEqual(restored.success_rate("patch"), table.success_rate("patch"))
        self.assertEqual(restored.samples("patch"), table.samples("patch"))
        self.assertEqual(restored.calibration("patch"), table.calibration("patch"))
        self.assertEqual(
            restored.suggest("patch", explore_bonus=0.1, min_samples_for_trust=5),
            table.suggest("patch", explore_bonus=0.1, min_samples_for_trust=5),
        )

    def test_non_outcome_events_are_ignored(self):
        table = CompetenceTable()
        table.apply(Event(stream="learn:outcomes", type="something_else", ts=1.0, trace_id="t",
                           causation_id=None, payload={}, seq=1))
        self.assertEqual(table.samples("patch"), 0)


if __name__ == "__main__":
    unittest.main()
