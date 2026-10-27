"""`claude_code_task` with a fake Claude Agent SDK (stage 18 item 12).

The real `claude` CLI is never run. The fake SDK behaves as the real one
does where it matters here: the client calls the PreToolUse hook before
each tool call, and runs the call only when the hook says `allow`.

Over a REAL Guardian and a REAL Execution on the memory bus, so each
Claude Code call goes the whole way: `action.proposed` -> Guardian's
pipeline -> `action.approved` -> Execution verifies the token and answers
-> the hook allows. Pinned:

- every tool call reaches Guardian, with the requester of the
  `claude_code_task` call itself; a denied call never runs;
- with no hook path (or no SDK), the run refuses to start;
- budget caps (turns, dollars, wall-clock) end the run as `partial`;
- off by default, only in a task worktree, at most N runs a day.

A protected-path diff refused at landing is in
`test_landing_refuses_protected_paths.py`; through Claude Code it is
pinned here too (a commit that a denied Edit never made cannot land, and
one made through Bash is refused by the landing check).
"""

from __future__ import annotations

import asyncio
import dataclasses
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts.envelope import Event
from simorgh.contracts.protocols import Context, ToolContext, ToolResult
from simorgh.execution import claudecode
from simorgh.execution.claudecode import STREAM, ClaudeCodeTaskTool, load_sdk, proposal_for
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.service import Service as ExecutionService
from simorgh.execution.worktree import WorktreeManager
from simorgh.guardian.config import DEFAULT_PROTECTED_SUBJECTS, Config as GuardianConfig
from simorgh.guardian.service import Service as GuardianService
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock

REPO = Path(__file__).resolve().parents[3]
_ID = ["-c", "user.name=t", "-c", "user.email=t@example.com"]


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *_ID, *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class _Logger:
    def debug(self, event, **f): pass
    def info(self, event, **f): pass
    def warning(self, event, **f): pass
    def error(self, event, **f): pass


# -- the fake SDK -------------------------------------------------------------------------------


@dataclasses.dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict


@dataclasses.dataclass
class TextBlock:
    text: str


@dataclasses.dataclass
class AssistantMessage:
    content: list


@dataclasses.dataclass
class ResultMessage:
    subtype: str = "success"
    total_cost_usd: float = 0.12
    num_turns: int = 3
    is_error: bool = False
    result: str = "done"


def fake_sdk(script: list, *, result: ResultMessage | None = None, hooks: bool = True,
             delay_s: float = 0.0) -> types.ModuleType:
    """A `claude_agent_sdk` stand-in. `script` is a list of
    `("tool", name, input, effect(cwd))` and `("text", str)`."""
    sdk = types.ModuleType("claude_agent_sdk")
    sdk.ran, sdk.options, sdk.prompts = [], [], []

    fields = dict(cwd=None, max_turns=None, permission_mode=None, max_budget_usd=None,
                  setting_sources=None, disallowed_tools=None, model=None, env=None)
    if hooks:
        fields["hooks"] = None
    sdk.ClaudeAgentOptions = dataclasses.make_dataclass(
        "ClaudeAgentOptions", [(k, Any, dataclasses.field(default=v)) for k, v in fields.items()])

    if hooks:
        @dataclasses.dataclass
        class HookMatcher:
            matcher: Any = None
            hooks: list = dataclasses.field(default_factory=list)

        sdk.HookMatcher = HookMatcher

    class ClaudeSDKClient:
        def __init__(self, options=None):
            self.options = options
            sdk.options.append(options)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def query(self, prompt):
            sdk.prompts.append(prompt)

        async def receive_response(self):
            hook = self.options.hooks["PreToolUse"][0].hooks[0]
            for n, step in enumerate(script):
                if delay_s:
                    await asyncio.sleep(delay_s)
                if step[0] == "text":
                    yield AssistantMessage([TextBlock(step[1])])
                    continue
                _, name, tool_input, effect = step
                yield AssistantMessage([ToolUseBlock(f"tu{n}", name, tool_input)])
                out = await hook({"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": tool_input},
                                 f"tu{n}", None)
                if out["hookSpecificOutput"]["permissionDecision"] == "allow":
                    sdk.ran.append(name)
                    if effect is not None:
                        effect(Path(self.options.cwd))
            yield result or ResultMessage()

    sdk.ClaudeSDKClient = ClaudeSDKClient
    return sdk


