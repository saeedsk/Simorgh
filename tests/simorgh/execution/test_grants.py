"""Capabilities Sim grants itself (execution/grants.py).

This is the one 2026-09-09 change that widens what Sim can do to
itself, so most of what follows is the boundary rather than the
feature: a grant is always registered at the strictest Guardian tier,
never shadows a builtin, cannot be pointed at `os:system`, cannot turn
`npx <package>` into `npx -e <code>`, is capped per day, is written
somewhere a human can read, and can be taken back.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from simorgh.execution.config import Config
from simorgh.execution.grants import (
    Grant, GrantCapabilityTool, GrantStore, RevokeCapabilityTool,
    grant_id, tool_name_for, validate_external, validate_mcp,
)


def _ctx(task_id="t1"):
    from simorgh.contracts.protocols import ToolContext

    return ToolContext(action_id="a1", task_id=task_id, scope={}, constraints={},
                       data_dir=Path.cwd(), clock=None, logger=None, ledger=None)


def _clock(t=1_757_462_400.0):  # 2026-09-09T00:00:00Z
    return lambda: t


class _Registry:
    """Stands in for Execution's own register/unregister callbacks."""

    def __init__(self, taken=()):
        self.registered: list = []
        self.unregistered: list = []
        self.taken = set(taken)

    async def register(self, tool, *, provider=None, marker_arg_key=""):
        if tool.name in self.taken:
            return False
        self.taken.add(tool.name)
        self.registered.append((tool.name, provider, marker_arg_key, tool.reversibility))
        return True

    async def unregister(self, name, *, reason):
        self.unregistered.append((name, reason))
        return True

    async def start_mcp(self, server):
        names = [f"mcp_{server.name}_{t}" for t in (server.read_only_tools or ["run"])]
        self.registered.extend((n, "mcp", "", "irreversible") for n in names)
        return names


class ValidationTestCase(unittest.TestCase):
    def setUp(self):
        self.config = Config(repo_root=Path.cwd())

    def test_a_good_import_path_passes(self):
        self.assertIsNone(validate_external(
            {"import_path": "homeharvest:scrape_property"}, self.config))

    def test_the_module_denylist_refuses_handing_out_the_machine(self):
        for path in ("os:system", "subprocess:run", "shutil:rmtree", "socket:socket",
                     "builtins:eval", "importlib:import_module", "requests:get"):
            with self.subTest(path=path):
                refusal = validate_external({"import_path": path}, self.config)
                self.assertIsNotNone(refusal, f"{path} should be refused")
                self.assertIn("denylist", refusal)

    def test_a_submodule_of_a_denylisted_root_is_also_refused(self):
        # `os.path:join` is harmless; `os` as a root is the thing being
        # kept out, and letting a submodule through would make the
        # denylist decorative.
        self.assertIsNotNone(validate_external({"import_path": "os.path:join"}, self.config))

    def test_a_path_or_dunder_is_not_an_import_path(self):
        for path in ("/etc/passwd", "pkg:__import__", "pkg.mod", "pkg:mod:fn", "../x:y", ""):
            with self.subTest(path=path):
                self.assertIsNotNone(validate_external({"import_path": path}, self.config))

    def test_an_unknown_adapter_is_refused(self):
        self.assertIsNotNone(validate_external(
            {"import_path": "pkg:fn", "adapter": "magic"}, self.config))

    def test_a_good_mcp_spec_passes(self):
        self.assertIsNone(validate_mcp({
            "name": "time", "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-time"],
        }))

    def test_only_the_allowed_commands_may_launch_a_server(self):
        for command in ("bash", "sh", "curl", "rm", "/bin/sh"):
            with self.subTest(command=command):
                refusal = validate_mcp({"name": "x", "command": command, "args": ["y"]})
                self.assertIsNotNone(refusal)

    def test_an_eval_flag_turns_run_a_package_into_run_this_code(self):
        for args in (["-e", "require('child_process')"], ["--eval", "x"], ["-c", "import os"]):
            with self.subTest(args=args):
                refusal = validate_mcp({"name": "x", "command": "node", "args": args})
                self.assertIsNotNone(refusal)
                self.assertIn("run this code", refusal)

    def test_shell_metacharacters_are_refused(self):
        refusal = validate_mcp({"name": "x", "command": "npx", "args": ["-y", "pkg; rm -rf /"]})
        self.assertIsNotNone(refusal)

    def test_a_local_path_is_not_a_package(self):
        for arg in ("/tmp/evil.js", "./evil.js", "../evil.js"):
            with self.subTest(arg=arg):
                self.assertIsNotNone(validate_mcp({"name": "x", "command": "node", "args": [arg]}))

    def test_env_keys_must_look_like_environment_variables(self):
        self.assertIsNotNone(validate_mcp({
            "name": "x", "command": "npx", "args": ["-y", "pkg"], "env_keys": ["not a var"]}))


