"""Stage 1 item 8: a subsystem's ledger writes only its own streams."""

import unittest

from simorgh.contracts.envelope import Event
from simorgh.contracts.streamnames import WRITERS, writers_for
from simorgh.ledger.bound import BoundLedger, WriterViolation
from simorgh.ledger.factory import make_ledger


def _event(stream):
    return Event(stream=stream, type="x", ts=1.0, trace_id="t", causation_id=None, payload={})


class ALedgerIsBoundToItsWriter(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.inner = make_ledger({"backend": "memory"})
        await self.inner.start()

    async def test_reflection_may_not_write_the_self_model(self):
        with self.assertRaises(WriterViolation):
            await BoundLedger(self.inner, "reflection").append("self:model", _event("self:model"))
        self.assertEqual(await self.inner.read("self:model"), [])

    async def test_the_owner_and_the_shared_writers_may(self):
        await BoundLedger(self.inner, "worldmodel").append("self:model", _event("self:model"))
        await BoundLedger(self.inner, "orchestration").append("task:t1", _event("task:t1"))
        await BoundLedger(self.inner, "planning@w1").append("task:t1", _event("task:t1"))
        self.assertEqual(len(await self.inner.read("task:t1")), 2)

    async def test_reads_pass_through_and_unlisted_streams_are_open(self):
        bound = BoundLedger(self.inner, "interface")
        await bound.append("scratch:notes", _event("scratch:notes"))
        self.assertEqual(len(await bound.read("scratch:notes")), 1)

    def test_the_longest_prefix_decides(self):
        self.assertEqual(writers_for("reflection:alerts"), frozenset({"reflection"}))
        self.assertEqual(writers_for("reflect:drift:x"), frozenset({"reflection"}))
        self.assertIsNone(writers_for("somethingelse"))
        self.assertTrue(all(isinstance(v, frozenset) and v for v in WRITERS.values()))
