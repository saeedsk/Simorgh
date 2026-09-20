"""Stage 8 items 3-4: find what keeps going wrong by counting, and keep
what was decided about it with the evidence and the measurement."""

from __future__ import annotations

import unittest

from simorgh.growth.diagnose import Failure, cluster, phrasing_prompt
from simorgh.growth.policies import PolicyStore


def _fail(i, task_type, **kw):
    return Failure(task_id=f"t{i}", task_type=task_type, **kw)


class Clustering(unittest.TestCase):
    """A fixture of thirty failures with two planted clusters in it."""

    def setUp(self):
        self.failures = (
            [_fail(i, "patch", failed_check="tests_pass", reason="left the suite red") for i in range(6)]
            + [_fail(100 + i, "research", denied_tool="web_fetch", reason="refused: no network") for i in range(4)]
            + [_fail(200 + i, "patch", reason="ran out of steps") for i in range(12)]
            + [_fail(300 + i, "skill", reason=f"something one-off {i}") for i in range(8)]
        )

    def test_it_finds_the_planted_clusters_and_no_others(self):
        found = cluster(self.failures)
        self.assertEqual(len(found), 2)
        self.assertEqual({c.key[1] or c.key[2] for c in found}, {"tests_pass", "web_fetch"})
        self.assertEqual(len(found[0].members), 6, "biggest first")

    def test_a_cause_nobody_recorded_is_not_a_pattern(self):
        for found in cluster(self.failures):
            self.assertTrue(found.key[1] or found.key[2] or found.key[3])

    def test_two_of_a_kind_is_not_a_cluster(self):
        pair = [_fail(i, "patch", failed_check="lint") for i in range(2)]
        self.assertEqual(cluster(pair), [])

    def test_a_failure_mode_every_type_has_is_not_about_this_type(self):
        everywhere = ([_fail(i, "patch", denied_tool="run_shell") for i in range(3)]
                      + [_fail(100 + i, "research", denied_tool="run_shell") for i in range(3)]
                      + [_fail(200 + i, "skill", denied_tool="run_shell") for i in range(3)])
        # Each type's share equals the baseline elsewhere, so nothing here
        # is a lesson about a particular kind of work.
        self.assertEqual(cluster(everywhere), [])

    def test_the_model_is_only_asked_to_phrase_it(self):
        prompt = phrasing_prompt(cluster(self.failures)[0])
        self.assertIn("Write the one sentence of advice", prompt)
        self.assertIn("tests_pass", prompt)
        self.assertIn("nothing you cannot see below", prompt)


class Policies(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.now = 1_790_000_000.0
        self.store = PolicyStore(clock=lambda: self.now)

    async def _proposed(self, body="run the failing test alone first"):
        return await self.store.propose(kind="rule", task_type="patch", body=body,
                                        evidence_refs=("task:1", "task:2"))

    async def test_adoption_needs_a_measurement_and_a_case_it_fixed(self):
        regressed = await self.store.adopt((await self._proposed("a")).id, baseline=0.6, result=0.5,
                                           evaluated_on=10, fixed_a_motivating_case=True)
        self.assertEqual(regressed.status, "refused")
        self.assertIn("regressed", regressed.why)

        no_case = await self.store.adopt((await self._proposed("b")).id, baseline=0.6, result=0.9,
                                         evaluated_on=10, fixed_a_motivating_case=False)
        self.assertEqual(no_case.status, "refused")
        self.assertIn("fixed none", no_case.why)

        unmeasured = await self.store.adopt((await self._proposed("c")).id, baseline=0.6, result=0.9,
                                            evaluated_on=0, fixed_a_motivating_case=True)
        self.assertEqual(unmeasured.status, "refused")

        good = await self.store.adopt((await self._proposed("d")).id, baseline=0.6, result=0.8,
                                      evaluated_on=12, fixed_a_motivating_case=True)
        self.assertEqual(good.status, "adopted")
        self.assertEqual([p.body for p in self.store.live_for("patch")], ["d"])

    async def test_a_policy_is_retired_not_deleted(self):
        policy = await self._proposed()
        await self.store.adopt(policy.id, baseline=0.5, result=0.7, evaluated_on=9,
                               fixed_a_motivating_case=True)
        retired = await self.store.retire(policy.id, why="the type regressed")
        self.assertEqual(retired.status, "retired")
        self.assertEqual(self.store.live_for("patch"), [])
        self.assertEqual(len(self.store.all()), 1, "retiring is a status, not a deletion")

    async def test_a_policy_expires_with_its_measurement(self):
        policy = await self._proposed()
        await self.store.adopt(policy.id, baseline=0.5, result=0.7, evaluated_on=9,
                               fixed_a_motivating_case=True)
        self.assertEqual(await self.store.retire_expired(), [])
        self.now += 29 * 24 * 3600.0
        self.assertEqual([p.id for p in await self.store.retire_expired()], [policy.id])

    async def test_evidence_and_a_body_are_required(self):
        with self.assertRaises(ValueError):
            await self.store.propose(kind="rule", task_type="patch", body="   ")
        with self.assertRaises(ValueError):
            await self.store.propose(kind="wishful", task_type="patch", body="x")
        self.assertEqual((await self._proposed()).evidence_refs, ("task:1", "task:2"))


if __name__ == "__main__":
    unittest.main()
