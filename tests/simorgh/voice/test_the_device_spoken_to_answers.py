"""The device you spoke to answers.

The creator, 2026-10-04, at the laptop with its microphone on: "sim hears
from laptop but replies from the satellite's speaker" -- "logically I
expect to hear the response from which I speak to it". With Follow Up
Mode a board is open after every reply, and any open board used to win."""

from __future__ import annotations

import time
import types
import unittest

from simorgh.voice import service as svc


def _service(*, woken: bool, follow_up: bool, room_answered_s_ago: float | None = None):
    service = svc.Service.__new__(svc.Service)
    mic = types.SimpleNamespace(woken=woken, follow_up=follow_up)
    service._satellites = {"satellite": types.SimpleNamespace(microphone=mic)}   # noqa: SLF001
    at = time.monotonic() - room_answered_s_ago if room_answered_s_ago is not None else -1e9
    service._rooms = {"satellite": types.SimpleNamespace(answering_at=at)}        # noqa: SLF001
    return service


class TheDeviceSpokenToAnswers(unittest.TestCase):
    def test_a_real_wake_word_on_the_board_is_the_rooms(self):
        self.assertTrue(_service(woken=True, follow_up=False)._laptop_defers())   # noqa: SLF001

    def test_a_board_only_in_its_follow_up_window_does_not_take_the_laptops_sentence(self):
        self.assertFalse(_service(woken=True, follow_up=True)._laptop_defers())   # noqa: SLF001

    def test_but_a_room_that_began_answering_first_keeps_it(self):
        self.assertTrue(_service(woken=True, follow_up=True, room_answered_s_ago=1.0)._laptop_defers())  # noqa: SLF001
        self.assertFalse(_service(woken=True, follow_up=True, room_answered_s_ago=30.0)._laptop_defers())  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
