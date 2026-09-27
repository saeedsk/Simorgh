"""Home Assistant is brought back when it cannot be reached.

The creator, 2026-09-27: "why HA is not running, sim should be able to
handle HA run state, if it is not running, sim should be able to recover
and kick start" it. The VM had stopped two days before and UTM's library
had lost it; every home question failed with "Host is down".
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.domains.home import keeper


class _Runner:
    """A fake `utmctl`/`open`/`docker` that remembers what it was asked."""

    def __init__(self, vms: dict[str, str], *, lost: bool = False, container: str | None = None) -> None:
        self.vms, self.lost, self.container, self.calls = dict(vms), lost, container, []

    def __call__(self, args, timeout=30.0):
        self.calls.append(list(args))
        if args[:1] == [keeper.UTMCTL] and args[1] == "list":
            shown = {} if self.lost else self.vms
            rows = [f"UUID{i} {status} {name}" for i, (name, status) in enumerate(shown.items())]
            return 0, "\n".join(["UUID Status Name", *rows])
        if args[:1] == [keeper.UTMCTL] and args[1] == "start":
            self.vms[args[2]] = "started"
            return 0, ""
        if args[0] == "open":
            self.lost = False
            return 0, ""
        if args[:2] == ["docker", "inspect"]:
            return (1, "no such") if self.container is None else (0, self.container)
        if args[:2] == ["docker", "start"]:
            self.container = "true"
            return 0, ""
        return 1, "unexpected"


class Revive(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        keeper.reset()
        self.addCleanup(keeper.reset)
        patcher = mock.patch.object(keeper, "_answers", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.clock = [1000.0]

    async def _revive(self, url, run, **kw):
        return await keeper.revive(url, run=run, clock=lambda: self.clock[0], wait=lambda _url: True, **kw)

    async def test_a_stopped_vm_is_started(self):
        run = _Runner({"Virtual Machine": "stopped"})
        said = await self._revive("http://192.168.50.208", run)
        self.assertIn([keeper.UTMCTL, "start", "Virtual Machine"], run.calls)
        self.assertIn("started the Home Assistant VM 'Virtual Machine'; Home Assistant answers again", said)

    async def test_a_vm_utm_lost_is_added_back_then_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Virtual Machine.utm").mkdir()
            run = _Runner({"Virtual Machine": "stopped"}, lost=True)
            with mock.patch.object(keeper.time, "sleep"):
                said = await self._revive("http://192.168.50.208", run, documents=Path(tmp))
        self.assertIn(["open", str(Path(tmp) / "Virtual Machine.utm")], run.calls)
        self.assertIn("added the VM 'Virtual Machine' back to UTM's library", said)
        self.assertIn("started", said)

    async def test_home_assistant_on_this_machine_is_its_container(self):
        run = _Runner({}, container="false")
        said = await self._revive("http://127.0.0.1:8123", run)
        self.assertIn(["docker", "start", "homeassistant"], run.calls)
        self.assertIn("started the 'homeassistant' container", said)

    async def test_once_per_five_minutes(self):
        run = _Runner({"Virtual Machine": "stopped"})
        self.assertTrue(await self._revive("http://192.168.50.208", run))
        self.clock[0] += 60
        self.assertEqual(await self._revive("http://192.168.50.208", run), "", "tried a minute ago")
        self.clock[0] += keeper.RETRY_AFTER_S
        self.assertTrue(await self._revive("http://192.168.50.208", run))

    async def test_nothing_is_done_while_it_answers(self):
        run = _Runner({"Virtual Machine": "stopped"})
        with mock.patch.object(keeper, "_answers", return_value=True):
            self.assertEqual(await self._revive("http://192.168.50.208", run), "")
        self.assertEqual(run.calls, [])


class TheToolSaysSo(unittest.IsolatedAsyncioTestCase):
    """The call is asked again after the recovery, and the answer says
    Home Assistant was started: a tool that changed the machine says so."""

    async def test_a_home_question_after_a_recovery_is_answered_and_says_what_happened(self):
        import io
        import json
        import urllib.error

        from simorgh.domains.home.tools import HomeFindTool

        calls = []

        def opener(request, timeout=0):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise urllib.error.URLError(OSError(64, "Host is down"))
            body = json.dumps([{"entity_id": "light.kitchen", "state": "off", "attributes": {"friendly_name": "Kitchen"}}])
            response = io.BytesIO(body.encode())
            response.__enter__ = lambda *_: response
            response.__exit__ = lambda *_: None
            return response

        tool = HomeFindTool(config=None, env={"HOME_ASSISTANT_URL": "http://192.168.50.208", "HOME_ASSISTANT_TOKEN": "t"})
        real = tool._client

        def client():
            made = real()
            made._opener = opener
            return made

        tool._client = client
        with mock.patch("simorgh.domains.home.keeper.revive", return_value="started the Home Assistant VM 'Virtual Machine'; Home Assistant answers again"):
            result = await tool.run({"query": "kitchen"}, ctx=None)
        self.assertTrue(result.ok, result.error)
        self.assertIn("Home Assistant was not answering: started the Home Assistant VM", result.output)
        self.assertIn("light.kitchen", result.output)
        self.assertEqual(len(calls), 2, "asked again after the recovery")
