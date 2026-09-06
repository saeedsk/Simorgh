import tempfile
import unittest
from pathlib import Path

from simorgh.bus.enforcement import IdentityRegistry
from simorgh.bus.factory import make_backend
from simorgh.bus.config import Config as BusConfig
from simorgh.kernel.api import MissingSecret, RuntimeConfig
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.context import ContextFactory, HmacSecretStore
from simorgh.kernel.secrets import EnvSecretStore
from tests.simorgh.helpers import FakeClock


def _factory(tmp_path: str, *, raw_config: dict | None = None, secrets=None,
            hmac_secret: bytes = b"\x01" * 32, identity_registry=None) -> ContextFactory:
    return ContextFactory(
        bus_backend=make_backend(BusConfig()),
        ledger=object(),
        config=LoadedConfig(raw_config or {}, None),
        secrets=secrets if secrets is not None else EnvSecretStore({}),
        clock=FakeClock(),
        runtime=RuntimeConfig(data_dir=Path(tmp_path)),
        run_id="run-1",
        hmac_secret=hmac_secret,
        needs_hmac_secret=frozenset({"guardian", "execution"}),
        identity_registry=identity_registry,
    )


class TestContextBasics(unittest.TestCase):
    def test_build_stamps_name_run_id_and_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _factory(tmp).build("cognition")
            self.assertEqual(ctx.name, "cognition")
            self.assertEqual(ctx.run_id, "run-1")
            self.assertEqual(ctx.mode, "single")
            self.assertEqual(ctx.source, "cognition")

    def test_instance_id_is_folded_into_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _factory(tmp).build("cognition", instance_id="2")
            self.assertEqual(ctx.instance_id, "2")
            self.assertEqual(ctx.source, "cognition@2")

    def test_data_dir_is_created_under_runtime_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _factory(tmp).build("memory")
            self.assertEqual(ctx.data_dir, Path(tmp) / "memory")
            self.assertTrue(ctx.data_dir.is_dir())

    def test_config_section_is_the_subsystems_own_slice(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw = {"cognition": {"model": "x"}, "memory": {"other": 1}}
            ctx = _factory(tmp, raw_config=raw).build("cognition")
            self.assertEqual(ctx.config, {"model": "x"})

    def test_missing_config_section_is_an_empty_dict_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _factory(tmp).build("unconfigured-subsystem")
            self.assertEqual(ctx.config, {})

    def test_no_identity_registry_leaves_subsystem_token_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _factory(tmp).build("cognition")
            self.assertEqual(ctx.subsystem_token, "")

    def test_identity_registry_issues_a_nonempty_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IdentityRegistry(secret=b"\x03" * 32, run_id="run-1")
            ctx = _factory(tmp, identity_registry=registry).build("cognition")
            self.assertTrue(ctx.subsystem_token)


class TestSecretScoping(unittest.TestCase):
    def test_a_subsystem_with_no_declared_secrets_can_read_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets = EnvSecretStore({"GEMINI_API_KEY": "xyz"})
            ctx = _factory(tmp, secrets=secrets).build("cognition")
            self.assertIsNone(ctx.secrets.get("GEMINI_API_KEY"))
            with self.assertRaises(MissingSecret):
                ctx.secrets.require("GEMINI_API_KEY")

    def test_a_subsystem_that_declares_a_secret_can_read_only_that_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets = EnvSecretStore({"GEMINI_API_KEY": "xyz", "OTHER_KEY": "abc"})
            raw = {"cognition": {"secrets": ["GEMINI_API_KEY"]}}
            ctx = _factory(tmp, raw_config=raw, secrets=secrets).build("cognition")
            self.assertEqual(ctx.secrets.get("GEMINI_API_KEY"), "xyz")
            self.assertIsNone(ctx.secrets.get("OTHER_KEY"))

    def test_guardian_and_execution_can_read_the_hmac_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            factory = _factory(tmp, hmac_secret=b"\xab" * 32)
            for name in ("guardian", "execution"):
                ctx = factory.build(name)
                self.assertEqual(ctx.secrets.get("__hmac__"), (b"\xab" * 32).hex())

    def test_a_subsystem_not_declaring_hmac_cannot_read_it_even_though_it_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            ctx = _factory(tmp).build("curiosity")
            self.assertIsNone(ctx.secrets.get("__hmac__"))
            with self.assertRaises(MissingSecret):
                ctx.secrets.require("__hmac__")

    def test_hmac_subsystem_also_keeps_access_to_its_declared_ordinary_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            secrets = EnvSecretStore({"TOOL_KEY": "t"})
            raw = {"execution": {"secrets": ["TOOL_KEY"]}}
            ctx = _factory(tmp, raw_config=raw, secrets=secrets).build("execution")
            self.assertEqual(ctx.secrets.get("TOOL_KEY"), "t")
            self.assertEqual(ctx.secrets.get("__hmac__"), (b"\x01" * 32).hex())


class TestHmacSecretStore(unittest.TestCase):
    def test_hmac_name_returns_hex_without_touching_backing_store(self):
        backing = EnvSecretStore({})
        store = HmacSecretStore(backing, b"\x02" * 4)
        self.assertEqual(store.get("__hmac__"), (b"\x02" * 4).hex())

    def test_other_names_delegate_to_the_backing_store(self):
        backing = EnvSecretStore({"K": "v"})
        store = HmacSecretStore(backing, b"\x00")
        self.assertEqual(store.get("K"), "v")

    def test_require_raises_missing_secret_when_absent(self):
        store = HmacSecretStore(EnvSecretStore({}), b"\x00")
        with self.assertRaises(MissingSecret):
            store.require("NOPE")

    def test_none_hmac_secret_makes_the_hmac_name_absent_too(self):
        store = HmacSecretStore(EnvSecretStore({}), None)
        self.assertIsNone(store.get("__hmac__"))


if __name__ == "__main__":
    unittest.main()
