"""`TogetherProvider` against a fake transport -- request shape, response
shaping, the cache-aware cost model, and every failure degrading to
`ProviderUnavailable` so the Router simply tries the next candidate.

No test here may touch the network: the provider takes a `transport`
seam, and the one test that does not inject one asserts the *absence* of
a key stops it before any socket is opened.
"""

import json
import unittest

from simorgh.cognition.api import ProviderUnavailable
from simorgh.cognition.providers.together import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    MIN_REASONING_MAX_TOKENS,
    PRICE_CACHED_IN,
    PRICE_IN,
    PRICE_OUT,
    TogetherProvider,
)


def _reply(text="hi", *, prompt=1000, completion=200, cached=None, model=DEFAULT_MODEL) -> str:
    usage = {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}
    if cached is not None:
        usage["prompt_tokens_details"] = {"cached_tokens": cached}
    return json.dumps({
        "id": "x", "model": model,
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": usage,
    })


class _Transport:
    """Records the call and returns a canned body."""

    def __init__(self, body: str | Exception) -> None:
        self.body = body
        self.url = None
        self.headers = None
        self.request = None
        self.timeout = None

    def __call__(self, url, headers, payload, timeout):
        self.url, self.headers, self.timeout = url, headers, timeout
        self.request = json.loads(payload.decode())
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def _provider(transport, **kw) -> TogetherProvider:
    return TogetherProvider(api_key="k-test", transport=transport, **kw)


class TestTheRequest(unittest.IsolatedAsyncioTestCase):
    async def test_it_posts_the_documented_endpoint_model_and_auth_header(self):
        t = _Transport(_reply())
        await _provider(t).complete([{"role": "user", "content": "hello"}], tools=None, max_tokens=512)

        self.assertEqual(t.url, "https://api.together.ai/v1/chat/completions")
        self.assertEqual(t.headers["Authorization"], "Bearer k-test")
        self.assertEqual(t.headers["Content-Type"], "application/json")
        # Live-caught: without a real User-Agent every request came
        # back HTTP 403 "error code: 1010" from Cloudflare, while the
        # identical curl succeeded.
        self.assertIn("Simorgh", t.headers["User-Agent"])
        self.assertNotIn("urllib", t.headers["User-Agent"])
        self.assertEqual(t.request["model"], "zai-org/GLM-5.3-Flash")
        # Raised to the reasoning floor. 512 tokens does not buy a short
        # answer from a reasoning model, it buys no answer at all --
        # thinking comes out of the same budget (see
        # `MIN_REASONING_MAX_TOKENS`).
        self.assertEqual(t.request["max_tokens"], MIN_REASONING_MAX_TOKENS)

    async def test_system_messages_stay_system_messages(self):
        """Cognition's assembler puts the constitution, the voice, the
        self summary and the task rules in `role: "system"` blocks. A
        chat-completions provider must send them as system messages, not
        flatten everything into one user prompt the way the Gemini
        provider has to."""
        t = _Transport(_reply())
        await _provider(t).complete([
            {"role": "system", "content": "you are Sim"},
            {"role": "user", "content": "hello"},
        ], tools=None, max_tokens=64)

        self.assertEqual(
            t.request["messages"],
            [{"role": "system", "content": "you are Sim"}, {"role": "user", "content": "hello"}],
        )

    async def test_empty_content_is_dropped_but_never_leaves_zero_messages(self):
        t = _Transport(_reply())
        await _provider(t).complete([{"role": "user", "content": ""}], tools=None, max_tokens=64)
        self.assertEqual(len(t.request["messages"]), 1)


class TestTheReasoningModel(unittest.IsolatedAsyncioTestCase):
    """GLM-5.3-Flash thinks before it answers, and those tokens are billed
    and counted against `max_tokens`. Measured live 2026-09-07: "say hi in
    five words" spent 204 reasoning tokens before 9 tokens of answer, and
    4 with `reasoning_effort: "low"`."""

    async def test_reasoning_effort_is_sent_on_every_call(self):
        t = _Transport(_reply())
        await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=64)
        self.assertEqual(t.request["reasoning_effort"], DEFAULT_REASONING_EFFORT)

    async def test_the_effort_is_overridable_per_instance(self):
        t = _Transport(_reply())
        await _provider(t, reasoning_effort="high").complete(
            [{"role": "user", "content": "q"}], tools=None, max_tokens=64,
        )
        self.assertEqual(t.request["reasoning_effort"], "high")

    async def test_an_answer_truncated_inside_the_reasoning_is_not_passed_off_as_a_reply(self):
        """Empty `content` with a `reasoning_content` beside it means the
        output budget ran out mid-thought. Returning "" would reach
        Cognition as a real (empty) answer and be parsed as a non-answer;
        failing lets the Router try the next provider."""
        body = json.loads(_reply(prompt=18, completion=200))
        body["choices"][0]["message"] = {"role": "assistant", "reasoning_content": "let me count the words"}
        body["choices"][0]["finish_reason"] = "length"
        t = _Transport(json.dumps(body))
        with self.assertRaises(ProviderUnavailable):
            await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=200)

    async def test_the_truncated_calls_real_usage_is_still_billable(self):
        # Live-caught, 2026-09-08: Together already billed for this call
        # (18 prompt + 200 completion tokens, real reasoning tokens) before
        # deciding the reply itself was unusable. The Router only records
        # spend on the success path, so without `billable` on the raised
        # exception this real cost vanished -- silently undercounting the
        # provider's own rolling-window budget.
        body = json.loads(_reply(prompt=18, completion=200))
        body["choices"][0]["message"] = {"role": "assistant", "reasoning_content": "let me count the words"}
        body["choices"][0]["finish_reason"] = "length"
        t = _Transport(json.dumps(body))
        with self.assertRaises(ProviderUnavailable) as ctx:
            await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=200)
        billable = ctx.exception.billable
        self.assertIsNotNone(billable)
        self.assertEqual(billable.input_tokens, 18)
        self.assertEqual(billable.output_tokens, 200)
        self.assertGreater(billable.cost_usd, 0.0)
        self.assertEqual(billable.text, "")


