"""A time of day in the chat history, once in a while.

The creator, 2026-09-15: reading a voice log back, he wants to know when
Sim heard what -- "but don't want to enable it for any single conversation
line, as it will make the voice chat log ugly"."""

from __future__ import annotations

import io
import types
import unittest
from contextlib import redirect_stdout

from simorgh.interface import service as service_mod
from simorgh.interface.config import Config
from simorgh.interface.service import Service


class _Clock:
    """Stands in for the `time` module inside the service."""

    def __init__(self) -> None:
        self.at = 1_000_000.0

    def time(self) -> float:
        return self.at

    def strftime(self, fmt: str) -> str:
        return "17:29" if self.at < 1_000_100 else "18:04"


def _service(config: Config) -> Service:
    service = Service.__new__(Service)
    service.config = config
    service._color = False
    service._input_pending = False
    service._last_time_marker = 0.0
    service._live = types.SimpleNamespace(clear=lambda: None, restore=lambda: None)
    return service


def _printed(service: Service, text: str) -> list[str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        service._out(text)
    return buffer.getvalue().splitlines()


class TimeMarker(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self._real_time = service_mod.time
        service_mod.time = self.clock

    def tearDown(self):
        service_mod.time = self._real_time

    def test_once_at_the_head_and_again_after_a_gap(self):
        service = _service(Config(time_marker_minutes=15.0, unicode="off"))
        self.assertEqual(_printed(service, "Sim: hello"), ["-- 17:29 --", "Sim: hello"])
        self.assertEqual(_printed(service, "Sim: still here"), ["Sim: still here"], "not on every line")
        self.clock.at += 14 * 60
        self.assertEqual(_printed(service, "Sim: a minute short"), ["Sim: a minute short"])
        self.clock.at += 2 * 60
        self.assertEqual(_printed(service, "Sim: after the gap"), ["-- 18:04 --", "Sim: after the gap"])

    def test_zero_turns_it_off(self):
        service = _service(Config(time_marker_minutes=0.0))
        self.assertEqual(_printed(service, "Sim: hello"), ["Sim: hello"])
        self.clock.at += 3600
        self.assertEqual(_printed(service, "Sim: much later"), ["Sim: much later"])


if __name__ == "__main__":
    unittest.main()