def _write(rel: str, text: str):
    def effect(cwd: Path) -> None:
        target = cwd / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return effect


def _commit(message: str):
    def effect(cwd: Path) -> None:
        _git(cwd, "add", "-A")
        _git(cwd, "commit", "-qm", message)
    return effect


# -- the harness --------------------------------------------------------------------------------


class _Case(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="simorgh-cc-")
        self.root = Path(self._tmp.name)
        self.repo = self.root / "repo"
        for d in ("simorgh/guardian", "simorgh/memory", "agents"):
            (self.repo / d).mkdir(parents=True)
        (self.repo / "simorgh" / "guardian" / "rules.py").write_text("RULES = 1\n")
        (self.repo / "simorgh" / "memory" / "store.py").write_text("STORE = 1\n")
        shutil.copy(REPO / "agents" / "claude_code.md", self.repo / "agents" / "claude_code.md")
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-q", "-m", "base")
        self.worktrees = WorktreeManager(self.repo, self.root / "home")
        self.tree = (await self.worktrees.open("t1")).path

        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock)
        secrets = {"__hmac__": "00" * 32}

        gbus = make_client(self.backend, source="guardian", ledger=self.ledger, clock=self.clock)
        await gbus.start()
        self.guardian = GuardianService(config=GuardianConfig(irreversible_requires_human=False))
        await self.guardian.start(Context(name="guardian", instance_id="", run_id="t", mode="single", bus=gbus,
                                          ledger=self.ledger, config={}, secrets=secrets, clock=self.clock,
                                          logger=_Logger(), data_dir=self.root / "g"))
        self.ebus = make_client(self.backend, source="execution", ledger=self.ledger, clock=self.clock)
        await self.ebus.start()
        self.execution = ExecutionService(config=ExecutionConfig(repo_root=self.repo, worktrees=False))
        await self.execution.start(Context(name="execution", instance_id="", run_id="t", mode="single",
                                           bus=self.ebus, ledger=self.ledger, config={}, secrets=secrets,
                                           clock=self.clock, logger=_Logger(), data_dir=self.root / "e"))
        # The `claude_code_task` call's own proposal, as Guardian records it.
        await self.ledger.append("action:cc-call-1", Event(
            stream="action:cc-call-1", type="received", ts=self.clock.now(), trace_id="", causation_id=None,
            payload={"proposal": {"tool": "claude_code_task", "requester": None, "requester_channel": "cli"}}))

    async def asyncTearDown(self):
        await self.execution.stop()
        await self.guardian.stop()
        self._tmp.cleanup()

    def tool(self, sdk, **cc) -> ClaudeCodeTaskTool:
        settings = {"enabled": True, "hook_timeout_s": 10.0, **cc}
        return ClaudeCodeTaskTool(ExecutionConfig(repo_root=self.repo, claude_code=settings), sdk_loader=lambda: sdk)

    def ctx(self, *, root: Path | None = None, bus=True) -> ToolContext:
        return ToolContext(action_id="cc-call-1", task_id="t1", scope={}, constraints={}, data_dir=self.repo,
                           clock=self.clock, logger=_Logger(), ledger=self.ledger,
                           bus=self.ebus if bus else None, root=root if root is not None else self.tree)

    async def run_tool(self, tool, args=None, **ctx) -> ToolResult:
        return await asyncio.wait_for(tool.run(args or {"feature": "add a helper", "module": "memory",
                                                       "files": ["simorgh/memory/helper.py"]},
                                               ctx=self.ctx(**ctx)), timeout=30.0)

    async def proposal(self, action_id: str) -> dict:
        events = await self.ledger.read(f"action:{action_id}")
        return next(e.payload["proposal"] for e in events if e.type == "received")


