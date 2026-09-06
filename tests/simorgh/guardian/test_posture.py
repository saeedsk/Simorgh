"""`Posture` (09-guardian.md section 5.3): only ever tightens, never
loosens except `reset_to_baseline` -- a deliberate absence of any
message-driven loosening path (harness-06)."""

import unittest

from simorgh.guardian.posture import Posture


class TestPostureTighten(unittest.TestCase):
    def test_tighten_lowers_the_level(self):
        posture = Posture(level="trusted", baseline="trusted")
        posture.tighten("guarded", "budget pressure")
        self.assertEqual(posture.level, "guarded")
        self.assertEqual(posture.reasons, ["budget pressure"])

    def test_tighten_to_a_looser_level_is_a_no_op_on_level(self):
        posture = Posture(level="locked", baseline="guarded")
        posture.tighten("trusted", "should not loosen")
        self.assertEqual(posture.level, "locked")
        # reasons still records the attempt -- an audit trail even for a no-op
        self.assertIn("should not loosen", posture.reasons)

    def test_tighten_to_the_same_level_records_the_reason(self):
        posture = Posture(level="guarded", baseline="guarded")
        posture.tighten("guarded", "no-op tighten")
        self.assertEqual(posture.level, "guarded")
        self.assertIn("no-op tighten", posture.reasons)

    def test_reset_to_baseline_restores_level_and_clears_reasons(self):
        posture = Posture(level="locked", baseline="guarded", reasons=["a", "b"])
        posture.reset_to_baseline()
        self.assertEqual(posture.level, "guarded")
        self.assertEqual(posture.reasons, [])


class TestPostureApplyEvent(unittest.TestCase):
    def test_tightened_event_lowers_the_level(self):
        posture = Posture(level="trusted", baseline="trusted")
        posture.apply_event("tightened", {"to": "locked", "reason": "5 consecutive failures"})
        self.assertEqual(posture.level, "locked")
        self.assertEqual(posture.reasons, ["5 consecutive failures"])

    def test_tightened_event_never_loosens(self):
        posture = Posture(level="locked", baseline="guarded")
        posture.apply_event("tightened", {"to": "trusted", "reason": "ignored"})
        self.assertEqual(posture.level, "locked")

    def test_reset_to_baseline_event(self):
        posture = Posture(level="locked", baseline="guarded", reasons=["x"])
        posture.apply_event("reset_to_baseline", {})
        self.assertEqual(posture.level, "guarded")
        self.assertEqual(posture.reasons, [])

    def test_replaying_a_sequence_of_events_matches_direct_calls(self):
        events = [
            ("tightened", {"to": "guarded", "reason": "r1"}),
            ("tightened", {"to": "locked", "reason": "r2"}),
            ("reset_to_baseline", {}),
            ("tightened", {"to": "locked", "reason": "r3"}),
        ]
        replayed = Posture(level="trusted", baseline="trusted")
        for event_type, payload in events:
            replayed.apply_event(event_type, payload)

        direct = Posture(level="trusted", baseline="trusted")
        direct.tighten("guarded", "r1")
        direct.tighten("locked", "r2")
        direct.reset_to_baseline()
        direct.tighten("locked", "r3")

        self.assertEqual(replayed.level, direct.level)
        self.assertEqual(replayed.reasons, direct.reasons)


if __name__ == "__main__":
    unittest.main()
