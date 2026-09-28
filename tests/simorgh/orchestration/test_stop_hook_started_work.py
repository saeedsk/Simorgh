"""A chat reply saying work is under way, when nothing was started, bounces.

Live 2026-09-27: «رفت سرِ کارش سعید -- ... درست می‌کنم ... تموم شد خبرت می‌کنم»
with no tool called and no task made."""

import unittest
from types import SimpleNamespace as N

from simorgh.orchestration import stophook


def _chat(steps=()):
    return N(profile=N(scaffold="chat", tools=("start_task",)), steps=list(steps), user_text="fix it",
             claim_corrected=False)


class StartedWork(unittest.TestCase):
    def test_the_live_farsi_line(self):
        said = "رفت سرِ کارش سعید — تشخیص گفتار رو برای فارسی درست می‌کنم. تموم شد خبرت می‌کنم."
        bounce = stophook.check(said, _chat())
        self.assertIsNotNone(bounce)
        self.assertEqual(bounce.rule, "started")

    def test_english(self):
        self.assertTrue(stophook.claimed_to_start_work("I'm on it, I'll let you know when it's done.", _chat()))

    def test_a_task_that_was_started_is_fine(self):
        ran = N(tool="start_task", ok=True)
        self.assertEqual(stophook.claimed_to_start_work("I'm on it.", _chat([ran])), "")

    def test_ordinary_replies_are_left_alone(self):
        for said in ("The kitchen light is on.", "شروع کن سعید؟", "Let me know if you want more."):
            self.assertEqual(stophook.claimed_to_start_work(said, _chat()), "", said)


if __name__ == "__main__":
    unittest.main()