# -- the tests ----------------------------------------------------------------------------------


class GuardianSeesEveryCall(_Case):
    async def test_every_call_reaches_guardian_and_a_denied_one_never_runs(self):
        guardian_file = self.tree / "simorgh" / "guardian" / "rules.py"
        sdk = fake_sdk([
            ("text", "I will add the helper."),
            ("tool", "Read", {"file_path": str(self.tree / "simorgh" / "memory" / "store.py")}, None),
            ("tool", "Write", {"file_path": str(self.tree / "simorgh" / "memory" / "helper.py"),
                               "content": "def helper():\n    return 1\n"},
             _write("simorgh/memory/helper.py", "def helper():\n    return 1\n")),
            ("tool", "Edit", {"file_path": str(guardian_file), "old_string": "RULES = 1", "new_string": "RULES = 0"},
             _write("simorgh/guardian/rules.py", "RULES = 0\n")),
            ("tool", "Bash", {"command": "git add -A && git commit -m 'memory: a helper'"},
             _commit("memory: a helper")),
        ])
        result = await self.run_tool(self.tool(sdk))
        self.assertTrue(result.ok, result.error)
        report = result.metadata

        decisions = report["decisions"]
        self.assertEqual([d["tool"] for d in decisions], ["Read", "Write", "Edit", "Bash"])
        for decision in decisions:
            proposal = await self.proposal(decision["action_id"])
            self.assertEqual(proposal["tool"], "claude_code:" + decision["tool"], "Guardian saw it")
            self.assertEqual(proposal["requester_channel"], "cli", "the requester is inherited")
            self.assertEqual(proposal["task_id"], "t1")
        self.assertEqual([d["allowed"] for d in decisions], [True, True, False, True])
        self.assertIn("protected", decisions[2]["why"])
        self.assertEqual(sdk.ran, ["Read", "Write", "Bash"], "the denied Edit never ran")
        self.assertEqual(guardian_file.read_text(), "RULES = 1\n")

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["denied_calls"], 1)
        self.assertEqual([c["subject"] for c in report["commits"]], ["memory: a helper"])
        self.assertTrue(report["diff_ref"], "the diff is a blob ref, never inline")
        self.assertIn("simorgh/memory/helper.py", (await self.ledger.get_blob(report["diff_ref"])).decode())
        self.assertEqual(report["cost_usd"], 0.12)
        self.assertIn(f"commit:{report['commits'][0]['sha']}", report["artifacts"])

        kinds = [e.type for e in await self.ledger.read(STREAM)]
        self.assertEqual(kinds[0], "started")
        self.assertEqual(kinds[-1], "finished")
        self.assertEqual(kinds.count("decision"), 4, "every Guardian decision is on the record")
        self.assertIn("progress", kinds, "stream events become progress")

    async def test_a_shell_write_guardian_could_not_see_is_refused_at_landing(self):
        """The second lock: a Bash command that does not name the file
        gets past the hook; the landing check reads the diff."""
        sdk = fake_sdk([("tool", "Bash", {"command": "python make.py && git commit -am x"},
                         lambda cwd: (_write("simorgh/guardian/rules.py", "RULES = 9\n")(cwd), _commit("x")(cwd)))])
        result = await self.run_tool(self.tool(sdk))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(sdk.ran, ["Bash"])

        async def guardian_list():
            return DEFAULT_PROTECTED_SUBJECTS

        self.worktrees.protected = guardian_list
        landed = await self.worktrees.land("t1")
        self.assertFalse(landed.ok)
        self.assertIn("simorgh/guardian/rules.py", landed.detail)

    async def test_network_tools_are_denied_without_asking_unless_allowed(self):
        sdk = fake_sdk([("tool", "WebFetch", {"url": "https://example.com"}, None)])
        result = await self.run_tool(self.tool(sdk))
        self.assertEqual(sdk.ran, [])
        decision = result.metadata["decisions"][0]
        self.assertFalse(decision["allowed"])
        self.assertIn("allow_network", decision["why"])
        self.assertEqual(await self.ledger.read(f"action:{decision['action_id']}"), [])
        self.assertEqual(sdk.options[0].disallowed_tools, ["WebFetch", "WebSearch"])

    async def test_the_options_are_the_most_restrictive_that_let_the_hook_decide(self):
        sdk = fake_sdk([])
        await self.run_tool(self.tool(sdk, max_turns=7, max_usd_per_run=1.5))
        options = sdk.options[0]
        self.assertEqual(options.cwd, str(self.tree))
        self.assertEqual(options.permission_mode, "default")
        self.assertEqual((options.max_turns, options.max_budget_usd), (7, 1.5))
        self.assertIn("add a helper", sdk.prompts[0])
        self.assertIn("python tools/modtest.py memory", sdk.prompts[0], "the brief is agents/claude_code.md's")
        self.assertIn("simorgh/memory/helper.py", sdk.prompts[0])


