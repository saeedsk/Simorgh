import unittest

from simorgh.orchestration import Budget, profiles
from simorgh.orchestration.api import Session, Step


class TestBudget(unittest.TestCase):
    def test_steps_left_and_exhausted(self):
        b = Budget(max_steps=3)
        self.assertEqual(b.steps_left, 3)
        b.steps_used = 2
        self.assertTrue(b.is_last_step)
        self.assertFalse(b.exhausted)
        b.steps_used = 3
        self.assertTrue(b.exhausted)
        self.assertEqual(b.steps_left, 0)


class TestProfiles(unittest.TestCase):
    def test_for_task_plan_mode_is_always_read_only(self):
        p = profiles.for_task("patch", "plan")
        self.assertTrue(p.read_only)
        self.assertEqual(p.name, "plan")

    def test_for_task_unknown_kind_falls_back_to_chat(self):
        p = profiles.for_task("nonsense", "execute")
        self.assertEqual(p, profiles.CHAT)

    def test_chat_profile_skips_verification_by_default(self):
        self.assertFalse(profiles.CHAT.verify)

    def test_patch_profile_allows_revisions(self):
        self.assertGreater(profiles.PATCH.max_revisions, 0)


class TestSession(unittest.TestCase):
    def test_next_step_no_and_record(self):
        s = Session(task_id="t1", kind="chat", mode="execute", profile=profiles.CHAT)
        self.assertEqual(s.next_step_no(), 1)
        s.record(Step(1, "gather", "x"))
        self.assertEqual(s.next_step_no(), 2)
        self.assertEqual(len(s.steps), 1)


if __name__ == "__main__":
    unittest.main()
