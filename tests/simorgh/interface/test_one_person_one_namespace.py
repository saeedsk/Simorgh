"""Stage 6 item 4: the same person in the kitchen and on Telegram.

The acceptance case. Until now each edge had its own idea of who was
writing: the speaker book knew voices, `household.py` knew names, and
the channels matched a handle against those names -- so what Ira said
in the kitchen could not be found under her name on Telegram unless her
handle happened to BE "ira".

A link in the People store ("telegram:irak is Ira") is what closes
that, and these tests pin the two ends of it: a linked handle resolves
to the household name, and an unclaimed one resolves to nothing at all
-- never to the handle, which would put an address in the ledger and in
memory tags for ever.
"""

import unittest

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message


class _Bus:
    source = "interface"

    def __init__(self, people: dict[str, str]):
        self._people = people
        self.asked: list[str] = []

    async def request(self, message, timeout=None):
        identity = str((message.payload.get("args") or {}).get("identity") or "")
        self.asked.append(identity)
        name = self._people.get(identity)
        return Message.new(topics.WORLD_ENV_QUERY + ".reply", source="worldmodel",
                           payload={"person": {"name": name} if name else None})


class _Dead(_Bus):
    async def request(self, message, timeout=None):
        raise TimeoutError("no world model")


def _telegram(bus):
    from simorgh.interface.telegram import TelegramChannel as Telegram

    edge = Telegram.__new__(Telegram)
    edge._bus = bus  # noqa: SLF001
    return edge


def _whatsapp(bus):
    from simorgh.interface.whatsapp import WhatsAppChannel as WhatsApp

    edge = WhatsApp.__new__(WhatsApp)
    edge._bus = bus  # noqa: SLF001
    return edge


class OnePersonAcrossChannels(unittest.IsolatedAsyncioTestCase):
    async def test_a_linked_telegram_handle_is_the_household_name(self):
        bus = _Bus({"telegram:irak": "Ira"})
        self.assertEqual(await _telegram(bus)._person_for("telegram:irak", "irak"), "Ira")  # noqa: SLF001

    async def test_a_linked_whatsapp_number_is_the_household_name(self):
        bus = _Bus({"whatsapp:15551234567": "Ira"})
        name = await _whatsapp(bus)._person_for("whatsapp:15551234567", "15551234567")  # noqa: SLF001
        self.assertEqual(name, "Ira")

    async def test_an_unclaimed_handle_is_nobody_not_the_handle(self):
        bus = _Bus({})
        self.assertEqual(await _telegram(bus)._person_for("telegram:stranger", "stranger"), "")  # noqa: SLF001

    async def test_an_unclaimed_number_never_reaches_the_bus_as_itself(self):
        bus = _Bus({})
        name = await _whatsapp(bus)._person_for("whatsapp:15559999999", "15559999999")  # noqa: SLF001
        self.assertEqual(name, "", "a phone number is not a person's name")

    async def test_a_handle_that_is_a_household_name_still_works_without_a_link(self):
        """The fallback: `channels.person_for` matched names before the
        People store existed, and a fresh install has no links."""
        bus = _Bus({})
        self.assertEqual(await _telegram(bus)._person_for("telegram:saeed", "saeed"), "Saeed")  # noqa: SLF001

    async def test_no_world_model_falls_back_rather_than_failing(self):
        self.assertEqual(await _telegram(_Dead({}))._person_for("telegram:saeed", "saeed"), "Saeed")  # noqa: SLF001

    async def test_the_store_is_asked_by_a_namespaced_identity(self):
        """`saeed` on Telegram and `saeed` on WhatsApp are two
        identities, not one: the kind is part of the key."""
        bus = _Bus({"telegram:x": "Ira"})
        await _telegram(bus)._person_for("telegram:x", "x")  # noqa: SLF001
        self.assertEqual(bus.asked, ["telegram:x"])


if __name__ == "__main__":
    unittest.main()
