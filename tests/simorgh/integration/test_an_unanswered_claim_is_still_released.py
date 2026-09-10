"""2fbfd68 released a Guardian claim that nobody answered -- and moved
the window rather than closing it.

The claim is marked answered on the line right after `pipeline.decide()`
returns, with the comment "every branch below publishes something".
Several things below it can raise BEFORE anything is published:

- the `decided` ledger append (the same Ledger whose failure the
  `received` append two lines up is explicitly guarded against),
- `_remember_rejection`, which appends to the rejected stream before the
  denial is published,
- `approval_question` / `tokens.issue`,
- the `bus.publish` call itself.

Any of those leaves `answered=True` on an action nobody was told about,
and the legitimate retry is then dropped as a duplicate -- which is
exactly the bug 2fbfd68 says it fixed, three lines further down.

Reproduced 2026-09-10 by failing only the `decided` append.
"""

from __future__ import annotations

import unittest
from unittest import mock

from simorgh.contracts import topics  # noqa: F401  (imported for parity with the sibling module)

from .test_guardian_decides_once_per_action import (
    GuardianDecidesOncePerActionTestCase, _proposal,
)


class AClaimIsOnlyAnsweredOnceSomethingIsPublishedTestCase(GuardianDecidesOncePerActionTestCase):
    async def _fail_only(self, guardian, event_type: str):
        """Make the ledger refuse one kind of event and no other."""
        real = guardian._ctx.ledger.append  # noqa: SLF001

        async def append(stream, event, *a, **kw):
            if getattr(event, "type", "") == event_type:
                raise RuntimeError(f"ledger refused the {event_type} event")
            return await real(stream, event, *a, **kw)

        return mock.patch.object(guardian._ctx.ledger, "append", new=append)  # noqa: SLF001

    async def test_a_failure_after_the_verdict_still_lets_the_retry_through(self):
        kernel = await self._boot()
        guardian = kernel._supervisor.services["guardian"].service  # noqa: SLF001

        broken = await self._fail_only(guardian, "decided")
        broken.start()
        await kernel.bus.publish(_proposal("decided-append-fails", args={"path": "README.md"}))
        await self._settle()
        broken.stop()
        answered = len(self.results) + len(self.denials)
        self.assertEqual(answered, 0, "premise: this first delivery answers nobody")
        self.denials.clear()
        self.results.clear()

        await kernel.bus.publish(_proposal("decided-append-fails", args={"path": "README.md"}))
        await self._settle()
        self.assertTrue(self.results or self.denials,
                        "an action nobody was told about must be answerable on retry")

    async def test_a_publish_that_fails_still_lets_the_retry_through(self):
        kernel = await self._boot()
        guardian = kernel._supervisor.services["guardian"].service  # noqa: SLF001
        real = guardian._ctx.bus.publish  # noqa: SLF001
        seen: list[str] = []

        async def publish(msg, *a, **kw):
            if msg.type in (topics.ACTION_APPROVED, topics.ACTION_DENIED) and not seen:
                seen.append(msg.type)
                raise RuntimeError("bus refused the verdict")
            return await real(msg, *a, **kw)

        broken = mock.patch.object(guardian._ctx.bus, "publish", new=publish)  # noqa: SLF001
        broken.start()
        await kernel.bus.publish(_proposal("publish-fails", args={"path": "README.md"}))
        await self._settle()
        broken.stop()
        self.assertTrue(seen, "premise: the verdict publish was the call that failed")

        # The bus is at-least-once and redelivers a proposal whose
        # handler raised, so the recovery here is the bus's own retry
        # rather than a second proposal -- but it only works because the
        # claim is no longer marked answered before the publish that
        # failed. `guardian._decided` must not be holding this id as
        # answered with nothing on the wire.
        await self._settle()
        self.assertTrue(self.results or self.denials,
                        "a verdict that never reached the bus answered nobody")

    async def test_the_claim_is_not_marked_answered_before_the_publish(self):
        """The invariant itself, read straight off the map: an id can be
        `answered` only once something was actually published."""
        kernel = await self._boot()
        guardian = kernel._supervisor.services["guardian"].service  # noqa: SLF001

        broken = await self._fail_only(guardian, "decided")
        broken.start()
        await kernel.bus.publish(_proposal("nothing-published", args={"path": "README.md"}))
        await self._settle()
        broken.stop()
        self.assertEqual(len(self.results) + len(self.denials), 0,
                         "premise: nothing was published for this action")
        claim = guardian._decided.get("nothing-published")  # noqa: SLF001
        self.assertTrue(claim is None or claim[1] is False,
                        "an action nobody was told about must not be recorded as answered")

    async def test_an_answered_action_is_still_never_answered_twice(self):
        """The guard this widens must not widen into the bug it closed."""
        kernel = await self._boot()
        args = {"path": "README.md"}
        await kernel.bus.publish(_proposal("still-once", args=args))
        await self._settle()
        first = len(self.results) + len(self.denials)
        self.assertTrue(first, "premise: the first delivery was answered")
        await kernel.bus.publish(_proposal("still-once", args=args))
        await self._settle()
        self.assertEqual(len(self.results) + len(self.denials), first)


if __name__ == "__main__":
    unittest.main()
