"""`SharePolicy`'s pacing rules. `_share_times` grew forever: `decide()`
computed `recent` (the last hour's shares) to check the hourly cap but
never wrote it back, so a long-running process accumulated every share
timestamp for its whole lifetime. Live-caught and fixed by Sim itself,
2026-09-08, during an autonomous self-patch task."""

import unittest

from simorgh.persona.sharing import SharePolicy


class TestSharePolicy(unittest.TestCase):
    def test_share_times_older_than_an_hour_are_pruned_not_accumulated(self):
        policy = SharePolicy(max_per_hour=100)
        for i in range(50):
            policy.note_shared("news", now=float(i))
        # Far enough past every prior share that none is still "recent".
        policy.decide("news", now=100_000.0)
        self.assertEqual(policy._share_times, [])

    def test_the_hourly_cap_still_applies_to_genuinely_recent_shares(self):
        policy = SharePolicy(max_per_hour=2, news_cooldown_s=0.0)
        policy.note_shared("news", now=0.0)
        policy.note_shared("news", now=10.0)
        decision = policy.decide("news", now=20.0)
        self.assertFalse(decision.share)
        self.assertEqual(decision.reason, "hourly share cap reached")

    def test_an_old_share_no_longer_counts_toward_the_cap(self):
        policy = SharePolicy(max_per_hour=1, news_cooldown_s=0.0)
        policy.note_shared("news", now=0.0)
        # Well past the 3600s recency window.
        decision = policy.decide("news", now=10_000.0)
        self.assertTrue(decision.share)


if __name__ == "__main__":
    unittest.main()
