"""Stage 8 item 4: a behaviour change nobody can see is a behaviour
change nobody consented to.

The policy store already kept what Sim decided to do differently, in a
stream. A stream is where you look when you already suspect something;
it is not being told. So an adoption and a retirement go on the bus,
with the measurement that justified them, and the Interface prints one
line.

A proposal does not: it has changed nothing yet, and announcing every
one would train the household to ignore the adoptions. Same for a
refusal -- a policy that failed its measurement is in the stream for
whoever looks.
"""

import unittest

from simorgh.contracts import topics
from simorgh.growth.policies import PolicyStore


class _Seen:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def __call__(self, topic: str, payload: dict) -> None:
        self.calls.append((topic, payload))

    def topics(self) -> list[str]:
        return [t for t, _p in self.calls]


class WhatIsAnnounced(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.seen = _Seen()
        self.store = PolicyStore(clock=lambda: 1000.0, publish=self.seen)

    async def test_an_adoption_carries_its_measurement(self):
        policy = await self.store.propose(kind="rule", task_type="patch",
                                          body="run the whole suite before committing")
        await self.store.adopt(policy.id, baseline=0.5, result=0.8, evaluated_on=6,
                               fixed_a_motivating_case=True)
        adopted = [p for t, p in self.seen.calls if t == topics.GROWTH_POLICY_ADOPTED]
        self.assertEqual(len(adopted), 1)
        self.assertEqual((adopted[0]["baseline"], adopted[0]["result"], adopted[0]["evaluated_on"]),
                         (0.5, 0.8, 6))
        self.assertEqual(adopted[0]["task_type"], "patch")

    async def test_a_retirement_says_why(self):
        policy = await self.store.propose(kind="rule", task_type="patch", body="b")
        await self.store.adopt(policy.id, baseline=0.5, result=0.9, evaluated_on=5,
                               fixed_a_motivating_case=True)
        await self.store.retire(policy.id, why="the task type got worse")
        retired = [p for t, p in self.seen.calls if t == topics.GROWTH_POLICY_RETIRED]
        self.assertEqual(len(retired), 1)
        self.assertEqual(retired[0]["reason"], "the task type got worse")

    async def test_a_refusal_is_not_announced(self):
        """It changed nothing, and a household that hears about every
        rejected idea stops listening for the accepted ones."""
        policy = await self.store.propose(kind="rule", task_type="patch", body="b")
        await self.store.adopt(policy.id, baseline=0.8, result=0.5, evaluated_on=5,
                               fixed_a_motivating_case=True)
        self.assertNotIn(topics.GROWTH_POLICY_ADOPTED, self.seen.topics())

    async def test_a_store_with_nowhere_to_publish_still_works(self):
        quiet = PolicyStore(clock=lambda: 1000.0)
        policy = await quiet.propose(kind="rule", task_type="patch", body="b")
        self.assertEqual(policy.status, "proposed")


class TheInterfaceSaysIt(unittest.IsolatedAsyncioTestCase):
    """The household hears it in the words Sim would use, not as a
    payload."""

    def _service(self):
        from simorgh.interface.service import Service

        service = Service.__new__(Service)
        service._out = self.printed.append  # noqa: SLF001
        service._color = False  # noqa: SLF001
        return service

    def setUp(self):
        self.printed: list[str] = []

    async def test_an_adoption_reads_as_a_change_with_its_numbers(self):
        from simorgh.contracts.envelope import Message

        await self._service()._on_policy_changed(Message.new(  # noqa: SLF001
            topics.GROWTH_POLICY_ADOPTED, source="growth",
            payload={"policy_id": "p1", "kind": "rule", "task_type": "patch",
                     "body": "run the whole suite before committing",
                     "baseline": 0.5, "result": 0.8, "evaluated_on": 6}))
        line = "".join(self.printed)
        self.assertIn("run the whole suite before committing", line)
        self.assertIn("80%", line)
        self.assertIn("50%", line)
        self.assertIn("patch", line)

    async def test_a_retirement_reads_as_a_stop(self):
        from simorgh.contracts.envelope import Message

        await self._service()._on_policy_changed(Message.new(  # noqa: SLF001
            topics.GROWTH_POLICY_RETIRED, source="growth",
            payload={"policy_id": "p1", "kind": "rule", "task_type": "patch", "body": "a rule",
                     "reason": "it ran out"}))
        line = "".join(self.printed)
        self.assertIn("stopped", line)
        self.assertIn("it ran out", line)

    async def test_a_policy_with_no_body_prints_nothing(self):
        from simorgh.contracts.envelope import Message

        await self._service()._on_policy_changed(Message.new(  # noqa: SLF001
            topics.GROWTH_POLICY_ADOPTED, source="growth",
            payload={"policy_id": "p1", "kind": "rule", "task_type": "", "body": ""}))
        self.assertEqual(self.printed, [])


if __name__ == "__main__":
    unittest.main()
