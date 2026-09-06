import unittest

from simorgh.curiosity.projections import ActiveProject, AreaStaleness, BacklogCounter, RecentCandidates


class BacklogCounterTest(unittest.TestCase):
    def test_created_then_completed_nets_to_zero(self):
        c = BacklogCounter()
        c.on_created("t1")
        self.assertEqual(c.effective_count, 1)
        c.on_completed("t1")
        self.assertEqual(c.effective_count, 0)

    def test_terminal_failure_clears_task(self):
        c = BacklogCounter()
        c.on_created("t1")
        c.on_failed("t1", terminal=True)
        self.assertEqual(c.effective_count, 0)

    def test_non_terminal_failure_keeps_task_open(self):
        c = BacklogCounter()
        c.on_created("t1")
        c.on_failed("t1", terminal=False)
        self.assertEqual(c.effective_count, 1)

    def test_blocked_with_future_retry_does_not_count(self):
        c = BacklogCounter()
        c.on_created("t1")
        c.on_blocked("t1", retry_after=100.0, now=10.0)
        self.assertEqual(c.effective_count, 0)
        self.assertEqual(c.raw_count, 1)

    def test_blocked_with_past_retry_still_counts(self):
        c = BacklogCounter()
        c.on_created("t1")
        c.on_blocked("t1", retry_after=5.0, now=10.0)
        self.assertEqual(c.effective_count, 1)

    def test_blocked_without_retry_after_counts(self):
        c = BacklogCounter()
        c.on_created("t1")
        c.on_blocked("t1", retry_after=None, now=10.0)
        self.assertEqual(c.effective_count, 1)


class AreaStalenessTest(unittest.TestCase):
    def test_never_touched_has_no_age(self):
        s = AreaStaleness()
        self.assertIsNone(s.age("cognition", 100.0))

    def test_age_since_last_touch(self):
        s = AreaStaleness()
        s.touch("cognition", 10.0)
        self.assertEqual(s.age("cognition", 40.0), 30.0)

    def test_touch_only_moves_forward(self):
        s = AreaStaleness()
        s.touch("cognition", 40.0)
        s.touch("cognition", 10.0)
        self.assertEqual(s.age("cognition", 40.0), 0.0)

    def test_snapshot_covers_requested_areas(self):
        s = AreaStaleness()
        s.touch("a", 5.0)
        snap = s.snapshot(["a", "b"], 10.0)
        self.assertEqual(snap["a"], 5.0)
        self.assertIsNone(snap["b"])


class ActiveProjectTest(unittest.TestCase):
    def test_inactive_by_default(self):
        p = ActiveProject()
        self.assertFalse(p.is_active(0.0))

    def test_active_immediately_after_proposal(self):
        p = ActiveProject()
        p.mark_proposed(0.0)
        self.assertTrue(p.is_active(1.0))

    def test_unconfirmed_proposal_expires_after_timeout(self):
        p = ActiveProject(confirm_timeout=60.0)
        p.mark_proposed(0.0)
        self.assertTrue(p.is_active(59.0))
        self.assertFalse(p.is_active(61.0))

    def test_confirmed_proposal_survives_past_timeout(self):
        p = ActiveProject(confirm_timeout=60.0)
        p.mark_proposed(0.0)
        p.confirm()
        self.assertTrue(p.is_active(1000.0))

    def test_finish_clears_active_state(self):
        p = ActiveProject()
        p.mark_proposed(0.0)
        p.confirm()
        p.on_project_finished()
        self.assertFalse(p.is_active(1.0))


class RecentCandidatesTest(unittest.TestCase):
    def test_recent_subjects_respects_limit_and_order(self):
        r = RecentCandidates(maxlen=10)
        r.add("s1", "d1")
        r.add("s2", "d2")
        self.assertEqual(r.recent_subjects(1), ["s2"])
        self.assertEqual(r.recent_subjects(10), ["s1", "s2"])

    def test_ring_evicts_oldest_past_maxlen(self):
        r = RecentCandidates(maxlen=2)
        r.add("s1", "d1")
        r.add("s2", "d2")
        r.add("s3", "d3")
        self.assertEqual(r.recent_subjects(10), ["s2", "s3"])

    def test_similar_detects_near_duplicate_descriptions(self):
        r = RecentCandidates()
        r.add("s1", "tighten the retry loop timeout handling")
        self.assertTrue(r.similar("tighten the retry loop timeout handler"))

    def test_similar_false_for_unrelated_description(self):
        r = RecentCandidates()
        r.add("s1", "tighten the retry loop timeout handling")
        self.assertFalse(r.similar("rewrite the RSS parser entirely"))


if __name__ == "__main__":
    unittest.main()
