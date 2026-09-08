import unittest

from simorgh.orchestration.tools import marker_hint, register_tool_policy, to_action_payload


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

    def test_the_wired_mcp_example_tool_is_read_only_network_and_remapped(self):
        payload = to_action_payload(
            action_id="a8", task_id="t1",
            call={"tool": "mcp_ddg_search_ddg_search", "args": {"argument": "amazon stock price"}},
            rationale="r",
        )
        self.assertEqual(payload["reversibility"], "read_only")
        self.assertTrue(payload["scope"]["network"])
        self.assertEqual(payload["args"], {"query": "amazon stock price"})

    def test_already_correctly_keyed_args_are_left_alone(self):
        payload = to_action_payload(
            action_id="a7", task_id="t1",
            call={"tool": "web_fetch", "args": {"url": "https://example.com"}}, rationale="r",
        )
        self.assertEqual(payload["args"], {"url": "https://example.com"})

    def test_marker_hint_exists_for_propose_mcp_server(self):
        hint = marker_hint("propose_mcp_server")
        self.assertIsNotNone(hint)
        self.assertIn("command", hint)
        self.assertIn("reason", hint)

    def test_marker_hint_is_none_for_a_tool_with_a_self_explanatory_argument(self):
        self.assertIsNone(marker_hint("web_fetch"))
        self.assertIsNone(marker_hint("list_dir"))

    def test_marker_hint_is_none_for_an_unknown_tool(self):
        self.assertIsNone(marker_hint("not_a_real_tool"))

    def test_a_two_field_tool_splits_the_marker_payload_at_its_first_line(self):
        """apply_source_patch/apply_skill/git_commit are model-callable
        now (profiles.py, 2026-09-07); the one-string marker layer carries
        both fields as first-line + rest."""
        payload = to_action_payload(
            action_id="a9", task_id="t1",
            call={"tool": "apply_source_patch", "args": {"argument": "simorgh/foo.py\ndef f():\n    return 1\n"}},
            rationale="r",
        )
        self.assertEqual(payload["args"], {"subject": "simorgh/foo.py", "code": "def f():\n    return 1\n"})
        self.assertEqual(payload["reversibility"], "reversible")
        commit = to_action_payload(
            action_id="a10", task_id="t1",
            call={"tool": "git_commit", "args": {"argument": "simorgh/foo.py\nadd f"}}, rationale="r",
        )
        self.assertEqual(commit["args"], {"path": "simorgh/foo.py", "message": "add f"})

    def test_a_no_argument_tool_gets_empty_args_from_a_bare_marker(self):
        payload = to_action_payload(
            action_id="a11", task_id="t1", call={"tool": "git_revert", "args": {"argument": ""}}, rationale="r",
        )
        self.assertEqual(payload["args"], {})
        self.assertEqual(payload["reversibility"], "reversible")

    def test_an_announced_external_tool_becomes_routable_with_an_input_key(self):
        register_tool_policy("ddg_search_ext", reversibility="read_only", provider="external")
        payload = to_action_payload(
            action_id="a12", task_id="t1",
            call={"tool": "ddg_search_ext", "args": {"argument": "amazon stock"}}, rationale="r",
        )
        self.assertEqual(payload["args"], {"input": "amazon stock"})
        self.assertEqual(payload["reversibility"], "read_only")
        self.assertTrue(payload["scope"]["network"])

    def test_a_hand_written_policy_wins_over_a_later_announcement(self):
        register_tool_policy("read_file", reversibility="irreversible", provider="mcp")
        payload = to_action_payload(
            action_id="a13", task_id="t1", call={"tool": "read_file", "args": {"path": "docs/x"}}, rationale="r",
        )
        self.assertEqual(payload["reversibility"], "read_only")
        self.assertFalse(payload["scope"]["network"])


if __name__ == "__main__":
    unittest.main()


class TestOfferedToolsFollowRealRegistrations(unittest.TestCase):
    """`offered_tools` filters a profile by what Execution announced --
    never by the policy table, which tests fill with made-up names."""

    def tearDown(self):
        from simorgh.orchestration.tools import forget_registered
        forget_registered()

    def test_nothing_announced_means_the_profile_as_written(self):
        from simorgh.orchestration.tools import offered_tools, register_tool_policy
        register_tool_policy("made_up", reversibility="read_only", provider="external")
        self.assertEqual(offered_tools(("read_file", "run_shell")), ("read_file", "run_shell"))

    def test_an_announced_set_filters_the_profile(self):
        from simorgh.orchestration.tools import note_registered, offered_tools
        note_registered("read_file")
        self.assertEqual(offered_tools(("read_file", "run_shell")), ("read_file",))
