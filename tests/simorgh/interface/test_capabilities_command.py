"""The `capabilities` command, and re-probing after an install.

Half the toolset stands on something outside this repository -- Node, a
bundled Chromium, an optional pip package, a Docker daemon. Execution
has probed all of it since boot and written the answers to the ledger.
Nothing ever read them back, so "is this machine able to do X" was
answerable only by asking Sim to do X and watching it fail.

The second half matters as much: probes ran ONCE, at boot. So
`install_package` could install puppeteer and the system went on
reporting it missing until a restart -- the worst version of the bug the
probes exist to fix, where Sim does the resourceful thing and is still
told it cannot.
"""

from __future__ import annotations

import unittest

from simorgh.contracts.envelope import Event
from simorgh.execution.capabilities import CAPABILITIES_STREAM
from simorgh.interface.dispatch import _capabilities_command
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock


def _probed(name, ok, detail="", tools=()):
    return Event(
        stream=CAPABILITIES_STREAM, type="probed", ts=0.0, trace_id="", causation_id=None,
        idempotency_key=f"{name}-{ok}-{detail}",
        payload={"name": name, "ok": ok, "detail": detail, "cost": "free", "tools": list(tools)},
    )


class CapabilitiesCommandTestCase(unittest.IsolatedAsyncioTestCase):
    async def _ledger(self, events=()):
        ledger = make_ledger({"backend": "memory"}, clock=FakeClock())
        await ledger.start()
        for event in events:
            await ledger.append(CAPABILITIES_STREAM, event)
        return ledger

    async def test_before_any_probe_it_says_so_rather_than_claiming_nothing_works(self):
        outcome = await _capabilities_command(await self._ledger())
        self.assertIn("no capability probes recorded yet", outcome.text)

    async def test_it_reports_each_probe_and_a_count(self):
        ledger = await self._ledger([
            _probed("node", True, "/usr/bin/node"),
            _probed("docker", False, "daemon not running", tools=("run_container",)),
        ])
        text = (await _capabilities_command(ledger)).text
        self.assertIn("1/2 capabilities available", text)
        self.assertIn("missing: docker", text)
        self.assertIn("daemon not running", text)

    async def test_it_names_the_tools_a_missing_capability_costs(self):
        # "docker is missing" is only useful if you know what stops working.
        ledger = await self._ledger([_probed("docker", False, "no daemon", tools=("run_container",))])
        self.assertIn("run_container", (await _capabilities_command(ledger)).text)

    async def test_the_latest_probe_wins(self):
        # The stream is append-only and re-probed after an install, so a
        # capability that has just appeared must not still read missing.
        ledger = await self._ledger([
            _probed("puppeteer", False, "not installed"),
            _probed("puppeteer", True, "puppeteer 25.8.0"),
        ])
        text = (await _capabilities_command(ledger)).text
        self.assertIn("1/1 capabilities available", text)
        self.assertNotIn("missing", text)
        self.assertIn("25.8.0", text)

    async def test_an_unreadable_ledger_is_a_message_not_a_crash(self):
        class _Broken:
            async def read(self, _stream):
                raise OSError("disk gone")

        outcome = await _capabilities_command(_Broken())
        self.assertIn("could not read", outcome.text)
        self.assertFalse(outcome.exit_repl)

    async def test_it_is_a_recognised_command(self):
        from simorgh.interface.parser import COMMAND_NAMES

        self.assertIn("capabilities", COMMAND_NAMES)

    def test_the_help_text_lists_it(self):
        from simorgh.interface.render import _QUICK_COMMANDS

        self.assertIn("capabilities", [name for name, _ in _QUICK_COMMANDS])


class ReprobeTestCase(unittest.TestCase):
    """`_reprobe_after` -- probes ran once at boot and never again."""

    class _Service:
        from simorgh.execution.service import Service as _Real

        _reprobe_after = _Real._reprobe_after

        def __init__(self, running=False):
            self.started = 0
            self._probe_task = _FakeTask(done=not running) if running is not None else None

        def _probe_capabilities(self):
            self.started += 1
            return _noop()

    def test_a_successful_install_triggers_a_reprobe(self):
        import asyncio

        service = self._Service(running=False)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run(service, "install_package", True))
        finally:
            loop.close()
        self.assertEqual(service.started, 1)

    def test_a_failed_install_does_not(self):
        import asyncio

        service = self._Service(running=False)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run(service, "install_package", False))
        finally:
            loop.close()
        self.assertEqual(service.started, 0)

    def test_an_unrelated_tool_does_not(self):
        import asyncio

        service = self._Service(running=False)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run(service, "read_file", True))
        finally:
            loop.close()
        self.assertEqual(service.started, 0)

    def test_a_probe_already_running_is_not_duplicated(self):
        import asyncio

        service = self._Service(running=True)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run(service, "install_package", True))
        finally:
            loop.close()
        self.assertEqual(service.started, 0)

    async def _run(self, service, tool, ok):
        service._reprobe_after(tool, ok)


class _FakeTask:
    def __init__(self, done):
        self._done = done

    def done(self):
        return self._done


async def _noop():
    return None


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class StreamNameAgreementTestCase(unittest.TestCase):
    """`interface` may not import `execution` (the subsystem-isolation
    rule), so the ledger stream name is a plain string agreement in two
    places -- exactly like MCP_PROPOSALS_STREAM. This is the test that
    keeps them in step; without it the command silently reads an empty
    stream and reports "no probes recorded yet" forever.

    It has already earned its place: the first version of the constant
    read "execution:capabilities" and the real one is "capabilities".
    """

    def test_the_two_constants_match(self):
        from simorgh.execution.capabilities import CAPABILITIES_STREAM as theirs
        from simorgh.interface.dispatch import CAPABILITIES_STREAM as ours

        self.assertEqual(ours, theirs)

    def test_the_mcp_stream_agreement_still_holds_too(self):
        from simorgh.execution.tools import MCP_PROPOSALS_STREAM as theirs
        from simorgh.interface.dispatch import MCP_PROPOSALS_STREAM as ours

        self.assertEqual(ours, theirs)
