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


class TestReplayRestoresPolicyNotJustTheName(unittest.IsolatedAsyncioTestCase):
    """Execution registers tools on boot layer 3; Orchestration only
    subscribes on layer 6, the last one -- so every `tool.registered`
    from boot lands on nobody, and `_replay_registrations` (service.py)
    is the only way Orchestration ever learns about it. It used to
    replay only `name` (`note_registered`), never `register_tool_policy`
    -- so a statically-configured MCP server or `[[execution.
    external_tools]]` entry kept whatever `reversibility`/`read_only` an
    operator wrote in `simorgh.toml` completely unapplied for the life
    of the process: `to_action_payload` fell back to the unregistered-
    tool default every single call. Live-caught, 2026-09-08, auditing
    `execution/external.py`: a real Kernel boot showed
    `orchestration.tools._TOOL_POLICY` had no entry at all for a
    freshly-registered external tool even after replay ran."""

    def tearDown(self):
        from simorgh.orchestration.tools import forget_registered
        forget_registered()

    async def test_replay_restores_reversibility_provider_and_marker_arg_key(self):
        import time as _time

        from simorgh.contracts.envelope import Event
        from simorgh.orchestration.service import Service, _TOOLS_STREAM
        from simorgh.orchestration.tools import _TOOL_POLICY

        events = [Event(
            stream=_TOOLS_STREAM, type="registered", ts=_time.time(), trace_id="", causation_id=None,
            payload={"name": "ddg_search_ext", "provider": "external", "reversibility": "read_only",
                     "read_only": True},
        )]

        class _Ledger:
            async def read(self, stream):
                assert stream == _TOOLS_STREAM
                return events

        class _Logger:
            def info(self, *a, **kw):
                pass

        class _Ctx:
            ledger = _Ledger()
            logger = _Logger()

        service = Service()
        await service._replay_registrations(_Ctx())

        self.assertEqual(_TOOL_POLICY.get("ddg_search_ext"), ("read_only", True))
        payload = to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": "ddg_search_ext", "args": {"argument": "amazon"}}, rationale="r",
        )
        self.assertEqual(payload["reversibility"], "read_only")
        self.assertEqual(payload["args"], {"input": "amazon"})

    async def test_an_old_shape_event_with_no_reversibility_field_still_notes_the_name(self):
        """Backward compatible with a ledger written before this fix:
        `{"name": ...}` alone must not crash replay, and still makes the
        tool nameable/offerable even though its policy stays unrestored."""
        import time as _time

        from simorgh.contracts.envelope import Event
        from simorgh.orchestration.service import Service, _TOOLS_STREAM
        from simorgh.orchestration.tools import _TOOL_POLICY, known_tools

        events = [Event(
            stream=_TOOLS_STREAM, type="registered", ts=_time.time(), trace_id="", causation_id=None,
            payload={"name": "legacy_tool"},
        )]

        class _Ledger:
            async def read(self, stream):
                return events

        class _Logger:
            def info(self, *a, **kw):
                pass

        class _Ctx:
            ledger = _Ledger()
            logger = _Logger()

        service = Service()
        await service._replay_registrations(_Ctx())

        self.assertIn("legacy_tool", known_tools())
        self.assertNotIn("legacy_tool", _TOOL_POLICY)


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

    def test_a_registration_never_takes_a_tool_away_from_a_profile(self):
        """This used to intersect the profile with what had registered,
        which was a trap primed to spring. The registered set is empty at
        boot -- Execution announces on layer 3, Orchestration subscribes
        on layer 6 -- and an `if not known` guard hid that by offering
        the whole profile anyway. The moment ANY single tool registered,
        one skill or one slow MCP server, the intersection would drop
        every builtin from every later session, leaving a patch session
        with no read_file (observer, 2026-09-08).

        A profile names the tools that session should have. Registration
        adds skills to it, and must never subtract."""
        from simorgh.orchestration.tools import note_registered, offered_tools
        note_registered("skill:word_count")
        self.assertEqual(
            offered_tools(("read_file", "run_shell")), ("read_file", "run_shell", "skill:word_count"))

    def test_one_registration_does_not_strip_the_builtins(self):
        from simorgh.orchestration.tools import note_registered, offered_tools
        note_registered("read_file")
        self.assertEqual(offered_tools(("read_file", "run_shell")), ("read_file", "run_shell"))


