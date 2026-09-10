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
import types
import unittest
import unittest.mock
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


class OpenSourceProviderTestCase(unittest.IsolatedAsyncioTestCase):
    """The self-hosted providers (platform-connectors-design.md section
    7). Every one of these is a box the creator runs, so the assertions
    are about the request that WOULD go out and about the two things
    that are easy to get wrong: the private-address rule, and a token
    leaking into a result."""

    def _tool(self, opener, env, **overrides):
        return NotifyTool(Config(**overrides), opener=opener, env=env)

    async def _send(self, env, **kwargs):
        opener = _Opener()
        result = await self._tool(opener, env).run(
            {"subject": kwargs.pop("subject", "hello"), "body": kwargs.pop("body", "the body")},
            ctx=_ctx())
        return result, opener

    # -- ntfy ----------------------------------------------------------------

    async def test_ntfy_puts_the_body_in_the_body_and_the_subject_in_a_header(self):
        result, opener = await self._send({"NTFY_URL": "https://ntfy.sh/my-topic"})
        self.assertTrue(result.ok, result.error)
        request = opener.calls[0]
        self.assertEqual(request.data, b"the body")
        self.assertEqual(request.get_header("Title"), "hello")
        self.assertIsNone(request.get_header("Authorization"))

    async def test_ntfy_sends_its_token_when_one_is_set(self):
        _, opener = await self._send({"NTFY_URL": "https://ntfy.sh/t", "NTFY_TOKEN": "tk_abc"})
        self.assertEqual(opener.calls[0].get_header("Authorization"), "Bearer tk_abc")

    async def test_a_subject_that_cannot_be_a_latin1_header_does_not_lose_the_message(self):
        # urllib encodes headers as latin-1: an em-dash or an emoji in
        # the subject used to raise deep inside the send.
        result, opener = await self._send({"NTFY_URL": "https://ntfy.sh/t"}, subject="done — \U0001f680")
        self.assertTrue(result.ok, result.error)
        self.assertEqual(opener.calls[0].data, b"the body")

    async def test_a_self_hosted_ntfy_on_the_lan_is_allowed(self):
        # The whole point of ntfy is that it can be your own box. The
        # cloud providers keep the SSRF refusal; these do not, because
        # the URL is an operator's environment variable and never a
        # tool argument.
        result, opener = await self._send({"NTFY_URL": "http://192.168.1.50:8080/alerts"})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(len(opener.calls), 1)

    async def test_a_cloud_provider_still_refuses_a_private_address(self):
        result, opener = await self._send({"SLACK_WEBHOOK_URL": "http://192.168.1.50/hook"})
        self.assertFalse(result.ok)
        self.assertEqual(opener.calls, [])

    # -- gotify --------------------------------------------------------------

    async def test_gotify_posts_a_message_with_its_key_in_the_header(self):
        result, opener = await self._send({"GOTIFY_URL": "http://gotify.lan/", "GOTIFY_TOKEN": "A.key"})
        self.assertTrue(result.ok, result.error)
        request = opener.calls[0]
        self.assertEqual(request.full_url, "http://gotify.lan/message")
        self.assertEqual(request.get_header("X-gotify-key"), "A.key")
        self.assertEqual(json.loads(request.data)["message"], "the body")

    async def test_gotify_never_echoes_its_key_into_the_result(self):
        opener = _Opener(status=401)
        result = await self._tool(opener, {"GOTIFY_URL": "http://g.lan", "GOTIFY_TOKEN": "SECRETKEY"}).run(
            {"body": "hi"}, ctx=_ctx())
        self.assertFalse(result.ok)
        self.assertNotIn("SECRETKEY", json.dumps([result.error, result.output, result.metadata], default=str))

    # -- home assistant ------------------------------------------------------

    async def test_home_assistant_calls_the_default_notify_service(self):
        result, opener = await self._send({"HASS_URL": "http://homeassistant.local:8123", "HASS_TOKEN": "llat"})
        self.assertTrue(result.ok, result.error)
        request = opener.calls[0]
        self.assertEqual(request.full_url, "http://homeassistant.local:8123/api/services/notify/notify")
        self.assertEqual(request.get_header("Authorization"), "Bearer llat")

    async def test_home_assistant_targets_a_named_mobile_app_service(self):
        _, opener = await self._send({"HASS_URL": "http://ha.lan", "HASS_TOKEN": "t",
                                      "HASS_NOTIFY_SERVICE": "mobile_app_pixel"})
        self.assertTrue(opener.calls[0].full_url.endswith("/api/services/notify/mobile_app_pixel"))

    async def test_the_notify_prefix_is_accepted_and_not_mangled(self):
        # `lstrip("notify.")` strips a character SET, so a service whose
        # name begins with one of those letters lost it.
        _, opener = await self._send({"HASS_URL": "http://ha.lan", "HASS_TOKEN": "t",
                                      "HASS_NOTIFY_SERVICE": "notify.telegram"})
        self.assertTrue(opener.calls[0].full_url.endswith("/notify/telegram"))

    async def test_a_service_name_starting_with_a_prefix_letter_survives(self):
        _, opener = await self._send({"HASS_URL": "http://ha.lan", "HASS_TOKEN": "t",
                                      "HASS_NOTIFY_SERVICE": "trusted_phone"})
        self.assertTrue(opener.calls[0].full_url.endswith("/notify/trusted_phone"))

    # -- matrix --------------------------------------------------------------

    async def test_matrix_puts_a_room_message_with_an_escaped_room_id(self):
        result, opener = await self._send({"MATRIX_HOMESERVER": "https://matrix.org",
                                            "MATRIX_TOKEN": "syt_x", "MATRIX_ROOM": "!abc:matrix.org"})
        self.assertTrue(result.ok, result.error)
        request = opener.calls[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertIn("%21abc%3Amatrix.org", request.full_url)
        self.assertEqual(json.loads(request.data)["msgtype"], "m.text")
        self.assertIn("the body", json.loads(request.data)["body"])

    async def test_two_matrix_sends_use_different_transaction_ids(self):
        env = {"MATRIX_HOMESERVER": "https://m.org", "MATRIX_TOKEN": "t", "MATRIX_ROOM": "!r:m.org"}
        opener = _Opener()
        tool = self._tool(opener, env)
        await tool.run({"body": "one"}, ctx=_ctx())
        await tool.run({"body": "two"}, ctx=_ctx())
        self.assertNotEqual(opener.calls[0].full_url, opener.calls[1].full_url)

    # -- apprise -------------------------------------------------------------

    async def test_apprise_is_skipped_by_auto_when_the_package_is_absent(self):
        # Otherwise `auto` picks a provider that cannot work and the
        # message is lost, while a perfectly good Slack hook sits unused.
        env = {"APPRISE_URLS": "tgram://token/chat", "SLACK_WEBHOOK_URL": "https://hooks.slack.com/x"}
        with unittest.mock.patch.object(notify_module, "_apprise_installed", lambda: False):
            self.assertEqual(choose_provider("auto", env), "slack")

    async def test_naming_apprise_explicitly_says_what_to_install(self):
        with unittest.mock.patch.object(notify_module, "_apprise_installed", lambda: False):
            with self.assertRaises(NotifyUnavailable) as caught:
                choose_provider("apprise", {"APPRISE_URLS": "tgram://t/c"})
        self.assertIn("pip install apprise", str(caught.exception))

    async def test_apprise_sends_through_the_library_and_reports_the_count(self):
        sent = {}

        class _FakeApprise:
            def __init__(self):
                self.urls = []

            def add(self, url):
                self.urls.append(url)
                return True

            def notify(self, title, body):
                sent["title"], sent["body"], sent["urls"] = title, body, list(self.urls)
                return True

        module = types.SimpleNamespace(Apprise=_FakeApprise)
        with unittest.mock.patch.object(notify_module, "_apprise_installed", lambda: True), \
             unittest.mock.patch.object(notify_module, "_load_apprise", lambda: module):
            result, opener = await self._send({"APPRISE_URLS": "tgram://t/c, discord://w/t"})
        self.assertTrue(result.ok, result.error)
        self.assertEqual(sent["urls"], ["tgram://t/c", "discord://w/t"])
        self.assertEqual(sent["body"], "the body")
        self.assertEqual(opener.calls, [], "apprise does its own I/O")

    async def test_an_apprise_delivery_failure_is_not_reported_as_sent(self):
        class _FailingApprise:
            def add(self, url):
                return True

            def notify(self, title, body):
                return False

        module = types.SimpleNamespace(Apprise=_FailingApprise)
        with unittest.mock.patch.object(notify_module, "_apprise_installed", lambda: True), \
             unittest.mock.patch.object(notify_module, "_load_apprise", lambda: module):
            result, _ = await self._send({"APPRISE_URLS": "tgram://t/c"})
        self.assertFalse(result.ok)

    async def test_an_apprise_url_never_reaches_the_result(self):
        # An apprise URL embeds its own token: `tgram://<bot token>/<chat>`.
        class _RejectingApprise:
            def add(self, url):
                return False

            def notify(self, title, body):
                return True

        module = types.SimpleNamespace(Apprise=_RejectingApprise)
        with unittest.mock.patch.object(notify_module, "_apprise_installed", lambda: True), \
             unittest.mock.patch.object(notify_module, "_load_apprise", lambda: module):
            result, _ = await self._send({"APPRISE_URLS": "tgram://SUPERSECRET/chat"})
        self.assertFalse(result.ok)
        self.assertNotIn("SUPERSECRET", json.dumps([result.error, result.output, result.metadata], default=str))


class ProviderOrderTestCase(unittest.TestCase):
    def test_self_hosted_providers_come_before_the_cloud_ones(self):
        """`feedback_resourcefulness`: local first, cloud as a named
        tier. A person with both a Gotify box and a Slack hook should
        not have their notifications routed through Slack by default."""
        order = [name for name, _ in notify_module.PROVIDERS]
        for local in ("ntfy", "gotify", "home_assistant", "matrix"):
            self.assertLess(order.index(local), order.index("slack"), local)

    def test_auto_prefers_the_self_hosted_box(self):
        env = {"SLACK_WEBHOOK_URL": "https://hooks.slack.com/x", "GOTIFY_URL": "http://g.lan",
               "GOTIFY_TOKEN": "k"}
        self.assertEqual(choose_provider("auto", env), "gotify")

    def test_every_provider_has_a_sender_and_the_private_set_is_a_subset(self):
        names = {name for name, _ in notify_module.PROVIDERS}
        self.assertEqual(names, set(notify_module._SENDERS))
        self.assertTrue(notify_module._ALLOW_PRIVATE <= names)

    def test_no_cloud_provider_allows_a_private_address(self):
        for cloud in ("slack", "email", "sms"):
            self.assertNotIn(cloud, notify_module._ALLOW_PRIVATE)

    def test_nothing_configured_still_names_every_variable(self):
        message = ""
        try:
            choose_provider("auto", {})
        except NotifyUnavailable as exc:
            message = str(exc)
        for variable in ("NTFY_URL", "GOTIFY_URL", "HASS_URL", "MATRIX_HOMESERVER",
                         "APPRISE_URLS", "SLACK_WEBHOOK_URL"):
            self.assertIn(variable, message)

    def test_the_missing_package_refusal_comes_from_the_loader_itself(self):
        """The guard has to sit on the import statement (module-boundary
        rule 5), which also puts the pip line next to the import that
        failed rather than in a caller that might forget to catch it."""
        import builtins

        real_import = builtins.__import__

        def _no_apprise(name, *args, **kwargs):
            if name == "apprise":
                raise ImportError("no module named apprise")
            return real_import(name, *args, **kwargs)

        with unittest.mock.patch.object(builtins, "__import__", _no_apprise):
            with self.assertRaises(NotifyUnavailable) as caught:
                notify_module._load_apprise()
        self.assertIn("pip install apprise", str(caught.exception))
