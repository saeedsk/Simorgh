"""Live 2026-09-19: voice turns took 23-31 s. Together streams stalled and
were waited out for the whole budget, and failover to Gemini hit "Cannot
send a request, as the client has been closed"."""

import asyncio
import unittest
from types import SimpleNamespace

from simorgh.cognition.providers import together
from simorgh.cognition.providers.gemini import GeminiProvider


class TogetherStalls(unittest.TestCase):
    def test_the_socket_carries_the_first_line_budget_not_the_call_budget(self):
        """Waiting for the FIRST line is not the same as a gap between
        two: nothing has been generated yet, the server is reading the
        prompt, and that time grows with the prompt (a chat turn carries
        72 tool schemas). Live 2026-09-22, `no line in 6.1s` abandoned a
        healthy provider for being slow to start. It is still not the
        whole budget -- that was the 2026-09-19 bug above."""
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
        self.assertEqual(seen["timeout"], together.FIRST_LINE_S)
        self.assertLess(seen["timeout"], 90.0, "never the whole budget: that was the 2026-09-19 stall")

    def test_a_gap_between_lines_still_fails_fast(self):
        """The silence rule did not go away -- it moved to where it
        belongs, between lines, enforced by the consumer."""
        import time

        def transport(url, headers, payload, timeout):
            yield 'data: {"choices": [{"delta": {"content": "hi"}}]}\n'
            time.sleep(together.STREAM_SILENCE_S + 2.0)          # ... and then nothing
            yield "data: [DONE]\n"

        provider = together.TogetherProvider(api_key="k", stream_transport=transport)

        async def run():
            out = []
            async for delta in provider.stream([{"role": "user", "content": "x"}], tools=None,
                                               max_tokens=10, timeout=90.0):
                out.append(delta)
            return out

        started = time.monotonic()
        with self.assertRaises(Exception) as caught:      # noqa: PT027 -- ProviderUnavailable is the contract
            asyncio.run(run())
        self.assertIn("quiet after", str(caught.exception))
        self.assertLess(time.monotonic() - started, 20.0, "it must not wait out the budget")


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