class TestJsonRestMarkers(unittest.TestCase):
    """A single-string marker can only carry one value, so a tool with
    real options had nowhere to put them. Live-caught 2026-09-09: the
    model wrote `SEARCH_LISTINGS: San Jose, CA 95120 for sale, price
    filter 1000000 to 4000000, single family` -- the whole sentence
    became `location`, the source matched nothing, two steps wasted."""

    def _payload(self, argument: str) -> dict:
        return to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": "search_listings", "args": {"argument": argument}}, rationale="r",
        )["args"]

    def test_a_json_second_part_becomes_real_arguments(self):
        args = self._payload('San Jose, CA 95120\n{"zip_code": "95120", "max_price": 2500000}')
        self.assertEqual(args["location"], "San Jose, CA 95120")
        self.assertEqual(args["zip_code"], "95120")
        self.assertEqual(args["max_price"], 2500000)

    def test_a_bare_one_line_marker_still_works(self):
        args = self._payload("San Jose, CA 95120")
        self.assertEqual(args["location"], "San Jose, CA 95120")
        self.assertEqual(set(args), {"location"})

    def test_a_non_json_second_part_is_kept_as_the_plain_string(self):
        # The tool's own schema then rejects it honestly, rather than
        # this layer silently dropping what the model wrote.
        args = self._payload("San Jose\nunder 2 million please")
        self.assertEqual(args["location"], "San Jose")
        self.assertEqual(args["filters"], "under 2 million please")

    def test_malformed_json_does_not_crash_the_router(self):
        args = self._payload('San Jose\n{"zip_code": ')
        self.assertEqual(args["location"], "San Jose")
        self.assertIn("filters", args)

    def test_the_tool_still_declares_read_only_network_policy(self):
        payload = to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": "search_listings", "args": {"argument": "San Jose"}}, rationale="r",
        )
        self.assertEqual(payload["reversibility"], "read_only")
        self.assertTrue(payload["scope"]["network"])


class TestEveryToolPolicyEntryIsARealTuple(unittest.TestCase):
    """`_TOOL_POLICY` is `dict[str, tuple[str, bool]]` -- a plain string
    value there is a bug in the table itself, not something any marker
    input can trigger. Live-caught 2026-09-09 (tools audit): a duplicate
    `"browse_page"` key in the dict literal, meant for a marker hint,
    silently overwrote the real `("reversible", True)` tuple with a hint
    STRING, so `to_action_payload` crashed unpacking it into two
    variables on every single `browse_page` call -- the tool had never
    once worked from the model's side."""

    def test_every_policy_value_is_a_two_tuple(self):
        from simorgh.orchestration.tools import _TOOL_POLICY

        for name, value in _TOOL_POLICY.items():
            self.assertIsInstance(value, tuple, f"{name}'s policy is {value!r}, not a tuple")
            self.assertEqual(len(value), 2, f"{name}'s policy is {value!r}, not a 2-tuple")
            reversibility, network = value
            self.assertIsInstance(reversibility, str)
            self.assertIsInstance(network, bool)

    def test_browse_page_does_not_crash_to_action_payload(self):
        payload = to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": "browse_page", "args": {"argument": "https://example.com\n[]"}},
            rationale="r",
        )
        self.assertEqual(payload["reversibility"], "reversible")
        self.assertTrue(payload["scope"]["network"])