class NoHookNoRun(_Case):
    async def test_no_hook_path_refuses_to_start(self):
        sdk = fake_sdk([("tool", "Bash", {"command": "echo hi"}, None)], hooks=False)
        result = await self.run_tool(self.tool(sdk))
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "unconfigured")
        self.assertIn("refuses to start", result.error)
        self.assertEqual(sdk.options, [], "no client was ever made")
        self.assertEqual(await self.ledger.read(STREAM), [])

    async def test_no_sdk_is_refused_by_name(self):
        result = await self.run_tool(self.tool(None))
        self.assertEqual(result.error_kind, "unconfigured")
        self.assertIn("claude-agent-sdk", result.error)

    def test_the_real_loader_imports_the_sdk_module(self):
        fake = fake_sdk([])
        saved = sys.modules.get("claude_agent_sdk")
        sys.modules["claude_agent_sdk"] = fake
        try:
            self.assertIs(load_sdk(), fake)
            self.assertEqual(claudecode.hook_path(fake), "")
        finally:
            if saved is None:
                sys.modules.pop("claude_agent_sdk", None)
            else:
                sys.modules["claude_agent_sdk"] = saved

    async def test_no_bus_means_no_guardian_and_no_run(self):
        sdk = fake_sdk([])
        result = await self.run_tool(self.tool(sdk), bus=False)
        self.assertEqual(result.error_kind, "refused")
        self.assertEqual(sdk.options, [])


class BudgetCapsArePartial(_Case):
    async def test_the_turn_cap(self):
        result = await self.run_tool(self.tool(fake_sdk([], result=ResultMessage(subtype="error_max_turns"))))
        self.assertTrue(result.ok)
        self.assertEqual(result.metadata["status"], "partial")
        self.assertIn("turn cap", result.metadata["reason"])

    async def test_the_cost_cap(self):
        result = await self.run_tool(self.tool(fake_sdk([], result=ResultMessage(total_cost_usd=2.5))))
        self.assertEqual(result.metadata["status"], "partial")
        self.assertIn("cost cap", result.metadata["reason"])

    async def test_the_wall_clock_cap(self):
        sdk = fake_sdk([("text", "thinking")] * 50, delay_s=0.05)
        result = await self.run_tool(self.tool(sdk, wall_s=0.2))
        self.assertEqual(result.metadata["status"], "partial")
        self.assertIn("wall-clock", result.metadata["reason"])
        self.assertEqual((await self.ledger.read(STREAM))[-1].type, "finished")

    async def test_a_crew_members_share_caps_the_run(self):
        """Stage 18 review: a crew member's run is carved from its crew's
        dollars. Orchestration sets `max_usd`; the run never gets more than
        that, nor more than `max_usd_per_run`, and nothing starts at 0."""
        sdk = fake_sdk([], result=ResultMessage(total_cost_usd=0.12))
        result = await self.run_tool(self.tool(sdk), {"feature": "a helper", "max_usd": 0.1})
        self.assertEqual(sdk.options[0].max_budget_usd, 0.1)
        self.assertEqual(result.metadata["status"], "partial")
        self.assertIn("cost cap ($0.12 of $0.10)", result.metadata["reason"])
        self.assertEqual(result.metadata["cost_usd"], 0.12, "the cost Orchestration charges to the crew")
        more = fake_sdk([])
        await self.run_tool(self.tool(more, max_runs_per_day=10), {"feature": "a helper", "max_usd": 50})
        self.assertEqual(more.options[0].max_budget_usd, 2.0, "never above max_usd_per_run")
        none_left = fake_sdk([])
        refused = await self.run_tool(self.tool(none_left, max_runs_per_day=10), {"feature": "x", "max_usd": 0})
        self.assertEqual(refused.error_kind, "refused")
        self.assertEqual(none_left.options, [], "no client was made")

    async def test_an_error_result_is_failed(self):
        result = await self.run_tool(self.tool(fake_sdk([], result=ResultMessage(subtype="error_during_execution",
                                                                                 is_error=True))))
        self.assertFalse(result.ok)
        self.assertEqual(result.metadata["status"], "failed")