class NamingTestCase(unittest.TestCase):
    def test_every_granted_name_is_prefixed(self):
        self.assertTrue(tool_name_for({}, "homeharvest:scrape_property").startswith("x_"))
        self.assertEqual(tool_name_for({"name": "hh"}, "a:b"), "x_hh")

    def test_a_name_that_already_has_the_prefix_is_not_doubled(self):
        self.assertEqual(tool_name_for({"name": "x_hh"}, "a:b"), "x_hh")

    def test_a_grant_cannot_claim_a_builtin_name(self):
        # The prefix is the structural half of this; the registry
        # collision check is the other (see the tool tests below).
        self.assertNotEqual(tool_name_for({"name": "read_file"}, "a:b"), "read_file")


class GrantStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "grants.toml"
        self.addCleanup(self._tmp.cleanup)

    def _grant(self, **over):
        base = dict(id="g-1", kind="external", granted_at="2026-09-09T00:00:00+00:00",
                    name="x_hh", import_path="homeharvest:scrape_property", tools=("x_hh",))
        base.update(over)
        return Grant(**base)

    def test_a_grant_round_trips_through_the_file(self):
        store = GrantStore(self.path)
        store.append(self._grant())
        loaded = store.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].import_path, "homeharvest:scrape_property")
        self.assertEqual(loaded[0].tools, ("x_hh",))

    def test_a_missing_file_is_empty_not_an_error(self):
        self.assertEqual(GrantStore(self.path).load(), [])

    def test_a_malformed_file_is_empty_not_fatal(self):
        # One bad row must not stop the Kernel booting.
        self.path.write_text("this is not toml [[[")
        self.assertEqual(GrantStore(self.path).load(), [])

    def test_revoking_keeps_the_record_and_drops_it_from_active(self):
        store = GrantStore(self.path)
        store.append(self._grant())
        store.set_status("g-1", "revoked")
        self.assertEqual(len(store.load()), 1)
        self.assertEqual(store.active(), [])

    def test_a_hand_edited_file_cannot_invent_a_looser_tier(self):
        self.path.write_text(
            '[[grants]]\nid = "g-2"\nkind = "external"\ngranted_at = "x"\n'
            'import_path = "a:b"\nreversibility = "totally_safe"\n')
        self.assertEqual(GrantStore(self.path).load()[0].reversibility, "irreversible")

    def test_a_human_may_still_promote_by_hand(self):
        self.path.write_text(
            '[[grants]]\nid = "g-3"\nkind = "external"\ngranted_at = "x"\n'
            'import_path = "a:b"\nreversibility = "read_only"\n')
        self.assertEqual(GrantStore(self.path).load()[0].reversibility, "read_only")

    def test_quotes_in_a_reason_do_not_corrupt_the_file(self):
        store = GrantStore(self.path)
        store.append(self._grant(reason='he said "use this" \\ ok'))
        self.assertIn("use this", store.load()[0].reason)


class GrantCapabilityToolTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.store = GrantStore(self.root / "grants.toml")
        self.registry = _Registry()

    def _tool(self, **config):
        settings = {"repo_root": self.root}
        settings.update(config)
        return GrantCapabilityTool(
            Config(**settings), store=self.store, register=self.registry.register,
            start_mcp=self.registry.start_mcp, clock=_clock(), env={},
        )

    async def test_granting_a_real_callable_registers_and_records_it(self):
        result = await self._tool().run(
            {"kind": "external", "import_path": "json:dumps", "name": "dump",
             "reason": "structured output"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.registry.registered[0][0], "x_dump")
        grant = self.store.load()[0]
        self.assertEqual(grant.import_path, "json:dumps")
        self.assertEqual(grant.granted_by_task, "t1")
        self.assertEqual(grant.reason, "structured output")

    async def test_a_granted_tool_is_always_the_strictest_tier(self):
        """The load-bearing property. Guardian's ReversibilityRule gates
        every call to an irreversible tool; anything looser would let
        Sim hand itself an auto-approved capability."""
        await self._tool().run({"kind": "external", "import_path": "json:dumps"}, ctx=_ctx())
        self.assertEqual(self.registry.registered[0][3], "irreversible")
        self.assertEqual(self.store.load()[0].reversibility, "irreversible")

    async def test_a_grant_cannot_ask_for_a_looser_tier(self):
        # Not in args_schema, and ignored if sent anyway.
        await self._tool().run(
            {"kind": "external", "import_path": "json:dumps", "reversibility": "read_only"}, ctx=_ctx())
        self.assertEqual(self.store.load()[0].reversibility, "irreversible")

    async def test_a_denylisted_module_is_refused_and_records_nothing(self):
        result = await self._tool().run(
            {"kind": "external", "import_path": "os:system"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("denylist", result.error)
        self.assertEqual(self.store.load(), [])
        self.assertEqual(self.registry.registered, [])

    async def test_a_name_collision_refuses_rather_than_overwrites(self):
        self.registry.taken.add("x_dump")
        result = await self._tool().run(
            {"kind": "external", "import_path": "json:dumps", "name": "dump"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("already a registered tool", result.error)
        self.assertEqual(self.store.load(), [])

    async def test_an_import_that_does_not_exist_is_a_refusal_not_a_crash(self):
        result = await self._tool().run(
            {"kind": "external", "import_path": "nosuchmodule_xyz:thing"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("could not load", result.error)

    async def test_the_daily_cap_refuses_past_the_limit(self):
        tool = self._tool(max_grants_per_day=2)
        for name in ("a", "b"):
            self.assertTrue((await tool.run(
                {"kind": "external", "import_path": "json:dumps", "name": name}, ctx=_ctx())).ok)
        blocked = await tool.run(
            {"kind": "external", "import_path": "json:dumps", "name": "c"}, ctx=_ctx())
        self.assertFalse(blocked.ok)
        self.assertIn("already granted today", blocked.error)

    async def test_an_mcp_grant_starts_the_server_and_records_its_tools(self):
        result = await self._tool().run(
            {"kind": "mcp", "name": "time", "command": "npx",
             "args": ["-y", "@modelcontextprotocol/server-time"],
             "read_only_tools": ["get_current_time"]}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertIn("mcp_time_get_current_time", result.metadata["tools"])
        self.assertEqual(self.store.load()[0].kind, "mcp")

    async def test_an_mcp_grant_needing_an_absent_credential_is_refused(self):
        result = await self._tool().run(
            {"kind": "mcp", "name": "gh", "command": "npx", "args": ["-y", "server-github"],
             "env_keys": ["GITHUB_TOKEN"]}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("GITHUB_TOKEN", result.error)
        self.assertEqual(self.store.load(), [])

    async def test_a_grant_never_stores_a_secret_only_its_name(self):
        tool = GrantCapabilityTool(
            Config(repo_root=self.root), store=self.store, register=self.registry.register,
            start_mcp=self.registry.start_mcp, clock=_clock(), env={"GITHUB_TOKEN": "ghp_supersecret"})
        result = await tool.run(
            {"kind": "mcp", "name": "gh", "command": "npx", "args": ["-y", "server-github"],
             "env_keys": ["GITHUB_TOKEN"]}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertNotIn("ghp_supersecret", (self.root / "grants.toml").read_text())
        self.assertIn("GITHUB_TOKEN", (self.root / "grants.toml").read_text())

    async def test_an_unknown_kind_is_refused(self):
        result = await self._tool().run({"kind": "sideload"}, ctx=_ctx())
        self.assertFalse(result.ok)


class RevokeCapabilityToolTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.store = GrantStore(self.root / "grants.toml")
        self.registry = _Registry()
        self.store.append(Grant(
            id="g-1", kind="external", granted_at="2026-09-09T00:00:00+00:00",
            name="x_dump", import_path="json:dumps", tools=("x_dump",)))

    def _tool(self):
        return RevokeCapabilityTool(
            Config(repo_root=self.root), store=self.store, unregister=self.registry.unregister)

    async def test_revoking_by_tool_name_unregisters_it_now(self):
        result = await self._tool().run({"target": "x_dump"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.registry.unregistered[0][0], "x_dump")
        self.assertEqual(self.store.active(), [])

    async def test_revoking_by_grant_id_works_too(self):
        self.assertTrue((await self._tool().run({"target": "g-1"}, ctx=_ctx())).ok)
        self.assertEqual(self.store.active(), [])

    async def test_an_unknown_target_says_so(self):
        result = await self._tool().run({"target": "nope"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("no active grant", result.error)

    async def test_revoking_twice_is_honest_the_second_time(self):
        await self._tool().run({"target": "x_dump"}, ctx=_ctx())
        second = await self._tool().run({"target": "x_dump"}, ctx=_ctx())
        self.assertFalse(second.ok)


class OrchestrationForgetsARevokedToolTestCase(unittest.TestCase):
    """A revoked tool must stop being offered AND stop routing: a stale
    marker for a tool that no longer exists would otherwise fail
    somewhere further down with a worse error."""

    def test_a_granted_tool_is_forgotten_but_a_builtin_is_untouched(self):
        from simorgh.orchestration import tools

        tools.register_tool_policy("x_dump", reversibility="irreversible",
                                   provider="external:granted", marker_arg_key="input")
        tools.note_registered("x_dump")
        self.assertIn("x_dump", tools.known_tools())

        tools.unregister_tool("x_dump")
        self.assertNotIn("x_dump", tools.known_tools())
        self.assertNotIn("x_dump", tools._MARKER_ARG_KEY)
        self.assertNotIn("x_dump", tools._TOOL_POLICY)

        # And a revoked grant cannot take a builtin's wiring with it: the
        # runtime tables are shared, and a `pop` with no guard would let
        # a revoke delete read_file's marker key on its way out.
        tools.unregister_tool("read_file")
        self.assertEqual(tools._MARKER_ARG_KEY["read_file"], "path")
        self.assertIn("read_file", tools._TOOL_POLICY)