class TestBrowsePageAndRunContainerJsonRest(unittest.TestCase):
    """Same defect class as `TestJsonRestMarkers` above, for the other
    two tools that document a JSON second part but were missing from
    `_MARKER_JSON_REST`. Live-caught 2026-09-09 (tools audit):
    `browse_page`'s documented JSON array of actions arrived at the tool
    as that array's string rendering, so `classify_actions` always
    answered "refused: actions must be a list"; `run_container`'s
    documented JSON object arrived as the literal text of `command`,
    which `shlex.split` then chopped into garbage tokens, and
    `network`/`input_files`/`timeout_s` were silently unreachable."""

    def test_browse_page_actions_arrive_as_a_real_list(self):
        payload = to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": "browse_page",
                  "args": {"argument": 'https://example.com\n[{"click": "#go"}, {"wait": "#results"}]'}},
            rationale="r",
        )
        args = payload["args"]
        self.assertEqual(args["target"], "https://example.com")
        self.assertEqual(args["actions"], [{"click": "#go"}, {"wait": "#results"}])

    def test_browse_page_bare_marker_still_works(self):
        payload = to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": "browse_page", "args": {"argument": "https://example.com"}},
            rationale="r",
        )
        self.assertEqual(payload["args"], {"target": "https://example.com"})

    def test_run_container_json_object_merges_into_args(self):
        payload = to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": "run_container",
                  "args": {"argument": 'python:3.12-slim\n{"command": ["python", "-c", "print(1)"], '
                                        '"network": false}'}},
            rationale="r",
        )
        args = payload["args"]
        self.assertEqual(args["image"], "python:3.12-slim")
        self.assertEqual(args["command"], ["python", "-c", "print(1)"])
        self.assertIs(args["network"], False)

    def test_run_container_bare_marker_still_works(self):
        payload = to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": "run_container", "args": {"argument": "python:3.12-slim\necho hi"}},
            rationale="r",
        )
        self.assertEqual(payload["args"], {"image": "python:3.12-slim", "command": "echo hi"})


class TestTheWriteScopeHintIsTrue(unittest.TestCase):
    """Live-caught 2026-09-09, the final acceptance trial: asked to
    write `docs/games/x.html`, Sim said "apply_source_patch only writes
    under src/ or simorgh/, so I'll use run_shell with a heredoc" and
    routed a perfectly legal write through the broadest tool it has.

    It was not guessing -- it was repeating this hint, which named
    `src/` (the retired v1 tree, deliberately NOT writable since
    2026-09-08) and omitted `docs/`, `tests/`, `tools/` and
    `simorgh_skills/`, all of which are. A prompt that misinforms is
    worse than a prompt that says nothing.
    """

    def test_the_hint_names_the_real_write_scopes(self):
        from simorgh.execution.config import Config
        from simorgh.orchestration.tools import marker_hint

        hint = marker_hint("apply_source_patch") or ""
        for scope in Config().write_scopes_source:
            self.assertIn(scope, hint, f"{scope} is writable but the hint does not say so")

    def test_the_hint_does_not_claim_src_is_writable(self):
        from simorgh.execution.config import Config
        from simorgh.orchestration.tools import marker_hint

        self.assertNotIn("src/", Config().write_scopes_source)
        hint = marker_hint("apply_source_patch") or ""
        self.assertIn("NOT src/", hint)


