import unittest

from src.orchestrator.persona_state import ArousalLevel, PersonaState, Valence


class TestPersonaState(unittest.TestCase):
    def test_starts_neutral(self):
        state = PersonaState()
        current = state.current
        self.assertEqual(current.valence, 0.0)
        self.assertEqual(current.arousal, 0.0)
        self.assertEqual(current.cognitive_load, 0.0)

    def test_set_state_clamps_out_of_range_values(self):
        state = PersonaState()
        result = state.set_state(valence=5.0, arousal=-5.0, cognitive_load=3.0)
        self.assertEqual(result.valence, 1.0)
        self.assertEqual(result.arousal, -1.0)
        self.assertEqual(result.cognitive_load, 1.0)

    def test_set_state_leaves_unspecified_dimensions_untouched(self):
        state = PersonaState()
        state.set_state(valence=0.4)
        result = state.set_state(arousal=0.6)
        self.assertEqual(result.valence, 0.4)
        self.assertEqual(result.arousal, 0.6)

    def test_apply_delta_is_additive_and_clamped(self):
        state = PersonaState()
        state.apply_delta(valence=0.9, arousal=0.9)
        result = state.apply_delta(valence=0.5, arousal=-0.2)
        self.assertEqual(result.valence, 1.0)
        self.assertAlmostEqual(result.arousal, 0.7)

    def test_decay_toward_baseline_moves_partway_to_neutral(self):
        state = PersonaState()
        state.set_state(valence=1.0, arousal=1.0)
        result = state.decay_toward_baseline(rate=0.5)
        self.assertAlmostEqual(result.valence, 0.5)
        self.assertAlmostEqual(result.arousal, 0.5)

    def test_history_tracks_committed_transitions(self):
        state = PersonaState()
        state.set_state(valence=0.2)
        state.set_state(valence=0.4)
        history = state.history()
        self.assertEqual(len(history), 3)
        self.assertEqual([s.valence for s in history], [0.0, 0.2, 0.4])

    def test_history_is_bounded_by_history_limit(self):
        state = PersonaState(history_limit=3)
        for i in range(10):
            state.set_state(valence=i / 10)
        self.assertEqual(len(state.history()), 3)

    def test_valence_and_arousal_labels(self):
        state = PersonaState()
        state.set_state(valence=0.5, arousal=0.8)
        self.assertEqual(state.current.valence_label, Valence.POSITIVE)
        self.assertEqual(state.current.arousal_label, ArousalLevel.HIGH)

        state.set_state(valence=-0.5, arousal=0.05)
        self.assertEqual(state.current.valence_label, Valence.NEGATIVE)
        self.assertEqual(state.current.arousal_label, ArousalLevel.LOW)


if __name__ == "__main__":
    unittest.main()
