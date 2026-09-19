"""A provider key kept in secrets.toml reaches the provider.

2026-09-19: the creator put GEMINI_API_KEY in ~/.simorgh/secrets.toml.
GeminiProvider read only os.environ and Cognition had no default secret
scope, so the key was silently ignored and Gemini reported unavailable.
"""
import dataclasses
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from simorgh.cognition.config import Config as CognitionConfig, ProviderConfig
from simorgh.cognition.service import Service
from simorgh.kernel.api import RuntimeConfig
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.context import ContextFactory
from simorgh.kernel.registry import DEFAULT_SECRETS
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.bus.config import Config as BusConfig
from simorgh.bus.factory import make_backend
from simorgh.ledger.factory import make_ledger
from tests.simorgh.helpers import FakeClock

_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "TOGETHER_API_KEY", "ANTHROPIC_API_KEY")


class AKeyInTheSecretsFileReachesGemini(unittest.IsolatedAsyncioTestCase):
    async def test_gemini_is_available_with_the_key_only_in_the_store(self):
        clean_env = {k: v for k, v in os.environ.items() if k not in _KEYS}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, clean_env, clear=True):
            clock = FakeClock()
            ledger = make_ledger({"backend": "memory"}, clock=clock)
            await ledger.start()
            factory = ContextFactory(
                bus_backend=make_backend(BusConfig(backend="memory"), clock=clock), ledger=ledger,
                config=LoadedConfig({}, None), secrets=EnvSecretStore({"GEMINI_API_KEY": "from-the-file"}),
                clock=clock, runtime=RuntimeConfig(data_dir=Path(tmp)), run_id="run-1",
                hmac_secret=b"\x01" * 32, needs_hmac_secret=frozenset(), default_secrets=DEFAULT_SECRETS,
            )
            ctx = factory.build("cognition")
            await ctx.bus.start()
            base = CognitionConfig()
            service = Service(config=dataclasses.replace(
                base, provider_order=("gemini", "floor"),
                providers={**base.providers, "gemini": ProviderConfig(max_calls=10)},
            ))
            await service.start(ctx)
            try:
                gemini = [p for p in service._real_providers if p.name == "gemini"]
                self.assertEqual(len(gemini), 1)
                self.assertTrue(gemini[0].available(), "the key in the store did not reach GeminiProvider")
            finally:
                await service.stop()
                await ctx.bus.stop()

    def test_the_real_table_scopes_every_provider_key_to_cognition(self):
        for key in _KEYS:
            self.assertIn(key, DEFAULT_SECRETS["cognition"])


if __name__ == "__main__":
    unittest.main()
