"""Interface carrying out a command Sim asked for (`ui.command.request`)."""

from __future__ import annotations

import types
import unittest
from unittest import mock

from simorgh.contracts import topics
from simorgh.contracts.envelope import Message
from simorgh.interface.config import Config
from simorgh.interface.dispatch import Outcome
from simorgh.interface.service import Service


class _Bus:
    def __init__(self) -> None:
        self.replies: list[tuple[str, dict]] = []

    async def reply(self, message, *, type: str, payload: dict) -> None:  # noqa: A002
        self.replies.append((type, payload))


def _service(bus):
    service = Service.__new__(Service)
    service._ctx = types.SimpleNamespace(bus=bus, clock=types.SimpleNamespace(now=lambda: 0.0), ledger=None)
    service.config = Config()
    service.session_id = "s1"
    service.vitals = None
    service._watched_tasks = set()
    service._stop_repl = types.SimpleNamespace(set=lambda: None)
    service.printed: list[str] = []
    service._out = service.printed.append
    return service


def _request(line: str) -> Message:
    return Message.new(topics.UI_COMMAND_REQUEST, source="execution", payload={"line": line, "requested_by": "sim"})


class CommandRequest(unittest.IsolatedAsyncioTestCase):
    async def test_a_real_command_is_dispatched_and_shown(self):
        bus = _Bus()
        service = _service(bus)
        with mock.patch("simorgh.interface.service.dispatch",
                        return_value=Outcome("restarting -- Sim will come back up...", exit_repl=True)) as ran:
            await service._on_command_request(_request("restart"))        # noqa: SLF001
        self.assertEqual(ran.call_args.args[0].name, "restart")
        type_, payload = bus.replies[0]
        self.assertEqual(type_, topics.UI_COMMAND_REPLY)
        self.assertIn("come back up", payload["text"])
        self.assertTrue(payload["exit_repl"])
        self.assertIn("[sim ran: restart]", service.printed)

    async def test_an_unknown_command_is_refused(self):
        bus = _Bus()
        service = _service(bus)
        await service._on_command_request(_request("flibble the wotsit"))  # noqa: SLF001
        _type, payload = bus.replies[0]
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unknown_command")

    async def test_the_shell_escape_is_refused(self):
        bus = _Bus()
        service = _service(bus)
        await service._on_command_request(_request("!rm -rf /"))           # noqa: SLF001
        _type, payload = bus.replies[0]
        self.assertFalse(payload["ok"])
        self.assertIn("run_shell", payload["error"]["detail"])


if __name__ == "__main__":
    unittest.main()
