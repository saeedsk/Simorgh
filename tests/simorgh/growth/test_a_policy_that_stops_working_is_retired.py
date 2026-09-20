"""Stage 8 item 6: a policy is a claim, and claims are checked.

Adopting something because it measured well once is how a system
accumulates rules nobody can justify. So every live policy is watched
against the same measure that justified it -- the estimate part's
posterior for its task type -- and retired when its type has got worse
since, or when its TTL runs out.

Two things keep it from being trigger-happy, and both are the
interesting part:

- it judges a policy only on outcomes recorded AFTER the adoption,
  because comparing against all of history judges it on work that
  predates it;
- it needs enough of those outcomes, because a run of bad luck should
  not retire something that is working.
"""

import unittest

from simorgh.growth.policies import PolicyStore


class _Posteriors:
    """The estimate part, as far as `review` is concerned."""

    def __init__(self, table):
        self.table = table

    def __call__(self, task_type):
        return self.table[task_type]


async def _adopted(store, *, task_type="patch", baseline=0.7, samples_at_adoption=10):
    policy = await store.propose(kind="rule", task_type=task_type, body="run the suite first")
    return await store.adopt(policy.id, baseline=baseline, result=0.9, evaluated_on=6,
                             fixed_a_motivating_case=True, samples_at_adoption=samples_at_adoption)


class TheReview(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 1000.0
        self.store = PolicyStore(clock=lambda: self.now)

    async def test_a_type_that_got_worse_retires_its_policy(self):
        policy = await _adopted(self.store)
        gone = await self.store.review(_Posteriors({"patch": (0.4, 20)}))
        self.assertEqual([p.id for p in gone], [policy.id])
        self.assertEqual(self.store.all()[0].status, "retired")
        self.assertIn("0.40", gone[0].why)

    async def test_a_type_that_held_up_keeps_it(self):
        await _adopted(self.store)
        self.assertEqual(await self.store.review(_Posteriors({"patch": (0.8, 20)})), [])

    async def test_bad_luck_does_not_retire_a_working_policy(self):
        """Eleven samples where ten predate the adoption is one new
        outcome, and one outcome is not evidence of anything."""
        await _adopted(self.store, samples_at_adoption=10)
        self.assertEqual(await self.store.review(_Posteriors({"patch": (0.1, 11)})), [])

    async def test_it_judges_only_what_came_after(self):
        """The same posterior retires it once enough NEW outcomes exist
        -- the number that changed is the count since adoption, not the
        rate."""
        await _adopted(self.store, samples_at_adoption=10)
        self.assertEqual(await self.store.review(_Posteriors({"patch": (0.1, 14)})), [])
        gone = await self.store.review(_Posteriors({"patch": (0.1, 15)}))
        self.assertEqual(len(gone), 1)

    async def test_no_estimate_is_not_evidence_of_harm(self):
        await _adopted(self.store)

        def _raises(_task_type):
            raise LookupError("no competence table")

        self.assertEqual(await self.store.review(_raises), [])

    async def test_a_retired_policy_is_not_retired_twice(self):
        await _adopted(self.store)
        worse = _Posteriors({"patch": (0.4, 20)})
        self.assertEqual(len(await self.store.review(worse)), 1)
        self.assertEqual(await self.store.review(worse), [])

    async def test_a_proposal_is_not_reviewed(self):
        await self.store.propose(kind="rule", task_type="patch", body="b")
        self.assertEqual(await self.store.review(_Posteriors({"patch": (0.0, 99)})), [])

    async def test_a_ttl_still_retires_on_its_own(self):
        policy = await _adopted(self.store)
        self.now += policy.ttl_s + 1.0
        gone = await self.store.retire_expired()
        self.assertEqual([p.id for p in gone], [policy.id])


class TheSubsystemDoesItOnTheSleepTick(unittest.IsolatedAsyncioTestCase):
    """The review reads one part's numbers to judge another part's
    decision, which is the whole reason the three stopped being
    separate subsystems. It runs as the night's `review` step."""

    async def test_the_review_step_retires_what_has_stopped_working(self):
        from simorgh.growth.service import Service

        service = Service.__new__(Service)
        service.retired = 0
        service.policies = PolicyStore(clock=lambda: 1000.0)
        policy = await _adopted(service.policies)

        class _Table:
            @staticmethod
            def estimate(task_type, **_kw):
                return {"mean": 0.2, "samples": 40}

        service._parts = {"estimate": type("P", (), {"_competence": _Table()})()}  # noqa: SLF001
        await service._step_review()  # noqa: SLF001
        self.assertEqual(service.retired, 1)
        self.assertEqual(service.policies.all()[0].status, "retired")
        self.assertIsNotNone(policy)

    async def test_the_step_before_the_store_exists_does_nothing(self):
        from simorgh.growth.service import Service

        service = Service.__new__(Service)
        service.policies = None
        self.assertIn("no policy store", (await service._step_review())["detail"])  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
