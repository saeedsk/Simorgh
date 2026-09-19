"""Stage 2 item 3: every provider says what its API can do."""

import unittest

from simorgh.cognition.api import Capabilities, capabilities_of
from simorgh.cognition.providers.base import FloorProvider
from simorgh.cognition.providers.claude_code import ClaudeCodeProvider
from simorgh.cognition.providers.gemini import GeminiProvider
from simorgh.cognition.providers.ollama import OllamaProvider
from simorgh.cognition.providers.together import TogetherProvider


class EveryProviderSaysWhatItCanDo(unittest.TestCase):
    def test_the_floor_and_the_cli_wrapper_have_no_native_tools(self):
        self.assertFalse(capabilities_of(FloorProvider()).supports_tools)
        self.assertFalse(capabilities_of(ClaudeCodeProvider()).supports_tools)

    def test_the_api_providers_have_native_tools(self):
        for provider in (TogetherProvider(api_key="x"), GeminiProvider(api_key="x"), OllamaProvider(model="m")):
            self.assertTrue(capabilities_of(provider).supports_tools, provider.name)

    def test_ollama_sees_only_with_a_vision_model(self):
        self.assertFalse(capabilities_of(OllamaProvider(model="m")).supports_images)
        self.assertTrue(capabilities_of(OllamaProvider(model="m", vision_model="v")).supports_images)

    def test_an_undeclared_provider_is_assumed_to_do_nothing(self):
        class Bare:
            name = "bare"

        self.assertEqual(capabilities_of(Bare()), Capabilities())
