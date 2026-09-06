"""Proves the dashboard's `/api/chat` endpoint (`simorgh/interface/
httpapi.py`) end to end over a REAL Kernel -- real bus, real contract
validation, real Cognition/Orchestration/Interface `Service`s, a real
socket. This is deliberately not just unit tests against a fake bus:
the very first live use of this endpoint hit a real bug (`channel:
"dashboard"` is not a member of `percept.text.received`'s closed
`channel` enum) that every unit test in `tests/simorgh/interface/
test_httpapi.py` missed completely, because its `_FakeBus` never
validates a published message the way a real `BusClient.publish()`
does. Only Cognition's *provider* is fake here (no real subprocess/
network call is allowed in this suite) -- everything else, including
message validation, is the real thing.
"""

from __future__ import annotations

import asyncio
import http.client
import tempfile
import unittest
from unittest import mock

from simorgh.cognition.config import Config as CognitionConfig
from simorgh.cognition.service import Service as CognitionService
from simorgh.contracts.protocols import ProviderResponse
from simorgh.interface.config import Config as InterfaceConfig
from simorgh.interface.service import Service as InterfaceService
from simorgh.kernel import registry as kernel_registry
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel
from simorgh.kernel.state import RUNNING
from tests.simorgh.helpers import FakeClock


class _FakeProvider:
    name = "fake_llm"

    def available(self) -> bool:
        return True

    async def complete(self, messages, *, tools, max_tokens, timeout=None):
        return ProviderResponse(text="hello from the real pipeline", provider=self.name, cost_usd=0.0)


def _patched_build_factories():
    real = kernel_registry.build_factories

    def _build(*, bus_client, ledger_client, run_repl=False):
        factories = real(bus_client=bus_client, ledger_client=ledger_client, run_repl=run_repl)
        factories["cognition"] = lambda: CognitionService(
            config=CognitionConfig(provider_order=("fake_llm", "floor"), assembly_request_timeout=0.05),
            providers=[_FakeProvider()],
        )
        factories["interface"] = lambda: InterfaceService(
            InterfaceConfig(http_port=0, http_chat_timeout_s=5.0), run_repl=False, http_enabled=True,
        )
        return factories

    return _build


class TestDashboardChatEndpoint(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        config = LoadedConfig({"runtime": {"data_dir": self._tmp.name}}, None)
        self.kernel = Kernel(config, secrets=EnvSecretStore({}), clock=FakeClock())
        self._patch = mock.patch("simorgh.kernel.service.build_factories", new=_patched_build_factories())
        self._patch.start()
        await self.kernel.boot()
        self.assertEqual(self.kernel.state.state, RUNNING)
        iface = self.kernel._supervisor.services["interface"].service  # noqa: SLF001
        self.assertIsNotNone(iface._http)  # noqa: SLF001
        self.port = iface._http.port  # noqa: SLF001

    async def asyncTearDown(self) -> None:
        await self.kernel.shutdown()
        self._patch.stop()
        self._tmp.cleanup()

    async def _post_chat(self, text: str, session_id: str | None = None) -> tuple[int, dict]:
        import json

        def _do():
            body = {"text": text}
            if session_id is not None:
                body["session_id"] = session_id
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("POST", "/api/chat", body=json.dumps(body),
                        headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = resp.read()
            conn.close()
            return resp.status, json.loads(data)

        return await asyncio.to_thread(_do)

    async def test_chat_over_a_real_socket_against_a_real_kernel_returns_a_real_reply(self):
        status, body = await self._post_chat("hello Simorgh")
        self.assertEqual(status, 200, body)  # was a real 500 before the channel-enum fix
        self.assertEqual(body["text"], "hello from the real pipeline")
        self.assertFalse(body["floor"])

    async def test_the_percept_this_endpoint_publishes_is_contract_valid(self):
        """The actual regression: `channel` must be a real member of the
        wire enum (cli|api|chat|command), or `BusClient.publish()`'s own
        `validate()` raises and the request 500s -- confirmed here via
        the real, successful round trip rather than inspecting internals."""
        status, _body = await self._post_chat("does this validate")
        self.assertEqual(status, 200)

    async def test_a_client_supplied_session_id_reaches_memorys_real_episodic_write(self):
        """02-system-architecture.md section 6.1: a client-supplied
        session_id is the multi-session direction's first real step --
        proven here against the *real* Memory subsystem (milestone 105's
        episodic write on turn.completed), not just checked as a field
        on the outgoing percept."""
        status, _body = await self._post_chat("remember this exchange", session_id="dashboard-conv-1")
        self.assertEqual(status, 200)

        from simorgh.contracts import topics
        from simorgh.contracts.envelope import Message

        reply = await self.kernel.bus.request(Message.new(
            topics.MEMORY_RETRIEVE, source="test",
            payload={"query": "remember this exchange", "kinds": ["episodic"], "k": 5},
        ), timeout=5.0)
        items = reply.payload["items"]
        self.assertTrue(any("remember this exchange" in i["content"] for i in items))


if __name__ == "__main__":
    unittest.main()
