"""A door and a thermostat do not go stale at the same speed.

Stage 6 item 3 asks for "staleness = age / learned typical change
rate". It was a flat two hours for everything, and the two ends of
the house make that obviously wrong in both directions: a door
sensor observed thirty minutes ago tells you nothing, and a
thermostat observed this morning is almost certainly still right.

What is learned is the gap between CHANGES, not between
observations: how often Sim happens to look at a thing says nothing
about how often it moves, and it is the moving that decides when an
old reading stops being worth anything.
"""

import unittest

from simorgh.worldmodel.facets.home import (
    INTERVALS_KEPT, STALE_AFTER_S, STALE_CEILING_S, STALE_FLOOR_S, HomeFacet,
)


def _rhythm(key: str, gap: float, n: int, *, kind: str = "other") -> HomeFacet:
    """`n` state changes, `gap` seconds apart."""
    facet = HomeFacet(clock=lambda: 0.0)
    at = 0.0
    for i in range(n):
        at += gap
        facet.observe(key, kind=kind, state=str(i), at=at)
    return facet


class WhatIsLearned(unittest.TestCase):
    def test_a_fast_thing_is_trusted_briefly(self):
        entity = _rhythm("binary_sensor.door", 120.0, 8).entities["binary_sensor.door"]
        self.assertAlmostEqual(entity.typical_change_s(), 120.0, places=1)
        self.assertLess(entity.stale_after_s(), STALE_AFTER_S)

    def test_a_slow_thing_is_trusted_far_longer(self):
        entity = _rhythm("climate.hall", 43_200.0, 5).entities["climate.hall"]
        self.assertGreater(entity.stale_after_s(), STALE_AFTER_S)

    def test_the_median_not_the_mean(self):
        """One device left alone over a weekend must not make a
        minute-by-minute sensor look slow."""
        facet = HomeFacet(clock=lambda: 0.0)
        at = 0.0
        for i, gap in enumerate([60.0, 60.0, 60.0, 250_000.0, 60.0, 60.0]):
            at += gap
            facet.observe("binary_sensor.door", kind="other", state=str(i), at=at)
        self.assertLess(facet.entities["binary_sensor.door"].typical_change_s(), 200.0)


class WhenNothingIsKnown(unittest.TestCase):
    def test_a_brand_new_entity_keeps_the_old_flat_answer(self):
        facet = HomeFacet(clock=lambda: 0.0)
        facet.observe("light.new", kind="light", state="on", at=0.0)
        self.assertEqual(facet.entities["light.new"].stale_after_s(), STALE_AFTER_S)

    def test_two_changes_are_not_a_rhythm(self):
        """Two gaps can be anything; three is the least that means
        something."""
        self.assertIsNone(_rhythm("x", 60.0, 2).entities["x"].typical_change_s())


class TheBoundsHold(unittest.TestCase):
    def test_nothing_is_stale_the_instant_it_is_seen(self):
        entity = _rhythm("binary_sensor.twitchy", 0.5, 10).entities["binary_sensor.twitchy"]
        self.assertGreaterEqual(entity.stale_after_s(), STALE_FLOOR_S)

    def test_and_nothing_is_fresh_forever(self):
        entity = _rhythm("sensor.annual", 400 * 86_400.0, 5).entities["sensor.annual"]
        self.assertLessEqual(entity.stale_after_s(), STALE_CEILING_S)


class WhatCountsAsAChange(unittest.TestCase):
    def test_observing_the_same_state_again_teaches_nothing(self):
        """Polling a light that is on every ten seconds must not make
        it look like it changes every ten seconds."""
        facet = HomeFacet(clock=lambda: 0.0)
        for i in range(12):
            facet.observe("light.kitchen", kind="light", state="on", at=float(i) * 10.0)
        self.assertIsNone(facet.entities["light.kitchen"].typical_change_s())

    def test_history_survives_an_observation(self):
        """`observe` replaces the whole Entity, so the rhythm has to
        be carried forward deliberately."""
        facet = _rhythm("binary_sensor.door", 120.0, 8)
        facet.observe("binary_sensor.door", kind="other", state="7", at=10_000.0)
        self.assertIsNotNone(facet.entities["binary_sensor.door"].typical_change_s())

    def test_the_list_is_bounded(self):
        facet = _rhythm("binary_sensor.door", 60.0, INTERVALS_KEPT * 3)
        self.assertLessEqual(len(facet.entities["binary_sensor.door"].intervals), INTERVALS_KEPT)


class ItIsVisible(unittest.TestCase):
    def test_the_dict_says_how_long_it_is_trusted_for(self):
        """Reading "stale: false" without knowing the window behind it
        is why the flat two hours went unquestioned for so long."""
        facet = _rhythm("binary_sensor.door", 120.0, 8)
        self.assertIn("stale_after_s", facet.entities["binary_sensor.door"].as_dict(0.0))


if __name__ == "__main__":
    unittest.main()
