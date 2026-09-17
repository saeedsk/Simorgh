"""WhatsApp is a public endpoint into this house, so it is a gate first.

The creator, 2026-09-16, by voice: "maybe i can connect you to a whatsapp
application ... i talk to you over whatsapp", and then "CHANGE THE
CONTRACT AND INTRODUCE EXTERNAL VOICE/TEXT CHANNELS LIKE WHATSAPP AND
TELEGRAM".

Telegram dials out; WhatsApp is dialled INTO. Its webhook is a URL on
the public internet that starts real tool-using turns -- the cameras,
the lights, the TV, the backlog -- so most of this file is about who is
turned away, not about carrying a message.

Three gates, and a message must pass all three:

  the signature   every POST carries an HMAC of the raw body under the
                  app secret; no secret or no header means no proof,
                  and no proof means refused
  the allow-list  deny-by-default, empty admits nobody
  the handshake   Meta's subscription GET is answered only when the
                  verify token matches, compared in constant time

Plus the thing Meta does that Telegram does not: it retries a webhook it
believes failed. Answering the same question twice is worse than being
slow, so a message id already handled is dropped.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest

from simorgh.interface.whatsapp import MAX_REPLY, WhatsAppChannel

SECRET = "app-secret"
ALLOWED = ("+1 (415) 555-0123",)
WA_ID = "14155550123"


class _Bus:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, message) -> None:
        self.published.append(message)

    async def subscribe(self, _topic, _handler):
        class _Sub:
            async def unsubscribe(self):
                return None
        return _Sub()


class _Channel(WhatsAppChannel):
    """The real object with only the network replaced."""

    def __init__(self, bus, **kw) -> None:
        super().__init__(bus, **kw)
        self.sent: list[tuple[str, str]] = []

    def _post(self, wa_id: str, text: str) -> dict:
        self.sent.append((wa_id, text))
        return {"messages": [{"id": "sent"}]}


def _channel(bus=None, **kw):
    return _Channel(bus or _Bus(), token="t", phone_id="p", verify_token="v",
                    app_secret=SECRET, allowed=ALLOWED, **kw)


def _body(text: str = "what time is dinner", *, wa_id: str = WA_ID, mid: str = "m1", kind: str = "text") -> bytes:
    message: dict = {"from": wa_id, "id": mid, "type": kind}
    if kind == "text":
        message["text"] = {"body": text}
    return json.dumps({"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": wa_id}], "messages": [message]}}]}]}).encode("utf-8")


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class TheSignatureGateTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_signed_body_is_accepted(self):
        bus = _Bus(); ch = _channel(bus)
        body = _body()
        status, _ = await ch.receive(body, signature=_sign(body))
        self.assertEqual(status, 200)
        self.assertEqual(len(bus.published), 1)

    async def test_an_unsigned_body_is_refused(self):
        """The endpoint is public. Without proof it came from Meta,
        anyone who finds the URL could drive the house."""
        bus = _Bus(); ch = _channel(bus)
        status, _ = await ch.receive(_body(), signature="")
        self.assertEqual(status, 403)
        self.assertEqual(bus.published, [])

    async def test_a_forged_signature_is_refused(self):
        bus = _Bus(); ch = _channel(bus)
        status, _ = await ch.receive(_body(), signature="sha256=deadbeef")
        self.assertEqual(status, 403)
        self.assertEqual(bus.published, [])

    async def test_a_signature_for_different_content_is_refused(self):
        """The HMAC must cover THIS body, not merely be well-formed."""
        bus = _Bus(); ch = _channel(bus)
        status, _ = await ch.receive(_body("turn the cameras off"), signature=_sign(_body("hello")))
        self.assertEqual(status, 403)
        self.assertEqual(bus.published, [])

    async def test_without_an_app_secret_nothing_is_accepted(self):
        """No secret means no proof is possible, so the answer is no --
        not 'skip the check'."""
        bus = _Bus()
        ch = _Channel(bus, token="t", phone_id="p", verify_token="v", app_secret="", allowed=ALLOWED)
        body = _body()
        status, _ = await ch.receive(body, signature=_sign(body))
        self.assertEqual(status, 403)
        self.assertEqual(bus.published, [])


class TheHandshakeTestCase(unittest.TestCase):
    def test_the_challenge_is_echoed_for_the_right_token(self):
        status, body = _channel().verify(
            {"hub.mode": "subscribe", "hub.verify_token": "v", "hub.challenge": "12345"})
        self.assertEqual((status, body), (200, b"12345"))

    def test_a_wrong_token_gets_nothing(self):
        status, _ = _channel().verify(
            {"hub.mode": "subscribe", "hub.verify_token": "guess", "hub.challenge": "12345"})
        self.assertEqual(status, 403)

    def test_a_missing_token_gets_nothing(self):
        self.assertEqual(_channel().verify({"hub.mode": "subscribe"})[0], 403)

    def test_query_values_may_arrive_as_lists(self):
        """A parsed query string gives lists; the handshake must still work."""
        status, body = _channel().verify(
            {"hub.mode": ["subscribe"], "hub.verify_token": ["v"], "hub.challenge": ["7"]})
        self.assertEqual((status, body), (200, b"7"))


class TheAllowListTestCase(unittest.IsolatedAsyncioTestCase):
    async def _receive(self, ch, body):
        return await ch.receive(body, signature=_sign(body))

    async def test_a_stranger_is_ignored_in_silence(self):
        bus = _Bus(); ch = _channel(bus)
        await self._receive(ch, _body(wa_id="19995550000"))
        self.assertEqual(bus.published, [])
        self.assertEqual(ch.sent, [], "a stranger learnt something is listening")

    async def test_an_empty_allow_list_admits_nobody(self):
        bus = _Bus()
        ch = _Channel(bus, token="t", phone_id="p", verify_token="v", app_secret=SECRET, allowed=())
        await self._receive(ch, _body())
        self.assertEqual(bus.published, [])

    async def test_the_number_matches_however_it_is_punctuated(self):
        bus = _Bus(); ch = _channel(bus)
        await self._receive(ch, _body(wa_id="+1-415-555-0123"))
        self.assertEqual(len(bus.published), 1)


class TheConversationTestCase(unittest.IsolatedAsyncioTestCase):
    async def _receive(self, ch, body):
        return await ch.receive(body, signature=_sign(body))

    async def test_one_number_stays_one_conversation(self):
        bus = _Bus(); ch = _channel(bus)
        await self._receive(ch, _body("first", mid="a"))
        await self._receive(ch, _body("second", mid="b"))
        ids = {m.payload["session_id"] for m in bus.published}
        self.assertEqual(len(ids), 1)

    async def test_a_retried_message_is_not_answered_twice(self):
        """Meta retries a webhook it believes failed."""
        bus = _Bus(); ch = _channel(bus)
        await self._receive(ch, _body("what time is dinner", mid="same"))
        await self._receive(ch, _body("what time is dinner", mid="same"))
        self.assertEqual(len(bus.published), 1)

    async def test_the_reply_goes_back_to_that_number(self):
        bus = _Bus(); ch = _channel(bus)
        await self._receive(ch, _body())
        session = bus.published[0].payload["session_id"]

        class _Turn:
            payload = {"session_id": session, "channel": "whatsapp", "text": "Seven."}

        await ch._on_turn(_Turn())
        self.assertEqual(ch.sent, [(WA_ID, "Seven.")])

    async def test_a_turn_from_another_channel_is_not_sent(self):
        bus = _Bus(); ch = _channel(bus)
        await self._receive(ch, _body())
        session = bus.published[0].payload["session_id"]

        class _Turn:
            payload = {"session_id": session, "channel": "voice", "text": "spoken in the room"}

        await ch._on_turn(_Turn())
        self.assertEqual(ch.sent, [])

    async def test_a_long_reply_is_cut_to_what_whatsapp_accepts(self):
        ch = _channel()
        await ch._send(WA_ID, "x" * (MAX_REPLY + 500))
        self.assertLessEqual(len(ch.sent[0][1]), MAX_REPLY)


class WhatItWillNotDoTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_no_phone_number_ever_reaches_the_bus(self):
        """The ledger keeps what it is given for good."""
        bus = _Bus(); ch = _channel(bus)
        body = _body()
        await ch.receive(body, signature=_sign(body))
        payload = bus.published[0].payload
        self.assertNotIn(WA_ID, str(payload))
        self.assertEqual(set(payload) - {"channel", "text", "session_id"}, set())

    async def test_a_voice_note_is_answered_not_swallowed(self):
        """Interface may not import Voice, so there is no transcriber to
        reach from here."""
        bus = _Bus(); ch = _channel(bus)
        body = _body(kind="audio")
        await ch.receive(body, signature=_sign(body))
        self.assertEqual(bus.published, [])
        self.assertEqual(len(ch.sent), 1)
        self.assertIn("audio", ch.sent[0][1])

    async def test_a_status_only_webhook_is_harmless(self):
        """Meta sends delivered/read receipts with no message at all."""
        bus = _Bus(); ch = _channel(bus)
        body = json.dumps({"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]}).encode()
        status, _ = await ch.receive(body, signature=_sign(body))
        self.assertEqual(status, 200)
        self.assertEqual(bus.published, [])

    async def test_it_is_off_until_every_credential_is_there(self):
        for missing in ("token", "phone_id", "verify_token"):
            kw = {"token": "t", "phone_id": "p", "verify_token": "v"}
            kw[missing] = ""
            ch = WhatsAppChannel(_Bus(), **kw)
            with self.subTest(missing=missing):
                self.assertFalse(ch.configured)
                self.assertIn("SIM_WHATSAPP", ch.why_not())

    async def test_construction_never_reaches_the_network(self):
        WhatsAppChannel(None, token="", phone_id="", verify_token="")


if __name__ == "__main__":
    unittest.main()
