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

    def test_a_marker_parsed_single_argument_is_remapped_onto_the_tools_real_key(self):
        """Live-caught: `cognition/parser.py::_parse_markers` only ever
        produces `{"argument": <str>}` -- passing that straight through to
        a tool whose `args_schema` requires `path`/`url`/`code` made every
        real marker-driven tool call fail with a bare `KeyError`."""
        cases = {
            "read_file": ("path", "docs/SOUL.md"),
            "list_dir": ("path", "simorgh"),
            "web_fetch": ("url", "https://example.com"),
            "run_python_sandboxed": ("code", "print(1)"),
            "draft_candidate": ("code", "def f(): return 1"),
        }
        for tool, (key, value) in cases.items():
            with self.subTest(tool=tool):
                payload = to_action_payload(
                    action_id="a5", task_id="t1",
                    call={"tool": tool, "args": {"argument": value}}, rationale="r",
                )
                self.assertEqual(payload["args"], {key: value})

    def test_a_marker_parsed_argument_for_an_unknown_tool_is_left_alone(self):
        payload = to_action_payload(
            action_id="a6", task_id="t1",
            call={"tool": "delete_everything", "args": {"argument": "x"}}, rationale="r",
        )
        self.assertEqual(payload["args"], {"argument": "x"})

    def test_already_correctly_keyed_args_are_left_alone(self):
        payload = to_action_payload(
            action_id="a7", task_id="t1",
            call={"tool": "web_fetch", "args": {"url": "https://example.com"}}, rationale="r",
        )
        self.assertEqual(payload["args"], {"url": "https://example.com"})


if __name__ == "__main__":
    unittest.main()
