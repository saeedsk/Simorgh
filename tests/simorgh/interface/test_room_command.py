"""`room`, `mute ?`, `unmute ?`: the rooms and which are muted, live.

The creator, 2026-10-04: "mute and unmute should allow me to mute different
rooms, the list of rooms, their mute status should be queryable, the ? in
mute and unmute should show possible room options and their current status,
we may need to introduce the room command and its subsets"."""

import asyncio
import types
import unittest
from unittest import mock

from simorgh.interface import dispatch, voiceview
from simorgh.interface.parser import COMMAND_NAMES, parse

ROOMS = [{"name": "laptop", "kind": "laptop", "muted": True},
         {"name": "sim-room-1", "kind": "satellite", "muted": False, "connected": True, "button_muted": False},
         {"name": "kitchen", "kind": "satellite", "muted": False, "connected": True, "button_muted": True}]


class _Bus:
    def __init__(self):
        self.sent = []

    def new(self, topic, payload):
        return types.SimpleNamespace(topic=topic, payload=payload)

    async def request(self, message, timeout=0.0):
        self.sent.append(message.payload)
        if message.payload.get("action"):
            return types.SimpleNamespace(payload={"ok": True, "detail": f"{message.payload['name']} done"})
        return types.SimpleNamespace(payload={"rooms": ROOMS})


def _run(line):
    bus = _Bus()
    outcome = asyncio.run(dispatch.dispatch(parse(line), bus=bus, ledger=None,
                                            clock=types.SimpleNamespace(now=lambda: 0.0), session_id="s", vitals=None))
    return outcome.text, bus.sent


class RoomCommand(unittest.TestCase):
    def test_room_is_a_command(self):
        self.assertIn("room", COMMAND_NAMES)
        self.assertEqual(parse("room").name, "room")
        self.assertEqual(parse("room mute all").name, "room")
        self.assertIsNone(parse("room is far too warm today").name)

    def test_room_lists_every_room_and_its_state(self):
        text, _ = _run("room")
        self.assertIn("laptop", text)
        self.assertIn("muted", text)
        self.assertIn("sim-room-1", text)
        self.assertIn("listening", text)
        self.assertIn("muted by its button", text)

    def test_mute_question_mark_offers_the_rooms_still_listening(self):
        text, _ = _run("mute ?")
        self.assertIn("mute sim-room-1 | kitchen | all", text)
        text, _ = _run("unmute ?")
        self.assertIn("unmute laptop", text)

    def test_mute_and_room_mute_name_a_room_or_all(self):
        _, sent = _run("mute all")
        self.assertEqual(sent[-1], {"action": "mute", "name": "all"})
        _, sent = _run("room unmute kitchen")
        self.assertEqual(sent[-1], {"action": "unmute", "name": "kitchen"})

    def test_room_name_shows_one_room(self):
        text, _ = _run("room sim")
        self.assertTrue(text.startswith("sim-room-1"), text)
        text, _ = _run("room garage")
        self.assertIn("rooms: laptop, sim-room-1, kitchen", text)

    def test_with_no_rooms_it_says_voice_is_off(self):
        self.assertIn("voice is off", voiceview.room_panel([]))


if __name__ == "__main__":
    unittest.main()
