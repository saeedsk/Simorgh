import unittest

from src.cognition.provider import (
    CognitionRouter,
    DeterministicFallbackProvider,
    LLMResponse,
    ProviderUnavailable,
)


class FlakyProvider:
    name = "flaky"

    def __init__(self, available: bool = True, fails: bool = True):
        self._available = available
        self._fails = fails

    def available(self) -> bool:
        return self._available

    def complete(self, prompt, **kwargs):
        if self._fails:
            raise ProviderUnavailable("simulated outage")
        return LLMResponse(text=f"handled: {prompt}", provider_name=self.name)


class TestDeterministicFallbackProvider(unittest.TestCase):
    def test_always_available_and_never_raises(self):
        provider = DeterministicFallbackProvider()
        self.assertTrue(provider.available())
        response = provider.complete("hello")
        self.assertIn("hello", response.text)
        self.assertTrue(response.metadata["degraded"])


class TestCognitionRouter(unittest.TestCase):
    def test_uses_first_available_successful_provider(self):
        good = FlakyProvider(available=True, fails=False)
        router = CognitionRouter([good, DeterministicFallbackProvider()])

        response = router.complete("hi")

        self.assertEqual(response.provider_name, "flaky")

    def test_falls_back_when_a_provider_is_unavailable(self):
        unavailable = FlakyProvider(available=False)
        router = CognitionRouter([unavailable, DeterministicFallbackProvider()])

        response = router.complete("hi")

        self.assertEqual(response.provider_name, "deterministic_fallback")

    def test_falls_back_when_a_provider_raises(self):
        failing = FlakyProvider(available=True, fails=True)
        router = CognitionRouter([failing, DeterministicFallbackProvider()])

        response = router.complete("hi")

        self.assertEqual(response.provider_name, "deterministic_fallback")

    def test_never_fully_starved_with_fallback_registered(self):
        all_failing = [FlakyProvider(fails=True) for _ in range(3)]
        router = CognitionRouter([*all_failing, DeterministicFallbackProvider()])

        response = router.complete("still here?")

        self.assertEqual(response.provider_name, "deterministic_fallback")

    def test_health_tracks_successes_and_failures(self):
        failing = FlakyProvider(available=True, fails=True)
        router = CognitionRouter([failing, DeterministicFallbackProvider()])

        router.complete("hi")

        health = router.health()
        self.assertEqual(health["flaky"]["failures"], 1)
        self.assertEqual(health["deterministic_fallback"]["successes"], 1)

    def test_default_router_has_working_fallback_only(self):
        router = CognitionRouter()
        response = router.complete("anything")
        self.assertEqual(response.provider_name, "deterministic_fallback")


if __name__ == "__main__":
    unittest.main()
