"""A handle linked to a person in the People store may write (stage 6
item 4).

Linking `telegram:<handle>` to somebody is a tier-3 action a person
confirms, and it was not enough to let them in: `telegram_allowed` in
the config was a second, separate answer to "who may talk to Sim here".
Only a LINK admits -- a handle that merely spells a household name does
not, because anyone can choose that username.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from simorgh.interface.telegram import TelegramChannel
from simorgh.interface.whatsapp import WhatsAppChannel


class _Bus:
    def __init__(self, links: dict[str, str]) -> None:
        self.links = links
        self.published: list = []

    async def publish(self, message) -> None:
        self.published.append(message)

    async def request(self, message, timeout=1.0):
        name = self.links.get(message.payload["args"].get("identity", ""))
        return SimpleNamespace(payload={"person": {"name": name} if name else None})

    async def subscribe(self, _topic, _handler):
        return SimpleNamespace(unsubscribe=lambda: None)


class _Telegram(TelegramChannel):
    async def _api(self, method: str, **params):
        return {"ok": True, "result": []}


def _update(text: str, who: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": 42}, "from": {"id": 7, "username": who}, "text": text}}


class Telegram(unittest.IsolatedAsyncioTestCase):
    async def test_a_linked_handle_is_heard_with_no_allow_list(self):
        bus = _Bus({"telegram:ira_k": "Ira"})
        await _Telegram(bus, token="t", allowed=())._on_update(_update("hi", "ira_k"))
        self.assertEqual(len(bus.published), 1)
        self.assertEqual(bus.published[0].payload.get("speaker"), "Ira")

    async def test_a_handle_that_spells_a_family_name_is_not(self):
        bus = _Bus({})
        await _Telegram(bus, token="t", allowed=())._on_update(_update("unlock the door", "Saeed"))
        self.assertEqual(bus.published, [])


class WhatsApp(unittest.IsolatedAsyncioTestCase):
    async def test_a_linked_number_is_let_in_and_a_stranger_is_not(self):
        bus = _Bus({"whatsapp:14155550123": "Soodeh"})
        ch = WhatsAppChannel(bus, token="t", phone_id="p", verify_token="v", app_secret="s", allowed=())
        sent = []

        async def _send(wa_id, text):
            sent.append(text)

        ch._send = _send
        await ch._on_message({"from": "14155550123", "id": "m1", "type": "text", "text": {"body": "hi"}}, "")
        await ch._on_message({"from": "19998887777", "id": "m2", "type": "text", "text": {"body": "hi"}}, "")
        self.assertEqual(len(bus.published), 1)


if __name__ == "__main__":
    unittest.main()
