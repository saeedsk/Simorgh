"""Tab completes room names after `room`, `mute`, `unmute` (2026-10-04)."""

import asyncio
import unittest

from simorgh.interface import roomnames
from simorgh.interface.tui import _next_words

ROOMS = [{"name": "laptop", "kind": "laptop", "muted": True},
         {"name": "sim-room-1", "kind": "satellite", "muted": False, "connected": True}]


class RoomNamesComplete(unittest.TestCase):
    def setUp(self):
        roomnames.attach(None, None)
        roomnames.remember(ROOMS)

    def test_mute_and_unmute_offer_every_room_and_all(self):
        for verb in ("mute", "unmute"):
            words = dict(_next_words(f"{verb} "))
            self.assertEqual(list(words), ["laptop", "sim-room-1", "all"], verb)
        self.assertEqual(dict(_next_words("mute "))["laptop"], "muted")
        self.assertEqual(dict(_next_words("mute "))["sim-room-1"], "listening")

    def test_room_offers_its_verbs_then_the_rooms(self):
        words = [w for w, _ in _next_words("room ")]
        self.assertEqual(words, ["list", "mute", "unmute", "laptop", "sim-room-1"])
        self.assertIn("all", [w for w, _ in _next_words("room mute ")])
        self.assertIn("sim-room-1", [w for w, _ in _next_words("voice unmute ")])

    def test_the_laptop_is_offered_before_any_status(self):
        roomnames.remember([])
        self.assertIn("laptop", [w for w, _ in _next_words("mute ")])

    def test_an_old_list_asks_for_a_fresh_one_on_the_loop(self):
        async def main():
            calls = []

            async def refresh():
                calls.append(1)
                roomnames.remember(ROOMS[:1])

            roomnames.attach(asyncio.get_running_loop(), refresh)
            roomnames._at = 0.0  # noqa: SLF001 -- long ago
            roomnames.known()
            roomnames.known()          # one refresh at a time
            for _ in range(5):
                await asyncio.sleep(0)
            return calls

        self.assertEqual(asyncio.run(main()), [1])
        self.assertEqual([r["name"] for r in roomnames.known()], ["laptop"])
        roomnames.attach(None, None)


if __name__ == "__main__":
    unittest.main()
