import unittest

from simorgh.orchestration.tools import to_action_payload


class TestToolCallRouter(unittest.TestCase):
    def test_read_file_is_tagged_read_only_with_path_scope(self):
        payload = to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": "read_file", "args": {"path": "src/x.py"}},
            rationale="gather context",
        )
        self.assertEqual(payload["reversibility"], "read_only")
        self.assertEqual(payload["scope"]["paths"], ["src/x.py"])
        self.assertFalse(payload["scope"]["network"])
        self.assertEqual(payload["proposed_by"], "orchestration")

    def test_web_fetch_is_tagged_network(self):
        payload = to_action_payload(
            action_id="a2", task_id="t1", call={"tool": "web_fetch", "args": {"url": "https://x"}}, rationale="r",
        )
        self.assertTrue(payload["scope"]["network"])
        self.assertEqual(payload["reversibility"], "read_only")

    def test_unknown_tool_defaults_to_irreversible(self):
        payload = to_action_payload(action_id="a3", task_id="t1", call={"tool": "delete_everything", "args": {}}, rationale="r")
        self.assertEqual(payload["reversibility"], "irreversible")

    def test_args_default_to_empty_dict_when_not_a_mapping(self):
        payload = to_action_payload(action_id="a4", task_id="t1", call={"tool": "read_file"}, rationale="r")
        self.assertEqual(payload["args"], {})


if __name__ == "__main__":
    unittest.main()