class TestNotifyMarkerReachesTheTool(unittest.TestCase):
    """`notify` is wired through the same one-string marker layer that
    silently swallowed five other tools' arguments (RUN_CONTAINER,
    SEARCH_LISTINGS, BROWSE_PAGE, INSTALL_PACKAGE, RUN_SCRIPT -- each
    unusable from the model's side for days). This walks the whole path
    -- reply text, parser, router -- so the same defect cannot land here
    unnoticed."""

    def _walk(self, reply: str) -> dict:
        from simorgh.cognition.parser import parse_marker

        name, argument = parse_marker(reply, ("NOTIFY",))
        return to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": name, "args": {"argument": argument}}, rationale="r",
        )

    def test_the_subject_splits_off_and_the_body_keeps_every_line(self):
        payload = self._walk(
            "NOTIFY: benchmark regressed\nGAIA fell to 29%.\nWorth a look before the next run."
        )
        self.assertEqual(payload["tool"], "notify")
        self.assertEqual(payload["args"]["subject"], "benchmark regressed")
        self.assertEqual(
            payload["args"]["body"],
            "GAIA fell to 29%.\nWorth a look before the next run.",
            "a notification truncated to its first line is the useless message this tool exists to avoid",
        )

    def test_it_is_declared_irreversible_so_guardian_gates_every_message(self):
        payload = self._walk("NOTIFY: subject\nbody")
        self.assertEqual(payload["reversibility"], "irreversible")


class TestKnowledgeMarkersReachTheTools(unittest.TestCase):
    """The `kb_*` tools go through the same one-string marker layer that
    silently swallowed five other tools' arguments (RUN_CONTAINER,
    SEARCH_LISTINGS, BROWSE_PAGE, INSTALL_PACKAGE, RUN_SCRIPT -- each
    unusable from the model's side for days). This walks the whole path
    for each of them: reply text, parser, router, argument names."""

    MARKERS = ("KB_SEARCH", "KB_ASK", "KB_OPEN", "KB_SOURCES", "KB_STATUS")

    def _walk(self, reply: str) -> dict:
        from simorgh.cognition.parser import parse_marker

        name, argument = parse_marker(reply, self.MARKERS)
        return to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": name, "args": {"argument": argument}}, rationale="r",
        )

    def test_a_search_arrives_as_a_query(self):
        payload = self._walk("KB_SEARCH: flood cover on the house policy")
        self.assertEqual(payload["tool"], "kb_search")
        self.assertEqual(payload["args"], {"query": "flood cover on the house policy"})

    def test_a_question_arrives_as_a_question(self):
        payload = self._walk("KB_ASK: what is my household excess?")
        self.assertEqual(payload["args"], {"question": "what is my household excess?"})

    def test_a_citation_arrives_as_a_citation(self):
        payload = self._walk("KB_OPEN: [a1b2c3d4e5f60000:3]")
        self.assertEqual(payload["args"], {"citation": "[a1b2c3d4e5f60000:3]"})

    def test_status_takes_no_arguments_rather_than_an_empty_string_one(self):
        payload = self._walk("KB_STATUS:")
        self.assertEqual(payload["tool"], "kb_status")
        self.assertEqual(payload["args"], {}, "a stray empty arg fails schema validation")

    def test_adding_a_source_splits_the_op_from_its_json(self):
        payload = self._walk(
            'KB_SOURCES: add\n{"path": "~/Documents", "privacy": "personal"}')
        self.assertEqual(payload["tool"], "kb_sources")
        self.assertEqual(payload["args"]["op"], "add")
        self.assertEqual(payload["args"]["path"], "~/Documents")
        self.assertEqual(payload["args"]["privacy"], "personal")

    def test_a_bare_op_with_no_json_still_routes(self):
        payload = self._walk("KB_SOURCES: scan")
        self.assertEqual(payload["args"]["op"], "scan")

    def test_the_reading_tools_are_read_only_so_a_plan_session_may_use_them(self):
        for marker, tool in (("KB_SEARCH: x", "kb_search"), ("KB_ASK: x", "kb_ask"),
                             ("KB_OPEN: x", "kb_open"), ("KB_STATUS:", "kb_status")):
            with self.subTest(tool=tool):
                payload = self._walk(marker)
                self.assertEqual(payload["reversibility"], "read_only")

    def test_managing_sources_is_reversible_not_read_only(self):
        payload = self._walk("KB_SOURCES: scan")
        self.assertEqual(payload["reversibility"], "reversible")

    def test_none_of_them_claims_to_use_the_network(self):
        """The whole point of the domain is that the documents never
        leave the machine; a tool declaring `network` would be gated as
        though they might."""
        for marker in ("KB_SEARCH: x", "KB_ASK: x", "KB_OPEN: x", "KB_STATUS:", "KB_SOURCES: scan"):
            with self.subTest(marker=marker):
                self.assertFalse(self._walk(marker)["scope"]["network"])

    def test_every_kb_tool_has_a_policy_row_and_a_timeout_and_a_note(self):
        """The missing `_TOOL_POLICY` row is how `browse_page` crashed;
        a missing timeout is the stale-5-second bug; a missing note
        means the model is offered a tool it is never told about."""
        from simorgh.execution.config import Config
        from simorgh.execution.knowledge.tools import knowledge_tools
        from simorgh.orchestration import scaffolds
        from simorgh.orchestration.session import _ACTION_TIMEOUTS
        from simorgh.orchestration.tools import _TOOL_POLICY

        for tool in knowledge_tools(Config()):
            with self.subTest(tool=tool.name):
                self.assertIn(tool.name, _TOOL_POLICY)
                self.assertIn(tool.name, _ACTION_TIMEOUTS)
                self.assertIn(tool.name, scaffolds._TOOL_NOTES)

    def test_the_declared_policy_matches_what_the_tool_says_about_itself(self):
        from simorgh.execution.config import Config
        from simorgh.execution.knowledge.tools import knowledge_tools
        from simorgh.orchestration.tools import _TOOL_POLICY

        for tool in knowledge_tools(Config()):
            with self.subTest(tool=tool.name):
                self.assertEqual(_TOOL_POLICY[tool.name][0], tool.reversibility)


