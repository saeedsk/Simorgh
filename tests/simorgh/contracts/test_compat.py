import unittest

from simorgh.contracts import ContractError, compat
from tests.simorgh.helpers import make_message


class TestTranslators(unittest.TestCase):
    def setUp(self):
        compat.clear()

    def tearDown(self):
        compat.clear()

    def test_identity_when_already_at_version(self):
        m = make_message("task.started")
        self.assertIs(compat.translate(m, 1), m)

    def test_missing_translator_is_a_contract_error(self):
        with self.assertRaises(ContractError):
            compat.translate(make_message("task.started"), 2)

    def test_translators_chain_one_step_at_a_time(self):
        compat.register("task.started", 1, 2,
                        lambda p: {k: v for k, v in p.items() if k != "worker_id"} | {"worker": p["worker_id"]})
        compat.register("task.started", 2, 3, lambda p: {**p, "v3": True})
        m = make_message("task.started")
        out = compat.translate(m, 3)
        self.assertEqual(out.schema_version, 3)
        self.assertEqual(out.payload, {"task_id": "x", "worker": "x", "v3": True})
        self.assertEqual(m.schema_version, 1)  # original untouched

    def test_register_rejects_multi_step_jumps(self):
        with self.assertRaises(ContractError):
            compat.register("task.started", 1, 3, lambda p: p)


if __name__ == "__main__":
    unittest.main()
