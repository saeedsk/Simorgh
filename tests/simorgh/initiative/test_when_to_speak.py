"""Stage 6 item 6: the plan's own acceptance -- a camera event at 02:00
with a child asleep in the living room goes to the owner's phone, not the
speaker."""

from __future__ import annotations

import unittest

from simorgh.initiative.api import COOLDOWN, DAILY_CAP, Notice, Situation, decide

NIGHT = Situation(quiet_hours=True, someone_asleep=True, child_alone=True, people={"Iris": "living room"})
EVENING = Situation(people={"Saeed": "kitchen", "Soodeh": "kitchen"})
EMPTY = Situation()


class TheNightCase(unittest.TestCase):
    def test_a_camera_event_at_two_in_the_morning_goes_to_the_phone(self):
        delivery = decide(Notice("event_fyi", "a car in the driveway"), NIGHT)
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.channel, "phone")
        self.assertEqual(delivery.tool, "notify")
        self.assertEqual(delivery.to, "Saeed")

    def test_the_same_event_in_the_evening_may_be_spoken(self):
        delivery = decide(Notice("event_fyi", "a car in the driveway"), EVENING)
        self.assertIsNotNone(delivery)
        self.assertIn(delivery.channel, ("speaker", "screen", "phone"))
        self.assertGreater(delivery.utility, 0.0)

    def test_a_safety_alert_is_never_dropped(self):
        for situation in (NIGHT, EMPTY, EVENING):
            with self.subTest(situation=situation):
                delivery = decide(Notice("safety_alert", "smoke in the kitchen"), situation)
                self.assertIsNotNone(delivery)


class WhatItWillNotDo(unittest.TestCase):
    def test_it_does_not_talk_to_an_empty_room(self):
        delivery = decide(Notice("news", "an interesting paper"), EMPTY)
        self.assertTrue(delivery is None or delivery.channel != "speaker")

    def test_small_talk_waits(self):
        self.assertIsNone(decide(Notice("news", "an interesting paper"), NIGHT))
        self.assertIsNone(decide(Notice("growth", "I learnt something"), NIGHT))

    def test_a_class_respects_its_cooldown(self):
        now = 1_790_000_000.0
        self.assertIsNone(decide(Notice("event_fyi", "again"), EVENING, now=now,
                                 last_by_kind={"event_fyi": now - COOLDOWN["event_fyi"] / 2}))
        self.assertIsNotNone(decide(Notice("event_fyi", "again"), EVENING, now=now,
                                    last_by_kind={"event_fyi": now - COOLDOWN["event_fyi"] - 1}))

    def test_the_daily_cap_holds_but_not_against_safety(self):
        self.assertIsNone(decide(Notice("event_fyi", "x"), EVENING, delivered_today=DAILY_CAP))
        self.assertIsNotNone(decide(Notice("safety_alert", "smoke"), EVENING, delivered_today=DAILY_CAP))

    def test_do_not_disturb_is_honoured_except_for_safety(self):
        reminder = Notice("reminder", "the dentist", person="Soodeh")
        self.assertIsNone(decide(reminder, EVENING, do_not_disturb={"Soodeh"}))
        self.assertIsNotNone(decide(Notice("safety_alert", "smoke", person="Soodeh"), EVENING,
                                    do_not_disturb={"Soodeh"}))

    def test_a_reminder_is_not_announced_in_a_room_its_person_is_not_in(self):
        delivery = decide(Notice("reminder", "leave in ten minutes", person="Aran"), EVENING)
        self.assertTrue(delivery is None or delivery.channel != "speaker")


if __name__ == "__main__":
    unittest.main()