class TestPimMarkersReachTheTools(unittest.TestCase):
    """Calendar, mail and reminders through the marker layer. `remind`
    is the one that matters most: it is two-part (when, then what), and
    a reminder whose text was truncated to its first line is the useless
    message this whole path exists to avoid."""

    MARKERS = ("CAL_LIST", "MAIL_SEARCH", "MAIL_READ", "REMIND")

    def _walk(self, reply: str) -> dict:
        from simorgh.cognition.parser import parse_marker

        name, argument = parse_marker(reply, self.MARKERS)
        return to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": name, "args": {"argument": argument}}, rationale="r",
        )

    def test_a_range_arrives_as_a_range(self):
        payload = self._walk("CAL_LIST: this week")
        self.assertEqual(payload["tool"], "cal_list")
        self.assertEqual(payload["args"], {"range": "this week"})

    def test_a_mail_query_arrives_as_a_query(self):
        self.assertEqual(self._walk("MAIL_SEARCH: invoice from the plumber")["args"],
                         {"query": "invoice from the plumber"})

    def test_a_message_reference_arrives_intact(self):
        self.assertEqual(self._walk("MAIL_READ: [fastmail:INBOX:4471]")["args"],
                         {"message": "[fastmail:INBOX:4471]"})

    def test_a_reminder_splits_the_time_from_the_text(self):
        payload = self._walk("REMIND: tomorrow 8am\ncall the plumber back about the boiler")
        self.assertEqual(payload["args"]["when"], "tomorrow 8am")
        self.assertEqual(payload["args"]["text"], "call the plumber back about the boiler")

    def test_a_multi_line_reminder_keeps_every_line(self):
        payload = self._walk("REMIND: 20m\ntake the bins out\nand the recycling")
        self.assertEqual(payload["args"]["text"], "take the bins out\nand the recycling")

    def test_reading_is_read_only_and_reminding_is_reversible(self):
        for marker, expected in (("CAL_LIST: today", "read_only"),
                                 ("MAIL_SEARCH: x", "read_only"),
                                 ("MAIL_READ: 1", "read_only"),
                                 ("REMIND: 20m\nx", "reversible")):
            with self.subTest(marker=marker):
                self.assertEqual(self._walk(marker)["reversibility"], expected)

    def test_a_reminder_does_not_claim_the_network(self):
        """It publishes to the Kernel's own scheduler and reaches
        nothing outside this machine."""
        self.assertFalse(self._walk("REMIND: 20m\nx")["scope"]["network"])

    def test_calendar_and_mail_do_claim_the_network(self):
        for marker in ("CAL_LIST: today", "MAIL_SEARCH: x", "MAIL_READ: 1"):
            with self.subTest(marker=marker):
                self.assertTrue(self._walk(marker)["scope"]["network"])

    def test_every_pim_tool_has_a_policy_row_a_timeout_and_a_note(self):
        from simorgh.execution.config import Config
        from simorgh.execution.pim.tools import pim_tools
        from simorgh.orchestration import scaffolds
        from simorgh.orchestration.session import _ACTION_TIMEOUTS
        from simorgh.orchestration.tools import _TOOL_POLICY

        for tool in pim_tools(Config()):
            with self.subTest(tool=tool.name):
                self.assertIn(tool.name, _TOOL_POLICY)
                self.assertIn(tool.name, _ACTION_TIMEOUTS)
                self.assertIn(tool.name, scaffolds._TOOL_NOTES)
                self.assertEqual(_TOOL_POLICY[tool.name][0], tool.reversibility)


