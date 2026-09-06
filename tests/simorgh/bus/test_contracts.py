"""Contract tests (docs/blueprint/05 section 5): every type the bus
produces validates against the catalog; the bus's declared produces
refer to real types; publish rejects every invalid-envelope case from
03 section 2."""

import unittest

from simorgh.bus import Service
from simorgh.contracts import CATALOG, ContractError, get_spec, topics, validate
from simorgh.contracts.envelope import Message

from tests.simorgh.helpers import make_message

from .harness import Harness, run


class TestDeclaredTypes(unittest.TestCase):
    def test_produces_are_catalog_types(self):
        for t in Service.produces:
            self.assertIn(t, CATALOG)
            get_spec(t)


class TestPublishRejectsInvalidEnvelopes(unittest.TestCase):
    @run
    async def test_each_invariant(self):
        async with Harness("memory") as h:
            bus = h.client("planning")
            base = make_message(topics.TASK_STARTED, source="planning")
            cases = {
                "priority out of range": base.with_(priority=10),
                "bad partition form": base.with_(partition_key="no-colon"),
                "preempt with partition": make_message(topics.SYSTEM_PAUSE, source="planning").with_(partition_key="task:x"),
                "reply without correlation": make_message(topics.TASK_CLAIM_REPLY, source="planning").with_(correlation_id=None),
                "wrong schema version": base.with_(schema_version=99),
                "payload missing required": base.with_(payload={}),
                "ttl <= 0": base.with_(ttl_seconds=0),
                "nan in payload": base.with_(payload={**base.payload, "x": float("nan")}),
            }
            for name, bad in cases.items():
                with self.subTest(name):
                    with self.assertRaises(ContractError):
                        await bus.publish(bad)
            await bus.publish(base)  # the unmodified message is fine
            self.assertEqual(bus.metrics.counters["published"], 1)


if __name__ == "__main__":
    unittest.main()