class OffByDefaultAndBounded(_Case):
    async def test_off_by_default_and_not_registered(self):
        from simorgh.execution.claudecode import claude_code_tools

        self.assertEqual(claude_code_tools(ExecutionConfig()), [])
        tool = ClaudeCodeTaskTool(ExecutionConfig(repo_root=self.repo), sdk_loader=lambda: fake_sdk([]))
        self.assertEqual((await self.run_tool(tool)).error_kind, "unconfigured")
        self.assertEqual([t.name for t in claude_code_tools(
            ExecutionConfig.from_mapping({"claude_code": {"enabled": True}}))], ["claude_code_task"])

    async def test_never_in_the_live_checkout(self):
        sdk = fake_sdk([])
        result = await self.run_tool(self.tool(sdk), root=self.repo)
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("worktree", result.error)
        self.assertEqual(sdk.options, [])

    async def test_at_most_n_runs_a_day(self):
        tool = self.tool(fake_sdk([]), max_runs_per_day=2)
        for _ in range(2):
            self.assertTrue((await self.run_tool(tool)).ok)
        third = await self.run_tool(tool)
        self.assertEqual(third.error_kind, "refused")
        self.assertIn("max_runs_per_day", third.error)
        self.clock.advance(86_400.0)
        self.assertTrue((await self.run_tool(tool)).ok, "a new day")

    def test_defaults(self):
        cc = ExecutionConfig().claude_code
        self.assertEqual((cc.enabled, cc.max_usd_per_run, cc.max_runs_per_day), (False, 2.0, 3))
        self.assertGreater(ClaudeCodeTaskTool(ExecutionConfig()).timeout_s, cc.wall_s)


