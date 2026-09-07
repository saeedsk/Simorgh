"""`interface.dispatch`'s `mcp` command: the human half of "propose a
server, one human approval" (`execution/tools.py::ProposeMcpServerTool`'s
own docstring has the full design). Real (memory-backend) Bus/Ledger, a
real `dispatch()` call -- `_SIMORGH_TOML_PATH` is patched to a temp file
for `approve` so this test never touches the real repo's own
`simorgh.toml`."""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend, make_client
from simorgh.contracts import topics
from simorgh.contracts.envelope import Event
from simorgh.interface import dispatch as dispatch_module
from simorgh.interface.dispatch import dispatch
from simorgh.interface.parser import Command
from simorgh.interface.vitals import VitalsCache
from simorgh.ledger.factory import make_ledger

from tests.simorgh.helpers import FakeClock


class _McpDispatchTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = FakeClock()
        self.ledger = make_ledger({"backend": "memory"}, clock=self.clock.now)
        await self.ledger.start()
        self.backend = make_backend(BusConfig(backend="memory"), clock=self.clock.now)
        self.bus = make_client(self.backend, source="interface", ledger=self.ledger, clock=self.clock.now)
        await self.bus.start()
        self.vitals = VitalsCache()
        self.other = make_client(self.backend, source="other", ledger=self.ledger, clock=self.clock.now)
        await self.other.start()

        async def _answer_tools(message) -> None:
            await self.other.reply(message, type=topics.WORLD_ENV_QUERY_REPLY, payload={
                "facet": "tools", "as_of": self.clock.now(), "tools": [],
            })

        self._tools_sub = await self.other.subscribe(topics.WORLD_ENV_QUERY, _answer_tools)

    async def asyncTearDown(self):
        await self._tools_sub.unsubscribe()
        await self.other.stop()
        await self.bus.stop()
        await self.ledger.stop()

    async def _append_proposal(self, **overrides) -> str:
        payload = {
            "proposal_id": "abc123", "name": "ddg_search", "command": "npx",
            "args": ["-y", "ddg-search-mcp"], "read_only_tools": ["ddg_search"],
            "env_keys": [], "reason": "free web search, no API key", "status": "pending",
        }
        payload.update(overrides)
        await self.ledger.append(dispatch_module.MCP_PROPOSALS_STREAM, Event(
            stream=dispatch_module.MCP_PROPOSALS_STREAM, type="proposed", ts=self.clock.now(),
            trace_id="", causation_id=None, payload=payload,
        ))
        return payload["proposal_id"]

    async def _mcp(self, args: str) -> str:
        outcome = await dispatch(
            Command(name="mcp", args=args, raw=f"mcp {args}"),
            bus=self.bus, clock=self.clock, session_id="s1", vitals=self.vitals, ledger=self.ledger,
        )
        return outcome.text


class TestMcpBareList(_McpDispatchTestCase):
    async def test_no_pending_proposals_says_so(self):
        out = await self._mcp("")
        self.assertIn("no pending", out)

    async def test_lists_a_pending_proposal_with_its_reason(self):
        await self._append_proposal()
        out = await self._mcp("")
        self.assertIn("abc123", out)
        self.assertIn("ddg_search", out)
        self.assertIn("free web search, no API key", out)
        self.assertIn("npx -y ddg-search-mcp", out)

    async def test_an_approved_proposal_no_longer_appears_as_pending(self):
        await self._append_proposal(status="approved")
        out = await self._mcp("")
        self.assertIn("no pending", out)

    async def test_a_later_event_for_the_same_id_supersedes_the_earlier_one(self):
        await self._append_proposal()
        await self._append_proposal(status="rejected")
        out = await self._mcp("")
        self.assertIn("no pending", out)


class TestMcpApprove(_McpDispatchTestCase):
    async def test_usage_message_without_an_id(self):
        out = await self._mcp("approve")
        self.assertIn("usage", out)

    async def test_unknown_id_is_a_clear_error(self):
        out = await self._mcp("approve nope")
        self.assertIn("no pending proposal", out)

    async def test_approve_writes_a_real_toml_block_and_marks_approved(self):
        await self._append_proposal()
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                out = await self._mcp("approve abc123")
            self.assertIn("approved", out)
            self.assertIn("restart", out)
            content = toml_path.read_text()
        self.assertIn("[[execution.mcp_servers]]", content)
        self.assertIn('name = "ddg_search"', content)
        self.assertIn('command = "npx"', content)
        self.assertIn('args = ["-y", "ddg-search-mcp"]', content)
        pending_out = await self._mcp("")
        self.assertIn("no pending", pending_out)

    async def test_approve_appends_without_disturbing_existing_content(self):
        await self._append_proposal()
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            toml_path.write_text('[runtime]\nmode = "single"  # a human comment\n')
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                await self._mcp("approve abc123")
            content = toml_path.read_text()
        self.assertIn('mode = "single"  # a human comment', content)
        self.assertIn("[[execution.mcp_servers]]", content)

    async def test_env_keys_are_noted_as_names_never_written_as_values(self):
        await self._append_proposal(env_keys=["BRAVE_API_KEY"])
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                await self._mcp("approve abc123")
            content = toml_path.read_text()
        self.assertIn("BRAVE_API_KEY", content)
        self.assertNotIn("env =", content)  # noted in a comment, no env table Sim could have filled in

    async def test_approving_twice_the_second_time_is_an_unknown_id(self):
        await self._append_proposal()
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                await self._mcp("approve abc123")
                second = await self._mcp("approve abc123")
        self.assertIn("no pending proposal", second)


class TestMcpReject(_McpDispatchTestCase):
    async def test_usage_message_without_an_id(self):
        out = await self._mcp("reject")
        self.assertIn("usage", out)

    async def test_reject_marks_it_no_longer_pending_and_never_touches_toml(self):
        await self._append_proposal()
        with tempfile.TemporaryDirectory() as tmp:
            toml_path = Path(tmp) / "simorgh.toml"
            with unittest.mock.patch.object(dispatch_module, "_SIMORGH_TOML_PATH", toml_path):
                out = await self._mcp("reject abc123 too risky")
            self.assertFalse(toml_path.exists())
        self.assertIn("rejected", out)
        self.assertIn("ddg_search", out)
        pending_out = await self._mcp("")
        self.assertIn("no pending", pending_out)


if __name__ == "__main__":
    unittest.main()