class TestSecurityMarkersReachTheTools(unittest.TestCase):
    """The `sec_*` tools through the marker layer. `sec_self` and
    `sec_posture` take no arguments, which is its own trap: a stray
    empty-string argument fails schema validation and the tool is
    unusable from the model's side."""

    MARKERS = ("SEC_SELF", "SEC_POSTURE", "SEC_FINDINGS", "SEC_SHOW", "SEC_ACCEPT")

    def _walk(self, reply: str) -> dict:
        from simorgh.cognition.parser import parse_marker

        name, argument = parse_marker(reply, self.MARKERS)
        return to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": name, "args": {"argument": argument}}, rationale="r",
        )

    def test_the_argument_less_tools_send_no_arguments(self):
        for marker, tool in (("SEC_SELF:", "sec_self"), ("SEC_POSTURE:", "sec_posture")):
            with self.subTest(tool=tool):
                payload = self._walk(marker)
                self.assertEqual(payload["tool"], tool)
                self.assertEqual(payload["args"], {})

    def test_a_finding_id_arrives_as_a_finding(self):
        self.assertEqual(self._walk("SEC_SHOW: 3f9a1c2b")["args"], {"finding": "3f9a1c2b"})

    def test_accepting_splits_the_id_from_the_reason(self):
        payload = self._walk("SEC_ACCEPT: 3f9a1c2b\nthe box is only reachable over Tailscale")
        self.assertEqual(payload["args"]["finding"], "3f9a1c2b")
        self.assertEqual(payload["args"]["reason"], "the box is only reachable over Tailscale")

    def test_a_severity_filter_arrives_as_a_severity(self):
        payload = self._walk("SEC_FINDINGS: critical")
        self.assertEqual(payload["args"]["severity"], "critical")

    def test_a_severity_filter_with_json_options(self):
        payload = self._walk('SEC_FINDINGS: high\n{"status": "open"}')
        self.assertEqual(payload["args"]["severity"], "high")
        self.assertEqual(payload["args"]["status"], "open")

    def test_none_of_them_claims_the_network(self):
        """The domain is advisory and inspects this machine only. A
        tool declaring `network` would be gated as though it reached
        out, which is the opposite of what it does."""
        for marker in ("SEC_SELF:", "SEC_POSTURE:", "SEC_FINDINGS: high", "SEC_SHOW: a",
                       "SEC_ACCEPT: a\nreason"):
            with self.subTest(marker=marker):
                self.assertFalse(self._walk(marker)["scope"]["network"])

    def test_the_reading_tools_are_read_only_and_the_writing_ones_are_reversible(self):
        for marker, expected in (("SEC_POSTURE:", "read_only"), ("SEC_FINDINGS: high", "read_only"),
                                 ("SEC_SHOW: a", "read_only"), ("SEC_SELF:", "reversible"),
                                 ("SEC_ACCEPT: a\nr", "reversible")):
            with self.subTest(marker=marker):
                self.assertEqual(self._walk(marker)["reversibility"], expected)

    def test_every_security_tool_has_a_policy_row_a_timeout_and_a_note(self):
        from simorgh.execution.config import Config
        from simorgh.execution.security.tools import security_tools
        from simorgh.orchestration import scaffolds
        from simorgh.orchestration.session import _ACTION_TIMEOUTS
        from simorgh.orchestration.tools import _TOOL_POLICY

        for tool in security_tools(Config()):
            with self.subTest(tool=tool.name):
                self.assertIn(tool.name, _TOOL_POLICY)
                self.assertIn(tool.name, _ACTION_TIMEOUTS)
                self.assertIn(tool.name, scaffolds._TOOL_NOTES)
                self.assertEqual(_TOOL_POLICY[tool.name][0], tool.reversibility)


