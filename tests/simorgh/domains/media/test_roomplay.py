"""Stage 13 item 8: `room_play`, music on a room satellite's speaker.

The creator, 2026-09-27: "when I ask the satellite board to play
something, I expect it to play the audio on the board by default." The
tool asks Voice over the bus; with no room named, Voice picks the room
whose wake word was just heard. No network here: the radio directory is
stubbed.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from simorgh.contracts import topics
from simorgh.contracts.protocols import ToolContext
from simorgh.domains.media.roomplay import RoomPlayTool


class _Bus:
    def __init__(self, answer=None) -> None:
        self.asked: list[dict] = []
        self.answer = answer or {"ok": True, "room": "kitchen", "detail": "playing it in kitchen"}

    async def request(self, message, timeout=0.0):
        assert message.to_dict()["type"] == topics.VOICE_ROOM_PLAY_REQUEST
        self.asked.append(dict(message.payload))

        class _Reply:
            payload = self.answer
        return _Reply()


def _ctx(bus) -> ToolContext:
    return ToolContext(action_id="a", task_id=None, scope={}, constraints={}, data_dir=Path("."),
                       clock=None, logger=None, ledger=None, bus=bus)


def _tool(station=None):
    tool = RoomPlayTool()
    tool.find_station = lambda query: station
    return tool


class RoomPlay(unittest.IsolatedAsyncioTestCase):
    async def test_a_genre_becomes_a_radio_station_played_where_the_person_is(self):
        bus = _Bus()
        tool = _tool({"name": "Adroit Jazz Underground", "url_resolved": "https://icecast.example/jazz"})
        result = await tool.run({"what": "jazz"}, ctx=_ctx(bus))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(bus.asked[0]["action"], "play")
        self.assertEqual(bus.asked[0]["url"], "https://icecast.example/jazz")
        self.assertEqual(bus.asked[0]["room"], "", "no room named: Voice picks the room just spoken in")
        self.assertIn("Adroit Jazz Underground", bus.asked[0]["title"])

    async def test_a_url_is_played_as_given_in_the_named_room(self):
        bus = _Bus()
        result = await _tool().run({"what": "https://ice1.somafm.com/groovesalad-128-mp3", "room": "kitchen"},
                                   ctx=_ctx(bus))
        self.assertTrue(result.ok)
        self.assertEqual((bus.asked[0]["url"], bus.asked[0]["room"]),
                         ("https://ice1.somafm.com/groovesalad-128-mp3", "kitchen"))

    async def test_stop_and_volume(self):
        bus = _Bus()
        await _tool().run({"what": "stop"}, ctx=_ctx(bus))
        await _tool().run({"volume": "40"}, ctx=_ctx(bus))
        self.assertEqual([a["action"] for a in bus.asked], ["stop", "volume"])
        self.assertAlmostEqual(bus.asked[1]["volume"], 0.4)

    async def test_nothing_found_and_a_refusing_board_are_said_plainly(self):
        result = await _tool(None).run({"what": "nonexistent genre"}, ctx=_ctx(_Bus()))
        self.assertFalse(result.ok)
        self.assertIn("no working MP3 radio station", result.error)
        bus = _Bus({"ok": False, "detail": "which room? -- kitchen, study"})
        result = await _tool({"name": "x", "url_resolved": "u"}).run({"what": "jazz"}, ctx=_ctx(bus))
        self.assertEqual(result.error, "which room? -- kitchen, study")


if __name__ == "__main__":
    unittest.main()
