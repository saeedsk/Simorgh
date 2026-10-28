"""`mail_unsubscribe`: the sender's own RFC 8058 one-click offer, no browser.

Live 2026-10-27 the creator asked Sim, by voice, to unsubscribe him from
Temu and the rest; Sim could only read the unsubscribe page, which needs
JavaScript, and told him to click it himself. Bulk senders carry
`List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click`,
and one POST does it.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.domains.pim.connectors import FakeImap
from simorgh.domains.pim.tools import MailUnsubscribeTool, _public_https, unsubscribe_links
from simorgh.execution.config import Config

UTC = timezone.utc
ONE_CLICK = "List-Unsubscribe=One-Click"

MESSAGES = [
    {"uid": 11, "subject": "WOW! A BIG OFFER", "from": "Temu <email@news.temuemail.com>",
     "list_unsubscribe": "<mailto:unsub@temuemail.com>, <https://unsub.temuemail.com/u?t=abc>",
     "list_unsubscribe_post": ONE_CLICK, "date": datetime(2026, 10, 27, 19, 55, tzinfo=UTC)},
    {"uid": 12, "subject": "Back in stock", "from": "Temu <email@news.temuemail.com>",
     "list_unsubscribe": "<https://unsub.temuemail.com/u?t=def>",
     "list_unsubscribe_post": ONE_CLICK, "date": datetime(2026, 10, 27, 1, 55, tzinfo=UTC)},
    {"uid": 13, "subject": "Weekly deals", "from": "Michaels <deals@michaels.example>",
     "list_unsubscribe": "<https://michaels.example/prefs?u=1>"},
    {"uid": 14, "subject": "Old list", "from": "list@old.example",
     "list_unsubscribe": "<mailto:leave@old.example?subject=unsubscribe>"},
    {"uid": 15, "subject": "Your statement", "from": "bank@bank.example"},
]


def _ctx() -> ToolContext:
    return ToolContext(action_id="a1", task_id=None, scope={}, constraints={},
                       data_dir=Path("."), clock=None, logger=None, ledger=None, bus=None)


class MailUnsubscribeTestCase(unittest.IsolatedAsyncioTestCase):
    def tool(self, post):
        return MailUnsubscribeTool(Config(), connectors={"gmail": FakeImap("gmail", MESSAGES)}, post=post)

    async def test_one_click_posts_once_per_sender_and_says_what_is_left(self):
        posted = []

        def post(url):
            posted.append(url)
            return 200

        result = await self.tool(post).run(
            {"messages": ["[gmail:INBOX:11]", "gmail:INBOX:12", "gmail:INBOX:13", "gmail:INBOX:14", "gmail:INBOX:15"]},
            ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(posted, ["https://unsub.temuemail.com/u?t=abc"], "one POST for Temu, not two")
        states = {row["sender"]: row["state"] for row in result.metadata["rows"]}
        self.assertEqual(states, {"Temu <email@news.temuemail.com>": "done", "Michaels <deals@michaels.example>": "page",
                                  "list@old.example": "email", "bank@bank.example": "none"})
        self.assertIn("1 of 4 sender(s) unsubscribed", result.output)
        self.assertIn("browse_page", result.output)
        self.assertEqual(result.side_effects, ("mail:unsubscribe:Temu <email@news.temuemail.com>",))

    async def test_a_refused_or_failed_post_is_not_called_done(self):
        def post(url):
            raise ValueError("unsub.temuemail.com is not a public address")

        result = await self.tool(post).run({"messages": ["gmail:INBOX:11"]}, ctx=_ctx())
        self.assertEqual(result.metadata["rows"][0]["state"], "failed")
        self.assertIn("0 of 1", result.output)
        self.assertEqual(result.side_effects, ())

        result = await self.tool(lambda url: 404).run({"messages": ["gmail:INBOX:12"]}, ctx=_ctx())
        self.assertEqual(result.metadata["rows"][0]["state"], "failed")
        self.assertIn("HTTP 404", result.output)

    async def test_no_messages_is_refused(self):
        result = await self.tool(lambda url: 200).run({"messages": []}, ctx=_ctx())
        self.assertEqual(result.error_kind, "refused")

    async def test_nothing_is_written_to_the_mailbox(self):
        connector = FakeImap("gmail", MESSAGES)
        tool = MailUnsubscribeTool(Config(), connectors={"gmail": connector}, post=lambda url: 200)
        await tool.run({"messages": ["gmail:INBOX:11"]}, ctx=_ctx())
        selects = [c for c in connector.server.commands if c[0] == "select"]
        self.assertTrue(selects and all(readonly for _, _, readonly in selects))
        fetches = [c for c in connector.server.commands if c[0] == "FETCH"]
        self.assertTrue(all("PEEK" in str(c[2]) for c in fetches), "the message is not marked read")


class LinksTestCase(unittest.TestCase):
    def test_https_and_mailto_links_in_the_senders_order_and_never_plain_http(self):
        self.assertEqual(unsubscribe_links("<http://x.example/u>, <https://a.example/u>, <mailto:o@a.example?s=1>"),
                         (["https://a.example/u"], ["o@a.example"]))
        self.assertEqual(unsubscribe_links(""), ([], []))

    def test_only_a_public_https_host_may_be_posted_to(self):
        self.assertEqual(_public_https("http://example.com/u"), "not an https link")
        self.assertIn("not a public address", _public_https("https://127.0.0.1/u"))
        self.assertIn("not a public address", _public_https("https://192.168.50.42/u"))


if __name__ == "__main__":
    unittest.main()