class TestEveryBuiltinToolIsFullyWired(unittest.TestCase):
    """The ten-step checklist, asserted for the whole registry rather
    than per domain. Missing a step means the tool exists but the model
    cannot call it, or calls it with the wrong argument key, or is never
    told it is there -- each of which has actually happened here."""

    def test_every_registered_tool_has_a_policy_row_and_a_note(self):
        """A missing `_TOOL_POLICY` row is how `browse_page` crashed; a
        missing note means the model is offered a tool it is never told
        about. `_ACTION_TIMEOUTS` is deliberately sparse -- the fast
        local tools (read_file, search_code, the git ones) share the
        session default, and only the ones that can genuinely take
        minutes are listed."""
        from simorgh.execution.config import Config
        from simorgh.execution.tools import builtin_tools
        from simorgh.orchestration import scaffolds
        from simorgh.orchestration.tools import _TOOL_POLICY

        for tool in builtin_tools(Config()):
            with self.subTest(tool=tool.name):
                self.assertIn(tool.name, _TOOL_POLICY, "no _TOOL_POLICY row -- Guardian would "
                                                        "treat it as irreversible")
                self.assertIn(tool.name, scaffolds._TOOL_NOTES, "no note -- the model is never "
                                                                 "told what it does")

    def test_the_declared_policy_matches_what_each_tool_says_about_itself(self):
        """Two sources of truth for reversibility, and Guardian trusts
        the table. A tool that calls itself read_only while the table
        calls it irreversible is gated wrongly in one direction or the
        other."""
        from simorgh.execution.config import Config
        from simorgh.execution.tools import builtin_tools
        from simorgh.orchestration.tools import _TOOL_POLICY

        for tool in builtin_tools(Config()):
            if tool.name not in _TOOL_POLICY:
                continue
            with self.subTest(tool=tool.name):
                self.assertEqual(_TOOL_POLICY[tool.name][0], tool.reversibility)

    def test_every_offered_tool_in_every_profile_actually_exists(self):
        """A profile offering a tool that is not registered wastes a
        step: the model calls it and is refused."""
        from simorgh.execution.config import Config
        from simorgh.execution.tools import builtin_tools
        from simorgh.orchestration.profiles import BY_KIND

        registered = {tool.name for tool in builtin_tools(Config(shell=True, remote=True))}
        for kind, profile in BY_KIND.items():
            for name in profile.tools:
                with self.subTest(profile=kind, tool=name):
                    self.assertIn(name, registered)

    def test_a_read_only_profile_offers_only_read_only_tools(self):
        from simorgh.orchestration.profiles import PLAN
        from simorgh.orchestration.tools import _TOOL_POLICY

        for name in PLAN.tools:
            with self.subTest(tool=name):
                self.assertEqual(_TOOL_POLICY.get(name, ("irreversible",))[0], "read_only")