class NoMoreReachThanSimsOwnTools(_Case):
    """Review of stage 18 item 12. A hook "allow" lets Claude Code's tool
    do whatever Guardian approved, and Guardian has no notion of "inside
    this worktree" (ScopeRule abstains): Sim's own file tools stay in the
    tree through `pathsafety`, and `run_shell` has `shell_refusals`.
    Claude Code's tools had neither."""

    async def _one(self, name: str, tool_input: dict, effect=None):
        sdk = fake_sdk([("tool", name, tool_input, effect)])
        result = await self.run_tool(self.tool(sdk, max_runs_per_day=100))
        return sdk, result.metadata["decisions"][0]

    async def assert_refused_before_guardian(self, name: str, tool_input: dict, why: str, effect=None):
        sdk, decision = await self._one(name, tool_input, effect)
        self.assertEqual(sdk.ran, [], f"{name} {tool_input} ran")
        self.assertFalse(decision["allowed"])
        self.assertIn(why, decision["why"])
        self.assertEqual(await self.ledger.read(f"action:{decision['action_id']}"), [],
                         "refused here, never proposed")

    async def test_a_write_to_the_live_checkout_is_refused(self):
        live = self.repo / "simorgh" / "memory" / "store.py"
        await self.assert_refused_before_guardian(
            "Write", {"file_path": str(live), "content": "STORE = 2\n"}, "outside this task's worktree",
            effect=lambda cwd: live.write_text("STORE = 2\n"))
        self.assertEqual(live.read_text(), "STORE = 1\n")

    async def test_a_relative_escape_and_a_link_out_are_refused(self):
        await self.assert_refused_before_guardian(
            "Edit", {"file_path": "../../repo/simorgh/memory/store.py", "old_string": "1", "new_string": "2"},
            "outside this task's worktree")
        (self.tree / "out").symlink_to(self.repo)
        await self.assert_refused_before_guardian(
            "Write", {"file_path": str(self.tree / "out" / "simorgh" / "memory" / "x.py"), "content": "x"},
            "outside this task's worktree")

    async def test_reads_stay_in_the_tree_and_never_name_a_credential(self):
        await self.assert_refused_before_guardian("Read", {"file_path": str(Path.home() / ".ssh" / "id_rsa")},
                                                  "outside this task's worktree")
        await self.assert_refused_before_guardian("Read", {"file_path": str(self.tree / ".env")},
                                                  "credentials")
        await self.assert_refused_before_guardian("Grep", {"pattern": "KEY", "path": "/etc"},
                                                  "outside this task's worktree")

    async def test_reading_a_protected_file_is_allowed(self):
        """ProtectedRule judges edits; the read_only claim reaches it
        through `ToolRegistry.info_for` for an unregistered tool."""
        sdk, decision = await self._one("Read", {"file_path": str(self.tree / "simorgh" / "guardian" / "rules.py")})
        self.assertTrue(decision["allowed"], decision["why"])
        self.assertEqual(sdk.ran, ["Read"])

    async def test_bash_gets_run_shells_refusals_and_may_not_move_main(self):
        for command, why in (("git push origin HEAD:main", "pushes"),
                             ("git update-ref refs/heads/main HEAD", "moves a git ref"),
                             ("git branch -f main HEAD", "branch"),
                             ("git -C ../.. merge stage", "merges"),
                             (f"cd {self.repo} && git status", "live checkout"),
                             ("cat ~/.ssh/id_ed25519", "credentials")):
            with self.subTest(command=command):
                await self.assert_refused_before_guardian("Bash", {"command": command}, why)
        main = _git(self.repo, "rev-parse", "main")
        _sdk, decision = await self._one("Bash", {"command": "git status && git log --oneline -3"})
        self.assertTrue(decision["allowed"], decision["why"])
        self.assertEqual(_git(self.repo, "rev-parse", "main"), main)

    async def test_sim_holds_the_locks_claude_code_never_takes_one(self):
        """The brief overrides CLAUDE.md's "lock before you edit": Sim is
        the coordinator. A lock claimed, released or written by hand is
        refused before Guardian, whatever the brief said."""
        for command in ("python tools/modlock.py claim memory --by cc --task x",
                        "python3 tools/modlock.py release memory --by cc",
                        "echo '[memory]' >> docs/modules/locks.toml"):
            with self.subTest(command=command):
                await self.assert_refused_before_guardian("Bash", {"command": command}, "Sim holds the locks")
        await self.assert_refused_before_guardian(
            "Write", {"file_path": str(self.tree / "docs" / "modules" / "locks.toml"), "content": "x"},
            "Sim holds the locks")
        _sdk, decision = await self._one("Bash", {"command": "python tools/modtest.py memory"})
        self.assertTrue(decision["allowed"], decision["why"])

    async def test_the_brief_overrides_the_lock_rule_and_keeps_it_in_the_worktree(self):
        sdk = fake_sdk([])
        await self.run_tool(self.tool(sdk))
        brief = sdk.prompts[0]
        self.assertIn("overrides CLAUDE.md's lock rule", brief)
        self.assertIn("tools/modlock.py claim", brief)
        self.assertIn("docs/modules/locks.toml", brief)
        self.assertIn("Stay inside this worktree", brief)
        self.assertIn("Never push", brief)

    async def test_no_settings_file_is_loaded(self):
        """A project `.claude/settings.json` can carry hooks that run
        outside PreToolUse; the worktree is reused by a retry."""
        sdk = fake_sdk([])
        await self.run_tool(self.tool(sdk))
        self.assertEqual(sdk.options[0].setting_sources, [])

    async def test_sims_other_keys_are_blanked_for_claude_code(self):
        from unittest import mock

        env = {"TOGETHER_API_KEY": "t", "ELEVENLABS_API_KEY": "e", "ANTHROPIC_API_KEY": "a"}
        with mock.patch.dict("os.environ", env):
            sdk = fake_sdk([])
            await self.run_tool(self.tool(sdk))
        passed = sdk.options[0].env
        self.assertEqual((passed.get("TOGETHER_API_KEY"), passed.get("ELEVENLABS_API_KEY")), ("", ""))
        self.assertNotIn("ANTHROPIC_API_KEY", passed, "the CLI's own credential is left alone")
        self.assertNotIn("PATH", passed)

    async def test_an_unknown_requester_refuses_to_start(self):
        sdk = fake_sdk([("tool", "Bash", {"command": "echo hi"}, None)])
        tool = self.tool(sdk)
        ctx = dataclasses.replace(self.ctx(), action_id="never-proposed")
        result = await asyncio.wait_for(tool.run({"feature": "x"}, ctx=ctx), timeout=30.0)
        self.assertEqual(result.error_kind, "refused")
        self.assertIn("who asked", result.error)
        self.assertEqual(sdk.options, [], "no client was made")

    async def test_two_runs_at_once_do_not_pass_the_daily_cap_together(self):
        tool = self.tool(fake_sdk([("text", "working")] * 3, delay_s=0.02), max_runs_per_day=1)
        read = self.ledger.read

        async def slow_read(stream, *a, **k):
            # A ledger whose read yields (sqlite reads in a thread), so
            # both calls are between their count and their `started`.
            await asyncio.sleep(0.01)
            return await read(stream, *a, **k)

        self.ledger.read = slow_read
        first, second = await asyncio.gather(self.run_tool(tool), self.run_tool(tool))
        self.assertEqual(sorted([first.ok, second.ok]), [False, True])
        self.assertEqual(sum(1 for e in await self.ledger.read(STREAM) if e.type == "started"), 1)


