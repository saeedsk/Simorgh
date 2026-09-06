import unittest

from simorgh.interface.vitals import VitalsCache


class VitalsCacheTestCase(unittest.TestCase):
    def test_stale_until_persona_state_observed(self):
        cache = VitalsCache()
        self.assertTrue(cache.snapshot().stale)
        cache.on_persona_state({"valence": 0.3, "arousal": 0.1, "cognitive_load": 0.2})
        self.assertFalse(cache.snapshot().stale)

    def test_persona_state_feeds_mood_energy_load(self):
        cache = VitalsCache()
        cache.on_persona_state({"valence": 0.4, "arousal": -0.2, "cognitive_load": 0.6})
        snap = cache.snapshot()
        self.assertEqual(snap.mood, 0.4)
        self.assertEqual(snap.energy, -0.2)
        self.assertEqual(snap.load, 0.6)

    def test_system_metrics_feed_counters(self):
        cache = VitalsCache()
        cache.on_persona_state({"valence": 0.0, "arousal": 0.0, "cognitive_load": 0.0})
        cache.on_system_metrics({"subsystem": "memory", "counters": {"stored": 5}, "gauges": {}})
        self.assertEqual(cache.snapshot().memory_records, 5)

    def test_guardian_posture_updates_from_the_contracts_mode_field(self):
        # Live-caught (post-cutover review): Guardian publishes
        # `guardian.posture.changed{mode: ...}` (the contract's field); the
        # cache read a `posture` key that never arrives, so the panel said
        # `posture: unknown` all day regardless of real events.
        cache = VitalsCache()
        cache.on_guardian_posture({"mode": "locked", "trust_score": 0.0, "reason": "test"})
        self.assertEqual(cache.snapshot().posture, "locked")

    def test_guardian_posture_legacy_key_still_accepted(self):
        cache = VitalsCache()
        cache.on_guardian_posture({"posture": "cautious"})
        self.assertEqual(cache.snapshot().posture, "cautious")


if __name__ == "__main__":
    unittest.main()
