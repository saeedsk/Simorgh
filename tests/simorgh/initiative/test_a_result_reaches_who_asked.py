"""A notice for one person reaches that person, never the owner's phone
(stage 18 review: "Initiative's notice can reach the owner for someone
else's background result").

`notify` has no recipient: it reaches the person who runs Sim. So the
phone and the screen are the owner's channels, and a reminder -- or a
background crew's result, which arrives as one -- for anybody else may
only be said in the room they are in. It used to win on the phone every
time (0.6 against the speaker's 0.25), which put Soodeh's answer on
Saeed's phone with "for Soodeh" in the subject. The end-to-end case, two
people through a real Orchestration, is in
tests/simorgh/orchestration/test_crew_review_gaps.py."""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.initiative.api import Notice, Situation, decide, for_owner

from .test_companion import _CompanionHarness

APART = Situation(people={"Soodeh": "kitchen", "Saeed": "office"})
TOGETHER = Situation(people={"Soodeh": "kitchen", "Saeed": "kitchen"})
SOODEH_OUT = Situation(people={"Saeed": "office"})


def _for(person: str, text: str = "A costs 325.") -> Notice:
    return Notice("reminder", text, person=person, ref="crew:voice-1")


class TwoPeople(unittest.TestCase):
    def test_hers_is_said_in_her_room_and_his_goes_to_his_phone(self):
        hers, his = decide(_for("Soodeh"), APART), decide(_for("Saeed"), APART)
        self.assertEqual((hers.channel, hers.tool, hers.to), ("speaker", "speak", "Soodeh"))
        self.assertEqual((his.channel, his.tool, his.to), ("phone", "notify", "Saeed"))

    def test_hers_never_reaches_the_owners_phone(self):
        for situation in (APART, TOGETHER, SOODEH_OUT, Situation(quiet_hours=True, people={"Soodeh": "kitchen"})):
            with self.subTest(situation=situation):
                delivery = decide(_for("Soodeh"), situation)
                self.assertTrue(delivery is None or delivery.tool == "speak", delivery)

    def test_the_owner_is_matched_whatever_the_case(self):
        self.assertTrue(for_owner(_for("saeed"), "Saeed"))
        self.assertTrue(for_owner(Notice("reminder", "bins"), "Saeed"), "the household's is the owner's to read")
        self.assertFalse(for_owner(_for("Soodeh"), "Saeed"))

    def test_a_safety_alert_still_reaches_somebody(self):
        delivery = decide(Notice("safety_alert", "smoke", person="Soodeh"), SOODEH_OUT)
        self.assertIsNotNone(delivery)


class TheServiceSaysWhy(_CompanionHarness):
    async def test_a_result_with_no_way_to_her_is_suppressed_with_the_reason(self):
        self.situation = SOODEH_OUT
        await self.bus.deliver(topics.PERCEPT_TIME_SCHEDULED,
                               {"schedule_id": "crew:voice-1", "label": "A costs 325.", "person": "Soodeh"})
        self.assertEqual(self.bus.of(topics.ACTION_PROPOSED), [], "not to the owner's phone")
        suppressed = self.bus.of(topics.INITIATIVE_SUPPRESSED)
        self.assertEqual(len(suppressed), 1)
        self.assertIn("the phone is the owner's", suppressed[0]["why"])

    async def test_two_people_two_deliveries_each_to_its_own(self):
        self.situation = APART
        for person, label in (("Soodeh", "A costs 325."), ("Saeed", "B costs 330.")):
            await self.bus.deliver(topics.PERCEPT_TIME_SCHEDULED,
                                   {"schedule_id": f"crew:voice-{person}", "label": label, "person": person})
        proposals = self.bus.of(topics.ACTION_PROPOSED)
        self.assertEqual([(p["tool"], p["args"].get("text") or p["args"].get("body")) for p in proposals],
                         [("speak", "A costs 325."), ("notify", "B costs 330.")])
        offered = self.bus.of(topics.INITIATIVE_OFFERED)
        self.assertEqual([(o["person"], o["to"]) for o in offered], [("Soodeh", "Soodeh"), ("Saeed", "Saeed")])


if __name__ == "__main__":
    unittest.main()
