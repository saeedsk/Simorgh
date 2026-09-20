"""Stage 10 item 2: how a person seems, against their own usual -- a
baseline per person, a Beta posterior over low-side turns with forgetting,
`unknown` as a visible answer, and nothing kept about anybody who has not
said yes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.worldmodel.facets.wellbeing import (
    BASELINE_MIN,
    FRESH_S,
    HALF_LIFE_S,
    LOW_AT,
    MIN_EVIDENCE,
    WellbeingFacet,
    decayed,
    features_of,
)

USUAL = "Could you add milk and eggs to the list, and remind me about the dentist on Thursday afternoon?"
SHORT = "fine."
LONG = ("Oh that is brilliant news, I have been waiting all week to hear that -- tell me everything, "
        "how did it go, what did they say, and can we celebrate properly this weekend with everyone?")

CONSENTED = {"Soodeh", "Saeed"}


def consent(name):
    return (name in CONSENTED, "" if name in CONSENTED else f"{name} has not said yes")


class _Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class _Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "wellbeing.json"
        self.clock = _Clock()
        self.facet = WellbeingFacet(self.path, clock=self.clock, consent=consent)

    def baseline(self, person="Soodeh", turns=BASELINE_MIN, every=12 * 3600.0):
        """`turns` usual turns, one every `every` seconds, ending now. These
        only teach the baseline: nothing is scored yet, so the state after
        them is still `unknown`."""
        for i in range(turns):
            self.clock.t += every
            self.assertTrue(self.facet.observe(person, text=USUAL, seconds=6.0, tone="neutral"))

    def settle(self, person="Soodeh", turns=4):
        """A few usual turns in the last hour, scored against the baseline,
        so there is fresh evidence and the state reads `usual`."""
        for _ in range(turns):
            self.clock.t += 600
            self.assertTrue(self.facet.observe(person, text=USUAL, seconds=6.0, tone="neutral"))


class NothingFromSilence(_Case):
    def test_no_turns_is_unknown_not_fine(self):
        est = self.facet.estimate("Soodeh")
        self.assertEqual(est["state"], "unknown")
        self.assertTrue(est["tracked"])
        self.assertEqual(est["why"], "no turns yet")
        self.assertEqual(self.facet.now_block(person="Soodeh"), "- Soodeh: no recent read (no turns yet)")

    def test_the_baseline_forms_before_anything_is_scored(self):
        for i in range(BASELINE_MIN - 1):
            self.clock.t += 3600
            self.facet.observe("Soodeh", text=SHORT)
        est = self.facet.estimate("Soodeh")
        self.assertEqual(est["state"], "unknown")
        self.assertIn("baseline forming", est["why"])
        self.assertEqual(est["samples"], 0, "nothing is scored against a baseline that is not there yet")

    def test_a_baseline_alone_is_not_a_state(self):
        self.baseline()
        est = self.facet.estimate("Soodeh")
        self.assertEqual(est["state"], "unknown")
        self.assertIn("too little recent evidence", est["why"])

    def test_a_person_not_heard_for_a_day_has_no_state(self):
        self.baseline()
        self.settle()
        self.assertEqual(self.facet.estimate("Soodeh")["state"], "usual")
        self.clock.t += FRESH_S + 60
        est = self.facet.estimate("Soodeh")
        self.assertEqual(est["state"], "unknown")
        self.assertEqual(est["why"], "not heard from lately")


class Consent(_Case):
    def test_nobody_without_consent_is_ever_stored(self):
        for name in ("Ira", "Bobby", "", "Aran"):
            with self.subTest(name=name):
                self.assertFalse(self.facet.observe(name, text=USUAL))
        self.assertFalse(self.path.exists() and "Ira" in self.path.read_text())
        est = self.facet.estimate("Ira")
        self.assertFalse(est["tracked"])
        self.assertEqual(est["state"], "unknown")
        self.assertIn("not said yes", est["why"])
        self.assertEqual(self.facet.now_block(person="Ira"), "", "not even a line saying so")
        self.assertEqual(self.facet.tracked(), [])

    def test_a_facet_told_nothing_about_consent_tracks_nobody(self):
        alone = WellbeingFacet(clock=self.clock)
        self.assertFalse(alone.observe("Saeed", text=USUAL))

    def test_forgetting_drops_everything(self):
        self.baseline()
        self.assertTrue(self.facet.forget("Soodeh"))
        self.assertEqual(self.facet.estimate("Soodeh")["why"], "no turns yet")
        self.assertNotIn("Soodeh", json.loads(self.path.read_text())["people"])
        self.assertFalse(self.facet.forget("Soodeh"), "nothing left to forget")


class TheDeviation(_Case):
    def test_twelve_usual_turns_then_five_short_ones_reads_low(self):
        self.baseline()
        for _ in range(5):
            self.clock.t += 600
            self.facet.observe("Soodeh", text=SHORT, seconds=1.0, tone="warm")
        est = self.facet.estimate("Soodeh")
        self.assertEqual(est["state"], "low", est)
        self.assertGreaterEqual(est["low"], LOW_AT)
        self.assertGreaterEqual(est["evidence"], MIN_EVIDENCE)
        note = self.facet.now_block(person="Soodeh")
        self.assertIn("quieter than usual", note)
        self.assertNotIn("fine", note, "never a word of theirs")
        self.assertNotIn(USUAL[:20], note)

    def test_five_usual_turns_read_usual_and_five_long_ones_read_high(self):
        self.baseline()
        for _ in range(5):
            self.clock.t += 600
            self.facet.observe("Soodeh", text=USUAL, seconds=6.0, tone="neutral")
        self.assertEqual(self.facet.estimate("Soodeh")["state"], "usual")
        for _ in range(5):
            self.clock.t += 600
            self.facet.observe("Soodeh", text=LONG, seconds=6.0, tone="bright")
        est = self.facet.estimate("Soodeh")
        self.assertEqual(est["state"], "high", est)
        self.assertIn("brighter than usual", self.facet.now_block(person="Soodeh"))

    def test_the_same_five_short_turns_spread_over_two_days_are_not_enough(self):
        """Five quiet turns in an hour is a pattern; five over two days,
        each half-forgotten before the next, is not evidence of anything."""
        self.baseline()
        for _ in range(5):
            self.clock.t += 12 * 3600
            self.facet.observe("Soodeh", text=SHORT, seconds=1.0)
        est = self.facet.estimate("Soodeh")
        self.assertNotEqual(est["state"], "low", est)
        self.assertLess(est["evidence"], MIN_EVIDENCE)

    def test_a_quiet_person_is_not_low_for_being_quiet(self):
        """The baseline is theirs: somebody whose usual is two words is
        at their usual with two words."""
        for _ in range(BASELINE_MIN + 5):
            self.clock.t += 600
            self.facet.observe("Saeed", text="ok thanks", seconds=1.0)
        self.assertEqual(self.facet.estimate("Saeed")["state"], "usual")

    def test_a_long_change_becomes_the_new_usual(self):
        self.baseline()
        state_seen = set()
        for _ in range(60):
            self.clock.t += 1800
            self.facet.observe("Soodeh", text=SHORT, seconds=1.0)
            state_seen.add(self.facet.estimate("Soodeh")["state"])
        self.assertIn("low", state_seen, "it did notice...")
        self.assertEqual(self.facet.estimate("Soodeh")["state"], "usual", "...and then stopped, because this is her now")

    def test_changes_reports_flips_once(self):
        self.baseline()
        self.assertEqual(self.facet.changes(), [], "a baseline forming is still unknown: no flip")
        self.settle()
        self.assertEqual([(p, e["state"]) for p, e in self.facet.changes()], [("Soodeh", "usual")],
                         "unknown -> usual is a flip")
        self.assertEqual(self.facet.changes(), [], "and not again until it moves")
        for _ in range(5):
            self.clock.t += 600
            self.facet.observe("Soodeh", text=SHORT, seconds=1.0, tone="warm")
        moved = self.facet.changes()
        self.assertEqual([(p, e["state"]) for p, e in moved], [("Soodeh", "low")])
        self.assertEqual(self.facet.changes(), [])


class TheBlockAndTheQuery(_Case):
    def test_the_block_names_one_person_when_asked_for_one(self):
        self.baseline("Soodeh")
        self.settle("Soodeh")
        self.baseline("Saeed")
        self.settle("Saeed")
        block = self.facet.now_block(person="Soodeh")
        self.assertIn("Soodeh", block)
        self.assertNotIn("Saeed", block, "one person's state is not for another's turn")
        self.assertEqual(len(self.facet.now_block().splitlines()), 2)

    def test_the_query_shapes(self):
        import asyncio

        self.baseline()
        self.settle()
        one = asyncio.run(self.facet.get({"person": "Soodeh"}))
        self.assertEqual(one["state"], "usual")
        self.assertIn("note", one)
        self.assertIn("evidence", one)
        everybody = asyncio.run(self.facet.get({}))
        self.assertEqual([p["person"] for p in everybody["people"]], ["Soodeh"])
        nobody = asyncio.run(self.facet.get({"person": "Ira"}))
        self.assertFalse(nobody["tracked"])


class ItSurvivesARestart(_Case):
    def test_the_baseline_and_window_are_read_back(self):
        self.baseline()
        self.settle()
        again = WellbeingFacet(self.path, clock=self.clock, consent=consent)
        est = again.estimate("Soodeh")
        self.assertEqual(est["state"], "usual")
        self.assertGreaterEqual(est["baseline_turns"], BASELINE_MIN)
        self.path.write_text("{not json")
        self.assertEqual(WellbeingFacet(self.path, clock=self.clock, consent=consent).estimate("Soodeh")["why"],
                         "no turns yet", "an unreadable file is a fresh start, not a crash")


class TheParts(unittest.TestCase):
    def test_features_are_cheap_and_deterministic(self):
        self.assertEqual(features_of("", tone="warm"), {"soft": 1.0})
        self.assertEqual(set(features_of("one two three", seconds=1.5, tone="bright")), {"words", "rate", "soft"})
        self.assertEqual(features_of("one two three", seconds=1.5, tone="bright")["rate"], 2.0)
        self.assertNotIn("rate", features_of("one two", seconds=0.1), "a tenth of a second is not a measurement")

    def test_a_trial_halves_every_half_life(self):
        self.assertAlmostEqual(decayed(1.0, HALF_LIFE_S), 0.5)
        self.assertAlmostEqual(decayed(1.0, 2 * HALF_LIFE_S), 0.25)
        self.assertEqual(decayed(1.0, 0.0), 1.0)


if __name__ == "__main__":
    unittest.main()