class TestHomeMarkersReachTheTools(unittest.TestCase):
    """The house through the marker layer, and the one thing here that
    no other tool does: `home_call`'s reversibility is computed from its
    ARGUMENTS. "turn a light on" and "unlock the front door" travel
    through the same tool, and only the arguments say which."""

    MARKERS = ("HOME_FIND", "HOME_STATE", "HOME_DESCRIBE", "HOME_CALL", "HOME_UNDO")

    def _walk(self, reply: str) -> dict:
        from simorgh.cognition.parser import parse_marker

        name, argument = parse_marker(reply, self.MARKERS)
        return to_action_payload(
            action_id="a1", task_id="t1",
            call={"tool": name, "args": {"argument": argument}}, rationale="r",
        )

    def test_a_find_arrives_as_a_query(self):
        self.assertEqual(self._walk("HOME_FIND: kitchen")["args"], {"query": "kitchen"})

    def test_a_state_arrives_as_a_target(self):
        self.assertEqual(self._walk("HOME_STATE: climate.hallway")["args"],
                         {"target": "climate.hallway"})

    def test_a_call_splits_the_service_from_its_json(self):
        payload = self._walk(
            'HOME_CALL: light.turn_on\n{"target": "kitchen lights", "data": {"brightness_pct": 40}}')
        self.assertEqual(payload["tool"], "home_call")
        self.assertEqual(payload["args"]["service"], "light.turn_on")
        self.assertEqual(payload["args"]["target"], "kitchen lights")
        self.assertEqual(payload["args"]["data"], {"brightness_pct": 40})

    def test_turning_a_light_on_is_reversible(self):
        payload = self._walk('HOME_CALL: light.turn_on\n{"target": "kitchen lights"}')
        self.assertEqual(payload["reversibility"], "reversible")

    def test_unlocking_a_door_is_escalated_by_the_same_tool(self):
        payload = self._walk('HOME_CALL: lock.unlock\n{"target": "front door"}')
        self.assertEqual(payload["reversibility"], "irreversible",
                         "Guardian escalates on this label")

    def test_disarming_the_alarm_is_escalated(self):
        payload = self._walk('HOME_CALL: alarm_control_panel.alarm_disarm\n{"target": "house"}')
        self.assertEqual(payload["reversibility"], "irreversible")

    def test_a_thermostat_outside_the_hard_limits_is_escalated(self):
        payload = self._walk(
            'HOME_CALL: climate.set_temperature\n'
            '{"target": "thermostat", "data": {"temperature": 40}}')
        self.assertEqual(payload["reversibility"], "irreversible")

    def test_a_thermostat_inside_the_hard_limits_is_not(self):
        payload = self._walk(
            'HOME_CALL: climate.set_temperature\n'
            '{"target": "thermostat", "data": {"temperature": 20}}')
        self.assertEqual(payload["reversibility"], "reversible")

    def test_the_reading_tools_are_read_only(self):
        for marker in ("HOME_FIND: x", "HOME_STATE: x", "HOME_DESCRIBE:"):
            with self.subTest(marker=marker):
                self.assertEqual(self._walk(marker)["reversibility"], "read_only")

    def test_every_home_tool_has_a_policy_row_and_a_note(self):
        from simorgh.execution.config import Config
        from simorgh.execution.home.tools import home_tools
        from simorgh.orchestration import scaffolds
        from simorgh.orchestration.session import _ACTION_TIMEOUTS
        from simorgh.orchestration.tools import _TOOL_POLICY

        for tool in home_tools(Config()):
            with self.subTest(tool=tool.name):
                self.assertIn(tool.name, _TOOL_POLICY)
                self.assertIn(tool.name, _ACTION_TIMEOUTS)
                self.assertIn(tool.name, scaffolds._TOOL_NOTES)
