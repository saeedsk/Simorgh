"""`POST /api/action`: what a paired device may ask the house to do.

Stage 12 item 3a. Every write the phone's control tabs need is a TOOL, and
tools were reachable only from a conversation or the REPL -- so the tabs
had nothing to call. The mechanism already existed: `_run_for_page`
proposes a tool "the way the terminal does: a proposal Guardian sees, the
result read back". It was wired to a handful of hardcoded camera routes
and never exposed generically.

The allowlist is the point of this file. Guardian gates EFFECTS -- it
weighs a proposal on its merits, and this house auto-approves irreversible
ones. `ACTION_TOOLS` gates SURFACE: what a network request may propose at
all. Without it, a stolen phone token could ask for `run_shell` and
Guardian would weigh it as a legitimate request, because from its side it
is one.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from simorgh.interface.devices import DeviceBook
from simorgh.interface.httpapi import ACTION_TOOLS, HttpApi


class TheActionRoute(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.book = DeviceBook(Path(self._tmp.name) / "devices.json")
        self.asked: list[tuple[str, dict]] = []

        async def _run(tool: str, args: dict, timeout: float):
            self.asked.append((tool, args))
            return 200, json.dumps({"text": "done"}).encode(), "application/json"

        self.api = HttpApi(bus=None, ledger=None, token="shared", devices=self.book)
        self.api._run_for_page = _run                                  # noqa: SLF001

    def _token(self, *, capabilities=("read", "chat", "control")) -> str:
        pending = self.book.begin_pairing(name="iPhone", capabilities=capabilities)
        _, token = self.book.redeem(pending.code)
        return token

    async def _post(self, body: dict, token: str | None):
        handler = self.api._routes[("POST", "/api/action")].handler     # noqa: SLF001
        headers = {"authorization": f"Bearer {token}"} if token else {}
        status, payload, _ = await handler({}, json.dumps(body).encode(), headers)
        return status, json.loads(payload)

    # ------------------------------------------------------------ allowed
    async def test_an_allowed_tool_is_proposed(self):
        status, body = await self._post({"tool": "home_call", "args": {"target": "kitchen", "action": "on"}},
                                        self._token())
        self.assertEqual(status, 200, body)
        self.assertEqual(self.asked, [("home_call", {"target": "kitchen", "action": "on"})])

    async def test_no_args_is_fine(self):
        status, _ = await self._post({"tool": "home_state"}, self._token())
        self.assertEqual(status, 200)
        self.assertEqual(self.asked[-1], ("home_state", {}))

    # ------------------------------------------------------------ refused
    async def test_a_tool_that_runs_code_is_refused_by_name(self):
        """The one that matters. Guardian would weigh this as legitimate."""
        for tool in ("run_shell", "apply_source_patch", "install_package",
                     "run_script", "run_python_sandboxed"):
            status, body = await self._post({"tool": tool, "args": {}}, self._token())
            self.assertEqual(status, 403, tool)
            self.assertEqual(body["error"]["code"], "not_over_the_wire")
            self.assertIn(tool, body["error"]["detail"])
        self.assertEqual(self.asked, [], "something was proposed anyway")

    async def test_sending_is_not_on_the_list_either(self):
        """`notify` is irreversible and reaches people; a phone asking the
        house to message somebody is not house control."""
        status, _ = await self._post({"tool": "notify", "args": {"body": "hi"}}, self._token())
        self.assertEqual(status, 403)

    async def test_a_device_without_control_is_refused_and_told_the_word(self):
        status, body = await self._post({"tool": "home_call", "args": {}},
                                        self._token(capabilities=("read", "chat")))
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["capability"], "control")
        self.assertIn("with control", body["error"]["detail"])
        self.assertEqual(self.asked, [])

    async def test_no_token_does_nothing(self):
        status, _ = await self._post({"tool": "home_call", "args": {}}, None)
        self.assertEqual(status, 403)
        self.assertEqual(self.asked, [])

    async def test_rubbish_is_a_400(self):
        handler = self.api._routes[("POST", "/api/action")].handler     # noqa: SLF001
        token = self._token()
        status, _, _ = await handler({}, b"{not json", {"authorization": f"Bearer {token}"})
        self.assertEqual(status, 400)
        status, body = await self._post({"tool": "home_call", "args": "kitchen"}, token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(json.dumps(body))["error"]["code"], "invalid_args")

    # ------------------------------------------------------------- shape
    def test_the_allowlist_holds_the_house_and_nothing_that_writes_code(self):
        for wanted in ("home_call", "cam_stream", "media_control", "cast_show", "cancel_task"):
            self.assertIn(wanted, ACTION_TOOLS)
        for refused in ("run_shell", "apply_source_patch", "install_package", "propose_mcp_server",
                        "notify", "memory_forget", "remember", "sim_command", "start_task"):
            self.assertNotIn(refused, ACTION_TOOLS, refused)

    def test_the_route_needs_a_token(self):
        self.assertTrue(self.api._routes[("POST", "/api/action")].auth)  # noqa: SLF001

    def test_it_did_not_join_the_open_write_routes(self):
        open_writes = [(m, path) for (m, path), route in self.api._routes.items()   # noqa: SLF001
                       if m != "GET" and not route.auth]
        self.assertEqual(open_writes, [("POST", "/api/pair")])
