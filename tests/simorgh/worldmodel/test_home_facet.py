"""Stage 6 item 3: what the house is doing and who is in it, from the
evidence Sim already sees -- with evidence that decays and staleness said
out loud rather than rendered as fact."""

from __future__ import annotations

import time
import unittest

from simorgh.worldmodel.facets.home import HALF_LIFE_S, STALE_AFTER_S, HomeFacet, decayed


class _Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class AScriptedEvening(unittest.IsolatedAsyncioTestCase):
    """The plan's own acceptance: the TV on, a child's voice in the living
    room, a camera event at the door."""

    def setUp(self):
        # 21:00 local, so the hour-dependent facts are not quiet hours.
        self.clock = _Clock(time.mktime((2026, 9, 19, 21, 0, 0, 0, 0, -1)))
        self.home = HomeFacet(clock=self.clock)

    async def test_the_situation_follows_from_the_evidence(self):
        self.home.observe("tv.family_room", kind="tv", state="playing", area="family room")
        self.home.saw_person("Ira", area="living room", strength=0.9)
        self.home.observe("camera.front_door", kind="camera", state="person", area="front door")
        situation = self.home.situation()
        self.assertTrue(situation["tv_playing"])
        self.assertTrue(situation["child_alone"], "a child placed and no adult")
        self.assertFalse(situation["quiet_hours"])
        self.assertEqual(situation["people"], {"Ira": "living room"})
        self.assertIs(situation["nobody_home"], False)

    async def test_an_area_with_no_evidence_is_unknown_not_empty(self):
        fresh = HomeFacet(clock=self.clock)
        self.assertIsNone(fresh.situation()["nobody_home"], "no evidence either way is not 'nobody home'")
        self.assertEqual(fresh.where("Saeed"), ("unknown", 0.0))

    async def test_an_adult_present_means_the_child_is_not_alone(self):
        self.home.saw_person("Ira", area="living room")
        self.home.saw_person("Soodeh", area="kitchen")
        self.assertFalse(self.home.situation()["child_alone"])

    async def test_presence_decays_and_is_reported_as_unknown(self):
        self.home.saw_person("Aran", area="kitchen", strength=1.0)
        self.assertEqual(self.home.where("Aran")[0], "kitchen")
        self.clock.t += HALF_LIFE_S * 3          # two and a half hours later
        self.assertEqual(self.home.where("Aran"), ("unknown", 0.0))
        self.assertEqual(self.home.presence()["Aran"], {"unknown": 1.0})

    async def test_a_stale_entity_is_named_stale_rather_than_reported(self):
        self.home.observe("tv.family_room", kind="tv", state="playing", area="family room")
        self.clock.t += STALE_AFTER_S + 60
        block = self.home.now_block()
        self.assertIn("unknown", block)
        self.assertNotIn("playing", block)
        self.assertFalse(self.home.situation()["tv_playing"], "a two-hour-old reading is not the state now")

    async def test_quiet_hours_at_two_in_the_morning(self):
        night = HomeFacet(clock=_Clock(time.mktime((2026, 9, 20, 2, 0, 0, 0, 0, -1))))
        night.saw_person("Iris", area="living room")
        situation = night.situation()
        self.assertTrue(situation["quiet_hours"])
        self.assertTrue(situation["someone_asleep"])

    async def test_the_query_shape(self):
        self.home.saw_person("Saeed", area="office")
        answer = await self.home.get({})
        self.assertIn("presence", answer)
        self.assertEqual((await self.home.get({"person": "Saeed"}))["area"], "office")


class Decay(unittest.TestCase):
    def test_a_belief_halves_over_the_half_life(self):
        self.assertAlmostEqual(decayed(1.0, HALF_LIFE_S), 0.5)
        self.assertAlmostEqual(decayed(1.0, 0.0), 1.0)
        self.assertEqual(decayed(0.0, 100.0), 0.0)


if __name__ == "__main__":
    unittest.main()
