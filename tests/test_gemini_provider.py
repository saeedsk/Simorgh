import os
import unittest
from unittest import mock

from src.cognition.gemini_provider import GeminiProvider
from src.cognition.provider import ProviderUnavailable


class FakeUsage:
    def __init__(self, prompt_tokens: int, output_tokens: int):
        self.prompt_token_count = prompt_tokens
        self.candidates_token_count = output_tokens


class FakeResponse:
    def __init__(self, text: str, prompt_tokens: int = 10, output_tokens: int = 20):
        self.text = text
        self.usage_metadata = FakeUsage(prompt_tokens, output_tokens)


class FakeModels:
    def __init__(self, response=None, exception=None):
        self._response = response
        self._exception = exception
        self.calls = []

    def generate_content(self, model, contents):
        self.calls.append((model, contents))
        if self._exception is not None:
            raise self._exception
        return self._response


class FakeClient:
    def __init__(self, models: FakeModels):
        self.models = models


class TestGeminiProviderAvailability(unittest.TestCase):
    def test_available_with_explicit_key(self):
        provider = GeminiProvider(api_key="explicit-key")
        self.assertTrue(provider.available())

    def test_unavailable_without_any_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = GeminiProvider(api_key=None)
            self.assertFalse(provider.available())

    def test_available_via_env_var(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "from-env"}, clear=True):
            provider = GeminiProvider()
            self.assertTrue(provider.available())


class TestGeminiProviderComplete(unittest.TestCase):
    def test_complete_returns_text_and_token_metadata(self):
        fake_client = FakeClient(FakeModels(response=FakeResponse("hello!", 15, 25)))
        provider = GeminiProvider(api_key="k", client=fake_client)

        response = provider.complete("hi")

        self.assertEqual(response.text, "hello!")
        self.assertEqual(response.provider_name, "gemini")
        self.assertEqual(response.metadata["input_tokens"], 15)
        self.assertEqual(response.metadata["output_tokens"], 25)

    def test_complete_calls_generate_content_with_prompt_and_model(self):
        fake_models = FakeModels(response=FakeResponse("ok"))
        provider = GeminiProvider(
            api_key="k", model="gemini-custom", client=FakeClient(fake_models)
        )

        provider.complete("what is 2+2?")

        self.assertEqual(fake_models.calls, [("gemini-custom", "what is 2+2?")])

    def test_complete_raises_provider_unavailable_without_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            provider = GeminiProvider(api_key=None)
            with self.assertRaises(ProviderUnavailable):
                provider.complete("hi")

    def test_complete_wraps_sdk_exceptions_as_provider_unavailable(self):
        fake_client = FakeClient(FakeModels(exception=RuntimeError("rate limited")))
        provider = GeminiProvider(api_key="k", client=fake_client)

        with self.assertRaises(ProviderUnavailable):
            provider.complete("hi")

    def test_complete_wraps_client_construction_failure_as_provider_unavailable(self):
        # Regression test: _get_client() (the lazy `from google import
        # genai` import + client construction) used to run outside the
        # try/except in complete(), so a missing/broken google-genai
        # install raised a raw ImportError straight out of complete(),
        # uncaught by CognitionRouter -- breaking the whole fallback chain
        # instead of degrading to the next provider.
        provider = GeminiProvider(api_key="k")
        provider._get_client = mock.Mock(
            side_effect=ImportError("cannot import name 'genai' from 'google'")
        )

        with self.assertRaises(ProviderUnavailable):
            provider.complete("hi")

    def test_missing_usage_metadata_defaults_to_zero_tokens(self):
        response = FakeResponse("ok")
        response.usage_metadata = None
        fake_client = FakeClient(FakeModels(response=response))
        provider = GeminiProvider(api_key="k", client=fake_client)

        result = provider.complete("hi")

        self.assertEqual(result.metadata["input_tokens"], 0)
        self.assertEqual(result.metadata["output_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
