"""Live 2026-09-19: voice turns took 23-31 s. Together streams stalled and
were waited out for the whole budget, and failover to Gemini hit "Cannot
send a request, as the client has been closed"."""

import asyncio
import unittest
from types import SimpleNamespace

from simorgh.cognition.providers import together
from simorgh.cognition.providers.gemini import GeminiProvider


class TogetherStalls(unittest.TestCase):
    def test_the_socket_timeout_is_the_silence_limit_not_the_budget(self):
        seen = {}

        def transport(url, headers, payload, timeout):
            seen["timeout"] = timeout
            yield 'data: {"choices": [{"delta": {"content": "hi"}}]}\n'
            yield "data: [DONE]\n"

        provider = together.TogetherProvider(api_key="k", stream_transport=transport)

        async def run():
            return [d async for d in provider.stream([{"role": "user", "content": "x"}], tools=None,
                                                     max_tokens=10, timeout=90.0)]

        asyncio.run(run())
        self.assertEqual(seen["timeout"], together.STREAM_SILENCE_S)


class GeminiClosedClient(unittest.TestCase):
    def test_a_closed_client_is_replaced_once(self):
        calls = []

        class _Models:
            def __init__(self, closed):
                self.closed = closed

            def generate_content(self, **kw):
                calls.append(self.closed)
                if self.closed:
                    raise RuntimeError("Cannot send a request, as the client has been closed.")
                return SimpleNamespace(text="hello", usage_metadata=None, candidates=[])

        provider = GeminiProvider(api_key="k", client=SimpleNamespace(models=_Models(True)))
        provider._get_client = lambda: provider._client or SimpleNamespace(models=_Models(False))  # noqa: SLF001
        response = provider._complete_sync("hi")  # noqa: SLF001
        self.assertEqual(response.text, "hello")
        self.assertEqual(calls, [True, False])


if __name__ == "__main__":
    unittest.main()
