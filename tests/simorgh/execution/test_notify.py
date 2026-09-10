"""`notify` (execution/notify.py): the tool that reaches a person.

Every test here injects its own opener, so no test in this file can put
a byte on the network -- including the ones that assert a message was
"sent". What is asserted is the request that WOULD have gone out.

The behaviour worth pinning is what happens with NO credential
configured, because that is the state the tool ships in and the state it
will sit in until somebody adds a key: it must refuse, and the refusal
must name the exact variable to set. A notifier that silently does
nothing is the worst possible failure of a notifier.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from simorgh.contracts.protocols import ToolContext
from simorgh.execution import notify as notify_module
from simorgh.execution.config import Config
from simorgh.execution.notify import (
    NotifyTool,
    NotifyUnavailable,
    available_providers,
    choose_provider,
)


class _Response:
    def __init__(self, status: int = 200, body: bytes = b"{}"):
        self.status, self._body = status, body

    def read(self, _n=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Opener:
    """Stands in for `urllib.request.urlopen`, recording every call."""

    def __init__(self, status: int = 200, raises: Exception | None = None):
        self.status, self.raises, self.calls = status, raises, []

    def __call__(self, request, timeout=None):
        self.calls.append(request)
        if self.raises:
            raise self.raises
        return _Response(self.status)


def _ctx():
    return ToolContext(
        action_id="a1", task_id=None, scope={}, constraints={},
        data_dir=Path("."), clock=None, logger=None, ledger=None,
    )


SLACK_ENV = {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/services/T/B/xxx"}


class ProviderSelectionTestCase(unittest.TestCase):
    def test_nothing_configured_names_every_variable_that_would_work(self):
        with self.assertRaises(NotifyUnavailable) as caught:
            choose_provider("auto", {})
        message = str(caught.exception)
        for variable in ("SLACK_WEBHOOK_URL", "RESEND_API_KEY", "TWILIO_ACCOUNT_SID"):
            self.assertIn(variable, message)

    def test_a_partly_configured_provider_names_only_what_is_missing(self):
        with self.assertRaises(NotifyUnavailable) as caught:
            choose_provider("email", {"RESEND_API_KEY": "k"})
        self.assertIn("NOTIFY_EMAIL_TO", str(caught.exception))
        self.assertNotIn("RESEND_API_KEY", str(caught.exception))

    def test_an_unknown_provider_lists_the_real_ones(self):
        with self.assertRaises(NotifyUnavailable) as caught:
            choose_provider("carrier_pigeon", SLACK_ENV)
        self.assertIn("slack", str(caught.exception))

    def test_auto_takes_the_first_fully_configured_provider(self):
        env = dict(SLACK_ENV, RESEND_API_KEY="k", NOTIFY_EMAIL_TO="a@b.c")
        self.assertEqual(choose_provider("auto", env), "slack")

    def test_a_blank_variable_does_not_count_as_configured(self):
        # An exported-but-empty variable is the classic way a deployment
        # thinks it configured something and did not.
        self.assertEqual(available_providers({"SLACK_WEBHOOK_URL": "   "}), [])


class SendingTestCase(unittest.IsolatedAsyncioTestCase):
    def _tool(self, opener, env=None, **overrides):
        return NotifyTool(Config(**overrides), opener=opener, env=env if env is not None else dict(SLACK_ENV))

    async def test_with_no_provider_it_refuses_and_says_what_to_set(self):
        opener = _Opener()
        result = await self._tool(opener, env={}).run({"body": "done"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("SLACK_WEBHOOK_URL", result.error)
        self.assertEqual(opener.calls, [], "a refusal must not have sent anything")

    async def test_a_slack_message_carries_the_subject_and_body(self):
        opener = _Opener()
        result = await self._tool(opener).run(
            {"subject": "benchmark", "body": "GAIA fell to 29%"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        payload = json.loads(opener.calls[0].data)
        self.assertIn("benchmark", payload["text"])
        self.assertIn("GAIA fell to 29%", payload["text"])

    async def test_an_empty_body_is_refused_before_any_provider_lookup(self):
        opener = _Opener()
        result = await self._tool(opener, env={}).run({"body": "   "}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("empty", result.error)

    async def test_the_body_never_reaches_the_metadata(self):
        # Metadata is written to the Ledger. A notice that echoed its own
        # contents there would copy whatever Sim was told to pass on into
        # a second place nobody chose.
        opener = _Opener()
        secret = "the quarterly figures are 4.2M"
        result = await self._tool(opener).run({"body": secret}, ctx=_ctx())
        self.assertNotIn(secret, json.dumps(result.metadata, default=str))
        self.assertEqual(result.metadata["chars"], len(secret))

    async def test_no_credential_is_echoed_into_the_result(self):
        opener = _Opener(status=500)
        result = await self._tool(opener).run({"body": "hi"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertNotIn("xxx", result.error or "")

    async def test_a_non_2xx_answer_is_a_failure_not_a_quiet_success(self):
        result = await self._tool(_Opener(status=403)).run({"body": "hi"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("403", result.error)

    async def test_a_transport_error_becomes_a_result_not_a_crash(self):
        result = await self._tool(_Opener(raises=OSError("no route to host"))).run(
            {"body": "hi"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertIn("failed", result.error)

    async def test_the_body_is_capped(self):
        opener = _Opener()
        tool = self._tool(opener, notify_max_chars=50)
        result = await tool.run({"body": "x" * 500}, ctx=_ctx())
        self.assertEqual(result.metadata["chars"], 50)

    async def test_the_rate_limit_stops_a_loop_from_spamming(self):
        opener = _Opener()
        tool = self._tool(opener, notify_max_calls=2)
        for _ in range(2):
            self.assertTrue((await tool.run({"body": "hi"}, ctx=_ctx())).ok)
        blocked = await tool.run({"body": "hi"}, ctx=_ctx())
        self.assertFalse(blocked.ok)
        self.assertIn("rate limit", blocked.error)
        self.assertEqual(len(opener.calls), 2, "the blocked call must not have gone out")

    async def test_an_email_send_addresses_the_configured_recipient(self):
        opener = _Opener()
        env = {"RESEND_API_KEY": "k", "NOTIFY_EMAIL_TO": "a@b.c, d@e.f"}
        result = await self._tool(opener, env=env).run({"body": "hi"}, ctx=_ctx())
        self.assertTrue(result.ok, result.error)
        payload = json.loads(opener.calls[0].data)
        self.assertEqual(payload["to"], ["a@b.c", "d@e.f"])

    async def test_a_webhook_pointed_at_the_local_network_is_refused(self):
        # The same SSRF boundary web_fetch uses: a misconfigured (or
        # attacker-supplied) webhook must not become a way to make this
        # machine talk to its own private network.
        opener = _Opener()
        env = {"SLACK_WEBHOOK_URL": "http://169.254.169.254/latest/meta-data/"}
        result = await self._tool(opener, env=env).run({"body": "hi"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertEqual(opener.calls, [])


class ContractTestCase(unittest.TestCase):
    def test_it_is_irreversible_and_stays_that_way(self):
        # There is no unsend. If this ever reads "reversible", something
        # has misunderstood the tool.
        tool = NotifyTool(Config())
        self.assertEqual(tool.reversibility, "irreversible")
        self.assertFalse(tool.read_only)

    def test_every_provider_row_names_at_least_one_variable(self):
        for name, keys in notify_module.PROVIDERS:
            with self.subTest(provider=name):
                self.assertTrue(keys, f"{name} would be 'configured' with nothing set")
                self.assertIn(name, notify_module._SENDERS)