class TestTheResponse(unittest.IsolatedAsyncioTestCase):
    async def test_it_returns_the_text_and_the_token_counts(self):
        t = _Transport(_reply("the answer", prompt=1000, completion=200))
        got = await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=64)

        self.assertEqual(got.text, "the answer")
        self.assertEqual(got.provider, "together")
        self.assertEqual(got.input_tokens, 1000)
        self.assertEqual(got.output_tokens, 200)

    async def test_cached_prompt_tokens_are_split_out_of_the_input_count(self):
        """Together counts cached tokens inside `prompt_tokens`. Reporting
        both raw would bill the cached part twice."""
        t = _Transport(_reply(prompt=1000, completion=200, cached=800))
        got = await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=64)

        self.assertEqual(got.cached_input_tokens, 800)
        self.assertEqual(got.input_tokens, 200)
        self.assertEqual(got.input_tokens + got.cached_input_tokens, 1000)

    async def test_a_flat_cached_tokens_field_is_read_too(self):
        body = json.loads(_reply(prompt=500, completion=100))
        body["usage"]["cached_tokens"] = 400
        t = _Transport(json.dumps(body))
        got = await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=64)
        self.assertEqual(got.cached_input_tokens, 400)
        self.assertEqual(got.input_tokens, 100)

    async def test_no_cache_information_prices_the_whole_prompt_at_the_input_rate(self):
        t = _Transport(_reply(prompt=1000, completion=0))
        got = await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=64)
        self.assertEqual(got.cached_input_tokens, 0)
        self.assertEqual(got.input_tokens, 1000)


class TestTheCostModel(unittest.TestCase):
    """$0.15 per 1M in, $0.50 per 1M out, $0.03 per 1M cached in."""

    def test_the_published_prices(self):
        self.assertEqual((PRICE_IN, PRICE_OUT, PRICE_CACHED_IN), (0.15, 0.50, 0.03))

    def test_one_million_of_each_tier(self):
        self.assertAlmostEqual(TogetherProvider.price(1_000_000, 0, 0), 0.15)
        self.assertAlmostEqual(TogetherProvider.price(0, 1_000_000, 0), 0.50)
        self.assertAlmostEqual(TogetherProvider.price(0, 0, 1_000_000), 0.03)

    def test_a_realistic_call_with_a_warm_cache(self):
        # 20k prompt of which 16k cached, 2k out:
        # 4_000*0.15/1e6 + 2_000*0.50/1e6 + 16_000*0.03/1e6
        self.assertAlmostEqual(TogetherProvider.price(4_000, 2_000, 16_000), 0.00208)

    def test_a_cold_cache_costs_more_than_a_warm_one_for_the_same_prompt(self):
        cold = TogetherProvider.price(20_000, 2_000, 0)
        warm = TogetherProvider.price(4_000, 2_000, 16_000)
        self.assertGreater(cold, warm)


class TestFailuresDegradeRatherThanRaise(unittest.IsolatedAsyncioTestCase):
    async def test_no_api_key_is_unavailable_and_never_opens_a_socket(self):
        provider = TogetherProvider(api_key="")
        self.assertFalse(provider.available())
        with self.assertRaises(ProviderUnavailable):
            await provider.complete([{"role": "user", "content": "q"}], tools=None, max_tokens=8)

    async def test_a_transport_error_becomes_provider_unavailable(self):
        t = _Transport(OSError("connection reset"))
        with self.assertRaises(ProviderUnavailable):
            await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=8)

    async def test_a_non_json_body_becomes_provider_unavailable(self):
        t = _Transport("<html>502 Bad Gateway</html>")
        with self.assertRaises(ProviderUnavailable):
            await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=8)

    async def test_a_body_with_no_choices_becomes_provider_unavailable(self):
        t = _Transport(json.dumps({"error": {"message": "model not found"}}))
        with self.assertRaises(ProviderUnavailable):
            await _provider(t).complete([{"role": "user", "content": "q"}], tools=None, max_tokens=8)


if __name__ == "__main__":
    unittest.main()
