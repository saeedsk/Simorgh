import json
import unittest
from dataclasses import replace

from .helpers import make_event
from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.contracts.registry import get_spec


class TestEventRoundTrip(unittest.TestCase):
    def test_to_json_from_dict_round_trip(self) -> None:
        event = replace(make_event("task:a", payload={"x": 1}, idempotency_key="k"), seq=3)

        again = Event.from_dict(json.loads(event.to_json()))

        self.assertEqual(again, event)

    def test_canonical_json_is_stable_regardless_of_field_insertion_order(self) -> None:
        a = Event(stream="s", type="t", ts=1.0, trace_id="tr", causation_id=None, payload={"b": 1, "a": 2})
        b = Event(stream="s", type="t", ts=1.0, trace_id="tr", causation_id=None, payload={"a": 2, "b": 1})

        self.assertEqual(a.to_json(), b.to_json())


class TestLedgerProducedMessagesValidate(unittest.TestCase):
    """The two message types the Ledger Service publishes (system.health,
    system.metrics) must accept exactly the payload shape service.py
    sends -- checked directly against the real catalog, not a copy of it.
    """

    def test_system_health_payload_validates(self) -> None:
        spec = get_spec(topics.SYSTEM_HEALTH)

        problems = spec.validate({"subsystem": "ledger", "status": "ok"})

        self.assertEqual(problems, [])

    def test_system_health_with_detail_validates(self) -> None:
        spec = get_spec(topics.SYSTEM_HEALTH)

        problems = spec.validate({"subsystem": "ledger", "status": "down", "detail": "ENOSPC"})

        self.assertEqual(problems, [])

    def test_system_metrics_payload_validates(self) -> None:
        spec = get_spec(topics.SYSTEM_METRICS)

        problems = spec.validate(
            {"subsystem": "ledger", "counters": {"appends": 1, "conflicts": 0}, "gauges": {"streams": 1}}
        )

        self.assertEqual(problems, [])

    def test_system_tick_sleep_requires_window_seconds(self) -> None:
        spec = get_spec(topics.SYSTEM_TICK_SLEEP)

        problems = spec.validate({})

        self.assertTrue(problems)


if __name__ == "__main__":
    unittest.main()
