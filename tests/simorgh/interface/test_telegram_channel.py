"""Sim answers from a phone, and only to the family.

The creator, 2026-09-16: "CHANGE THE CONTRACT AND INTRODUCE EXTERNAL
VOICE/TEXT CHANNELS LIKE WHATSAPP AND TELEGRAM" -- after telling Sim by
voice what it was for: talking to it from the car instead of carrying
the MacBook out to it.

Telegram is first because it can work tonight: a bot token and an
outbound long-poll, nothing exposed to the internet, no Meta business
account, and no ban risk to the family's own number.

The tests that matter most here are not the happy path. An external
channel is a remote control of this house -- the cameras, the lights,
the TV, the backlog -- offered to whoever finds the address. So the gate
is deny-by-default, a stranger is met with silence rather than a refusal
that confirms something is listening, and no chat address is ever put on
the bus, because the ledger keeps what it is given for good.
"""

from __future__ import annotations

import unittest

from simorgh.contracts import topics
from simorgh.interface.telegram import MAX_REPLY, TelegramChannel


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


def _update(text: str, *, who: str = "saeed", chat: int = 42, uid: int = 7, **extra) -> dict:
    sender = {"id": uid}
    if who:
        sender["username"] = who
    message = {"chat": {"id": chat}, "from": sender}
    if text:
        message["text"] = text
    message.update(extra)
    return {"update_id": 1, "message": message}


class _Channel(TelegramChannel):
    """The real object with only the network replaced."""

    def __init__(self, bus, **kw) -> None:
        super().__init__(bus, **kw)
        self.sent: list[tuple[int, str]] = []

    async def _api(self, method: str, **params):
        if method == "sendMessage":
            self.sent.append((params["chat_id"], params["text"]))
        return {"ok": True, "result": []}


class TheGateTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_a_listed_person_is_heard(self):
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed",))
        await ch._on_update(_update("what time is dinner"))
        self.assertEqual(len(bus.published), 1)
        self.assertEqual(bus.published[0].payload["text"], "what time is dinner")
        self.assertEqual(bus.published[0].payload["channel"], "telegram")

    async def test_a_stranger_is_ignored_entirely(self):
        """Not refused -- ignored. A refusal tells them something is
        here."""
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed",))
        await ch._on_update(_update("turn the cameras off", who="stranger", uid=999))
        self.assertEqual(bus.published, [], "a stranger reached the house")
        self.assertEqual(ch.sent, [], "a stranger learnt that something is listening")

    async def test_an_empty_allow_list_admits_nobody(self):
        """The failure that would hand the house to anyone who finds the
        bot: an unconfigured list meaning "everyone"."""
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=())
        await ch._on_update(_update("hello"))
        self.assertEqual(bus.published, [])

    async def test_a_number_is_matched_however_it_is_punctuated(self):
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("+1 (415) 555-0123",))
        await ch._on_update(_update("hello", who="", uid=14155550123))
        self.assertEqual(len(bus.published), 1)


class TheConversationTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_one_person_stays_one_conversation(self):
        """A fresh session per message would meet a stranger every
        time; memory groups turns by session_id."""
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed",))
        await ch._on_update(_update("what time is dinner"))
        await ch._on_update(_update("and tomorrow?"))
        first, second = (m.payload["session_id"] for m in bus.published)
        self.assertEqual(first, second)

    async def test_two_chats_are_two_conversations(self):
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed", "soodeh"))
        await ch._on_update(_update("mine", who="saeed", chat=1))
        await ch._on_update(_update("mine too", who="soodeh", chat=2))
        self.assertNotEqual(bus.published[0].payload["session_id"],
                            bus.published[1].payload["session_id"])

    async def test_the_reply_goes_back_to_that_chat(self):
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed",))
        await ch._on_update(_update("what time is dinner", chat=99))
        session = bus.published[0].payload["session_id"]

        class _Turn:
            payload = {"session_id": session, "channel": "telegram", "text": "Seven."}

        await ch._on_turn(_Turn())
        self.assertEqual(ch.sent, [(99, "Seven.")])

    async def test_a_turn_from_another_channel_is_not_sent(self):
        """Every reply in the house crosses this handler; only its own
        may go out."""
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed",))
        await ch._on_update(_update("hi", chat=99))
        session = bus.published[0].payload["session_id"]

        class _Turn:
            payload = {"session_id": session, "channel": "voice", "text": "spoken in the room"}

        await ch._on_turn(_Turn())
        self.assertEqual(ch.sent, [], "a spoken reply was forwarded to a phone")

    async def test_a_long_reply_is_cut_to_what_telegram_accepts(self):
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed",))
        await ch._send(1, "x" * (MAX_REPLY + 500))
        self.assertLessEqual(len(ch.sent[0][1]), MAX_REPLY)


class WhatItWillNotDoTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_no_chat_address_ever_reaches_the_bus(self):
        """The ledger keeps what it is given for good; the family's
        Telegram ids are not its business."""
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed",))
        await ch._on_update(_update("hello", chat=424242, uid=7))
        payload = bus.published[0].payload
        self.assertNotIn("424242", str(payload))
        self.assertEqual(set(payload) - {"channel", "text", "session_id"}, set())

    async def test_a_voice_note_is_answered_not_swallowed(self):
        """Interface may not import Voice, so there is no transcriber to
        reach from here. Silence would look like being ignored."""
        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed",))
        await ch._on_update(_update("", voice={"file_id": "abc"}))
        self.assertEqual(bus.published, [])
        self.assertEqual(len(ch.sent), 1)
        self.assertIn("voice", ch.sent[0][1])

    async def test_it_is_off_without_a_token_and_says_why(self):
        ch = TelegramChannel(_Bus(), token="", allowed=("saeed",))
        self.assertFalse(ch.configured)
        self.assertIn("SIM_TELEGRAM_TOKEN", ch.why_not())

    async def test_a_token_with_nobody_allowed_says_that_too(self):
        ch = TelegramChannel(_Bus(), token="t", allowed=())
        self.assertIn("telegram_allowed", ch.why_not())

    async def test_construction_never_reaches_the_network(self):
        """Every connector in this codebase obeys this: a missing
        credential is not an error at construction, it is a probe
        result."""
        TelegramChannel(None, token="", allowed=())


class TheChannelIsInTheContractTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_its_percept_validates(self):
        from simorgh.contracts.registry import get_spec
        import simorgh.contracts.messages.percept  # noqa: F401

        bus = _Bus()
        ch = _Channel(bus, token="t", allowed=("saeed",))
        await ch._on_update(_update("hello"))
        spec = get_spec(topics.PERCEPT_TEXT_RECEIVED)
        self.assertEqual(spec.validate(bus.published[0].payload), [])


if __name__ == "__main__":
    unittest.main()
