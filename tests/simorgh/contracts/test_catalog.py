"""Catalog completeness (docs/blueprint/03 section 8): every type in
`topics.py` has a dataclass and a schema, every dataclass round-trips
through canonical JSON, and every reserved-topology entry names a real
type."""

import json
import unittest

from simorgh.contracts import CATALOG, DOMAINS, Message, all_specs, get_spec, topics, validate
from simorgh.contracts.envelope import canonical_json
from simorgh.contracts.schemagen import SCHEMA_DIR
from tests.simorgh.helpers import example_payload, make_message


class TestCatalogCompleteness(unittest.TestCase):
    def test_every_topic_constant_has_a_registered_spec(self):
        self.assertEqual(sorted(CATALOG), sorted(all_specs()))

    def test_catalog_is_nonempty_and_unique(self):
        self.assertGreater(len(CATALOG), 100)
        self.assertEqual(len(CATALOG), len(set(CATALOG)))

    def test_every_type_belongs_to_a_declared_domain(self):
        for type_name in CATALOG:
            self.assertIn(topics.domain_of(type_name), DOMAINS, type_name)

    def test_every_domain_has_at_least_one_type(self):
        used = {topics.domain_of(t) for t in CATALOG}
        self.assertEqual(set(DOMAINS), used)

    def test_every_type_has_a_checked_in_schema_file(self):
        for type_name, spec in all_specs().items():
            path = SCHEMA_DIR / f"{type_name}.v{spec.version}.json"
            self.assertTrue(path.exists(), f"missing schema file for {type_name}")
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            self.assertEqual(loaded["title"], type_name)

    def test_every_request_has_a_reply_type(self):
        for type_name in CATALOG:
            if type_name.endswith(".request"):
                self.assertIn(topics.reply_type_for(type_name), CATALOG, type_name)

    def test_reserved_topology_names_real_types_and_subsystems(self):
        for table in (topics.SUBSCRIBE_ONLY_BY, topics.PUBLISH_ONLY_BY):
            for type_name, names in table.items():
                self.assertIn(type_name, CATALOG)
                for name in names:
                    self.assertIn(name, topics.SUBSYSTEMS + ("kernel",), name)
        for (type_name, publisher) in topics.PUBLISH_PAYLOAD_CONSTRAINTS:
            self.assertIn(type_name, CATALOG)
            self.assertIn(publisher, topics.SUBSYSTEMS)
        for type_name in topics.PREEMPTING_TYPES:
            self.assertIn(type_name, CATALOG)


class TestRoundTrips(unittest.TestCase):
    def test_every_dataclass_round_trips_required_fields(self):
        for type_name, spec in all_specs().items():
            with self.subTest(type=type_name):
                payload = example_payload(spec.fields)
                if spec.is_reply:
                    payload.pop("ok", None)
                    payload.pop("error", None)
                instance = spec.dataclass.from_payload(payload)
                self.assertEqual(instance.to_payload(), payload)
                spec.check(instance.to_payload())

    def test_every_dataclass_round_trips_with_optional_fields(self):
        for type_name, spec in all_specs().items():
            with self.subTest(type=type_name):
                payload = example_payload(spec.fields, include_optional=True)
                if spec.is_reply:
                    payload.pop("ok", None)
                    payload.pop("error", None)
                instance = spec.dataclass.from_payload(payload)
                self.assertEqual(instance.to_payload(), payload)
                spec.check(instance.to_payload())

    def test_every_message_round_trips_through_canonical_json(self):
        for type_name in CATALOG:
            with self.subTest(type=type_name):
                message = make_message(type_name, include_optional=True)
                validate(message)
                text = message.to_json()
                self.assertEqual(text, canonical_json(json.loads(text)))  # canonical is a fixed point
                self.assertEqual(Message.from_json(text), message)

    def test_optional_none_is_dropped_from_payload_but_accepted_on_the_wire(self):
        spec = get_spec("task.step")
        instance = spec.dataclass(task_id="t", step_no=1, phase="act", summary="s")
        self.assertNotIn("tool", instance.to_payload())
        spec.check({**instance.to_payload(), "tool": None})

    def test_unknown_payload_keys_are_ignored_by_from_payload_and_allowed_by_schema(self):
        spec = get_spec("task.started")
        instance = spec.dataclass.from_payload({"task_id": "t", "worker_id": "w", "future": 1})
        self.assertEqual(instance.task_id, "t")
        self.assertEqual(spec.validate({"task_id": "t", "worker_id": "w", "future": 1}), [])

    def test_missing_required_field_is_a_contract_error(self):
        from simorgh.contracts import ContractError

        spec = get_spec("task.started")
        with self.assertRaises(ContractError):
            spec.dataclass.from_payload({"task_id": "t"})
        self.assertTrue(spec.validate({"task_id": "t"}))

    def test_reply_types_accept_the_error_shape(self):
        for type_name, spec in all_specs().items():
            if not spec.is_reply:
                continue
            with self.subTest(type=type_name):
                self.assertEqual(spec.validate({"ok": False, "error": {"code": "c", "detail": "d", "retryable": True}}), [])
                self.assertTrue(spec.validate({"ok": False}))  # error body required with ok=false

    def test_dataclasses_are_frozen(self):
        instance = get_spec("task.started").dataclass(task_id="t", worker_id="w")
        with self.assertRaises(Exception):
            instance.task_id = "x"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
