"""Envelope invariants (docs/blueprint/03 section 2) -- one test per rule."""

import json
import unittest

from simorgh.contracts import ContractError, Event, Message, validate
from simorgh.contracts.envelope import canonical_json
from tests.simorgh.helpers import FakeClock, make_message


class TestMessageNew(unittest.TestCase):
    def test_new_fills_id_trace_ts_from_clock_and_catalog_version(self):
        clock = FakeClock(123.0)
        m = make_message("task.started", clock=clock)
        self.assertEqual(m.ts, 123.0)
        self.assertTrue(m.id and m.trace_id)
        self.assertEqual(m.schema_version, 1)
        self.assertEqual(m.priority, 5)

    def test_preempting_control_types_default_to_priority_9(self):
        for t in ("system.pause", "system.stop", "system.resume"):
            self.assertEqual(make_message(t).priority, 9)

    def test_unknown_type_is_rejected_at_construction(self):
        with self.assertRaises(ContractError):
            Message.new("nope.nothing", source="test", payload={})

    def test_reply_helper_correlates_and_keeps_trace_and_partition(self):
        req = make_message("task.claim", partition_key="task:t1")
        rep = req.reply("task.claim.reply", {"granted": True}, source="planning")
        validate(rep)
        self.assertEqual(rep.correlation_id, req.id)
        self.assertEqual(rep.causation_id, req.id)
        self.assertEqual(rep.trace_id, req.trace_id)
        self.assertEqual(rep.partition_key, "task:t1")

    def test_caused_keeps_trace_and_partition_by_default(self):
        parent = make_message("task.started", partition_key="task:t1")
        child = parent.caused("task.step", {"task_id": "t1", "step_no": 1, "phase": "act", "summary": "s"},
                              source="orchestration@w1")
        validate(child)
        self.assertEqual(child.causation_id, parent.id)
        self.assertEqual(child.partition_key, "task:t1")


class TestValidateInvariants(unittest.TestCase):
    def test_valid_message_passes_and_is_returned(self):
        m = make_message("task.started")
        self.assertIs(validate(m), m)

    def test_payload_must_match_schema(self):
        m = make_message("task.started").with_(payload={"task_id": "t"})
        with self.assertRaises(ContractError) as ctx:
            validate(m)
        self.assertIn("worker_id", str(ctx.exception))

    def test_priority_out_of_range(self):
        with self.assertRaises(ContractError):
            validate(make_message("task.started").with_(priority=10))
        with self.assertRaises(ContractError):
            validate(make_message("task.started").with_(priority=-1))

    def test_partition_key_form(self):
        with self.assertRaises(ContractError):
            validate(make_message("task.started").with_(partition_key="no-colon"))
        validate(make_message("task.started").with_(partition_key="task:abc-1"))

    def test_reply_requires_correlation_id(self):
        m = make_message("task.claim.reply").with_(correlation_id=None)
        with self.assertRaises(ContractError):
            validate(m)

    def test_preempting_message_must_not_set_partition_key(self):
        with self.assertRaises(ContractError):
            validate(make_message("system.pause").with_(partition_key="task:x"))
        with self.assertRaises(ContractError):
            validate(make_message("task.started").with_(priority=9, partition_key="task:x"))

    def test_schema_version_must_match_catalog(self):
        with self.assertRaises(ContractError):
            validate(make_message("task.started").with_(schema_version=2))

    def test_ttl_must_be_positive_when_set(self):
        with self.assertRaises(ContractError):
            validate(make_message("task.started").with_(ttl_seconds=0))

    def test_nan_in_payload_is_rejected(self):
        m = make_message("task.step").with_(payload={"task_id": "t", "step_no": 1, "phase": "act",
                                                     "summary": "s", "confidence": float("nan")})
        with self.assertRaises(ContractError):
            validate(m)

    def test_all_errors_are_reported_together(self):
        m = make_message("task.claim.reply").with_(correlation_id=None, priority=42, payload={})
        with self.assertRaises(ContractError) as ctx:
            validate(m)
        text = str(ctx.exception)
        self.assertIn("correlation_id", text)
        self.assertIn("priority", text)


class TestCanonicalJson(unittest.TestCase):
    def test_sorted_keys_compact_and_unicode(self):
        self.assertEqual(canonical_json({"b": 1, "a": "é"}), '{"a":"é","b":1}')

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            canonical_json({"x": float("nan")})

    def test_from_json_rejects_non_object_and_bad_json(self):
        with self.assertRaises(ContractError):
            Message.from_json("[1,2]")
        with self.assertRaises(ContractError):
            Message.from_json("{not json")

    def test_sha256_is_stable_for_equal_messages(self):
        m = make_message("task.started")
        again = Message.from_json(m.to_json())
        self.assertEqual(m.sha256(), again.sha256())


class TestEvent(unittest.TestCase):
    def test_from_message_strips_routing_and_keeps_causality(self):
        m = make_message("task.started", partition_key="task:t1", idempotency_key="k1")
        e = Event.from_message(m, stream="task:t1")
        self.assertEqual((e.stream, e.type, e.trace_id, e.causation_id, e.payload),
                         ("task:t1", m.type, m.trace_id, m.causation_id, m.payload))
        self.assertEqual(e.idempotency_key, "k1")
        self.assertEqual(e.seq, 0)

    def test_idempotency_key_defaults_to_message_id(self):
        m = make_message("task.started")
        self.assertEqual(Event.from_message(m, "s").idempotency_key, m.id)

    def test_event_round_trips_json(self):
        e = Event.from_message(make_message("task.started"), "s")
        self.assertEqual(Event.from_dict(json.loads(e.to_json())), e)


if __name__ == "__main__":
    unittest.main()