class TheToolIsWired(unittest.TestCase):
    """The four tables a new tool needs (a missing one shipped a broken
    `camera_describe`, 2026-09-15), and who is offered it."""

    def test_policy_note_verb_and_offers(self):
        from simorgh.interface import live_status
        from simorgh.orchestration import profiles, scaffolds
        from simorgh.orchestration import tools as orch_tools

        self.assertEqual(orch_tools._TOOL_POLICY["claude_code_task"], ("irreversible", True))  # noqa: SLF001
        self.assertIn("claude_code_task", scaffolds._TOOL_NOTES)  # noqa: SLF001
        self.assertIn(("act", "claude_code_task"), live_status._VERBS)  # noqa: SLF001
        self.assertIn("claude_code_task", profiles.PATCH.tools)
        self.assertIn("claude_code_task", profiles.AGENTS["claude_code"].tools)
        for name in ("chat", "voice_chat", "research", "plan"):
            self.assertNotIn("claude_code_task", profiles.AGENTS[name].tools, name)


class TheProposalShapes(unittest.TestCase):
    def test_guardians_rules_read_the_same_keys_as_for_sims_own_tools(self):
        self.assertEqual(proposal_for("Bash", {"command": "ls"}), ({"command": "ls"}, "irreversible", []))
        args, rev, paths = proposal_for("Edit", {"file_path": "/w/simorgh/x.py", "new_string": "y"})
        self.assertEqual((args, rev, paths), ({"path": "/w/simorgh/x.py", "content": "y"}, "reversible",
                                              ["/w/simorgh/x.py"]))
        self.assertEqual(proposal_for("Read", {"file_path": "a"})[1], "read_only")
        self.assertEqual(proposal_for("Task", {"prompt": "x"})[1], "irreversible", "unknown is strictest")


if __name__ == "__main__":
    unittest.main()
