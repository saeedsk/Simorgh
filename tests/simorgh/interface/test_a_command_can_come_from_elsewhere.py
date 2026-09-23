"""`POST /api/command` -- a typed line from somewhere that is not this
keyboard.

The creator, away from the house on 2026-09-22, asked for Sim to be
restarted and there was no way to say it: `/api/chat` starts a
conversational turn and Telegram becomes a percept, so no channel could
reach `restart` or `run swebench-verified 30`. What this pins is the
shape of the answer, not just that it exists: it runs the line through
the SAME `_handle_line` the keyboard uses (so Guardian gates what
follows), it refuses anything that is not a command, it needs the token,
and it shows the line on Sim's own screen -- a command with no visible
cause is how a household stops trusting the thing in the corner.
"""

import asyncio
import http.client
import json
import unittest

import pytest

from simorgh.interface.httpapi import HttpApi
from simorgh.interface.service import Service

from .test_httpapi import _FakeBus

pytestmark = pytest.mark.contract


class _Logger:
    def __init__(self):
        self.lines = []

    def info(self, event, **kw):
        self.lines.append((event, kw))

    warning = error = debug = info


class RemoteCommands(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = HttpApi(_FakeBus({}), host="127.0.0.1", port=0, token="secret")
        await self.api.start()
        self.addAsyncCleanup(self.api.stop)
        self.service = Service.__new__(Service)          # the route, not a whole boot
        self.service._http = self.api                    # noqa: SLF001
        self.service._ctx = type("Ctx", (), {"logger": _Logger()})()  # noqa: SLF001
        self.printed: list[str] = []
        self.handled: list[str] = []
        self.service._out = self.printed.append           # noqa: SLF001

        async def _guarded(line):
            self.handled.append(line)

        self.service._handle_line_guarded = _guarded      # noqa: SLF001
        self.api.register_route("POST", "/api/command", self.service._command_route, rate=(30, 60.0))  # noqa: SLF001

    async def _post(self, body: dict, *, bearer: str = "secret"):
        def _do():
            conn = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=5)
            headers = {"Content-Type": "application/json"}
            if bearer:
                headers["Authorization"] = f"Bearer {bearer}"
            conn.request("POST", "/api/command", body=json.dumps(body).encode(), headers=headers)
            resp = conn.getresponse()
            resp.body = resp.read()
            conn.close()
            return resp

        return await asyncio.to_thread(_do)

    async def test_a_command_runs_the_same_way_typing_it_would(self):
        resp = await self._post({"line": "benchmark run swebench-verified 30"})
        self.assertIn(resp.status, (200, 202))
        self.assertEqual(json.loads(resp.body)["accepted"], "benchmark")
        await asyncio.sleep(0.05)
        self.assertEqual(self.handled, ["benchmark run swebench-verified 30"],
                         "the keyboard's own path, so Guardian gates what follows")
        self.assertIn("[remote] benchmark run swebench-verified 30", self.printed,
                      "the household sees what was asked for")

    async def test_chat_is_refused_and_pointed_at_the_chat_route(self):
        resp = await self._post({"line": "how are you feeling today"})
        self.assertEqual(resp.status, 400)
        self.assertIn("/api/chat", json.loads(resp.body)["error"]["detail"])
        self.assertEqual(self.handled, [], "never a second, quieter way to talk to Sim")

    async def test_without_the_token_it_is_not_a_remote_control(self):
        resp = await self._post({"line": "restart"}, bearer="")
        self.assertEqual(resp.status, 401)
        await asyncio.sleep(0.05)
        self.assertEqual(self.handled, [])

    async def test_a_shell_line_is_refused(self):
        """`!` is a raw shell with no Guardian in it -- a person's own
        hands at their own keyboard. Over HTTP it would be a remote shell
        on this house."""
        resp = await self._post({"line": "!rm -rf /tmp/whatever"})
        self.assertEqual(resp.status, 400)
        self.assertEqual(json.loads(resp.body)["error"]["code"], "shell_refused")
        await asyncio.sleep(0.05)
        self.assertEqual(self.handled, [])

    async def test_the_answer_comes_back_when_the_command_finishes(self):
        """"202 accepted" is not an answer to `status`. The first thing
        this route could not do, an hour after it existed, was tell its
        own author what `benchmark history` said."""
        from simorgh.contracts import console

        async def _guarded(line):
            self.handled.append(line)
            console.record("suite   runs  best")
            console.record("gaia-1     3   60%")

        self.service._handle_line_guarded = _guarded      # noqa: SLF001
        resp = await self._post({"line": "benchmark history"})
        body = json.loads(resp.body)
        self.assertEqual(resp.status, 200)
        self.assertTrue(body["finished"])
        self.assertIn("gaia-1", body["said"])
        self.assertNotIn("[remote]", body["said"], "the echo is for the screen, not the caller")

    async def test_an_empty_or_unreadable_body_is_refused(self):
        self.assertEqual((await self._post({"line": "   "})).status, 400)
        self.assertEqual(self.handled, [])


if __name__ == "__main__":
    unittest.main()
