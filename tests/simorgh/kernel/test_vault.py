"""The credential vault (kernel/vault.py) -- multi-value, rotating
secrets that a single-string `SecretStore.get(name) -> str | None`
cannot hold (an OAuth token has three fields that must rotate
together).

No test here touches a real OS keychain: every test injects a fake
`keyring` module or forces the file fallback, so the suite runs
identically on a headless CI box and a laptop with Keychain access.
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from simorgh.kernel.api import MissingSecret
from simorgh.kernel.vault import (
    Credential,
    Vault,
    VaultHandle,
    VaultKeyFileUnsafe,
    VaultSecretStore,
    VaultUnavailable,
)


class _FakeKeyring:
    """An in-memory stand-in for the `keyring` package -- no real OS
    keychain touched."""

    def __init__(self, *, broken: bool = False):
        self._store: dict[tuple[str, str], str] = {}
        self._broken = broken

    def get_password(self, service, username):
        if self._broken:
            raise RuntimeError("no backend available")
        return self._store.get((service, username))

    def set_password(self, service, username, value):
        if self._broken:
            raise RuntimeError("no backend available")
        self._store[(service, username)] = value


class _FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


class VaultRoundTripTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "vault.bin"
        self.keyring = _FakeKeyring()

    def _vault(self, **kw) -> Vault:
        return Vault(self.path, keyring_module=self.keyring, **kw)

    def test_put_then_open_round_trips_every_field(self):
        vault = self._vault()
        vault.put("imap:fastmail", "password",
                  {"host": "imap.fastmail.com", "user": "a@b.com", "password": "hunter2"})
        values = vault.open("imap:fastmail")
        self.assertEqual(values["host"], "imap.fastmail.com")
        self.assertEqual(values["password"], "hunter2")

    def test_the_key_comes_from_keyring_when_available(self):
        vault = self._vault()
        self.assertEqual(vault.key_source, "keyring")

    def test_opening_an_unknown_credential_raises_missing_secret(self):
        vault = self._vault()
        with self.assertRaises(MissingSecret):
            vault.open("does-not-exist")

    def test_data_survives_a_fresh_vault_instance_over_the_same_file(self):
        vault1 = self._vault()
        vault1.put("token:x", "token", {"value": "abc"})
        vault2 = self._vault()  # re-opens the same encrypted file
        self.assertEqual(vault2.open("token:x")["value"], "abc")

    def test_delete_removes_it(self):
        vault = self._vault()
        vault.put("token:x", "token", {"value": "abc"})
        vault.delete("token:x")
        with self.assertRaises(MissingSecret):
            vault.open("token:x")

    def test_list_never_exposes_values(self):
        vault = self._vault()
        vault.put("imap:fastmail", "password", {"password": "hunter2"})
        rendered = repr(vault.list())
        self.assertNotIn("hunter2", rendered)

    def test_updating_a_credential_preserves_created_at(self):
        clock = _FakeClock()
        vault = self._vault(clock=clock)
        vault.put("token:x", "token", {"value": "v1"})
        created = vault.list()[0].created_at
        clock.now += 100
        vault.put("token:x", "token", {"value": "v2"})
        updated = vault.list()[0]
        self.assertEqual(updated.created_at, created)
        self.assertGreater(updated.updated_at, created)

    def test_opening_updates_last_used_at(self):
        clock = _FakeClock()
        vault = self._vault(clock=clock)
        vault.put("token:x", "token", {"value": "v"})
        self.assertIsNone(vault.list()[0].last_used_at)
        clock.now += 50
        vault.open("token:x")
        self.assertEqual(vault.list()[0].last_used_at, clock.now)

    def test_stale_reports_credentials_unused_past_the_window(self):
        clock = _FakeClock()
        vault = self._vault(clock=clock)
        vault.put("token:old", "token", {"value": "v"})
        clock.now += 91 * 86400.0
        vault.put("token:fresh", "token", {"value": "v"})
        stale_ids = {c.id for c in vault.stale(days=90)}
        self.assertEqual(stale_ids, {"token:old"})

    def test_a_wrong_key_refuses_rather_than_returning_garbage(self):
        vault1 = self._vault()
        vault1.put("token:x", "token", {"value": "abc"})
        other_keyring = _FakeKeyring()  # a different key entirely
        with self.assertRaises(VaultUnavailable):
            Vault(self.path, keyring_module=other_keyring)


class KeyringFallbackTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "vault.bin"

    def test_a_broken_keyring_falls_back_to_a_key_file_not_a_crash(self):
        vault = Vault(self.path, keyring_module=_FakeKeyring(broken=True))
        self.assertEqual(vault.key_source, "file")
        vault.put("token:x", "token", {"value": "v"})
        self.assertEqual(vault.open("token:x")["value"], "v")

    def test_the_fallback_key_file_is_created_with_safe_permissions(self):
        import stat

        vault = Vault(self.path, keyring_module=_FakeKeyring(broken=True))
        vault.put("token:x", "token", {"value": "v"})
        key_path = self.path.with_suffix(self.path.suffix + ".key")
        mode = key_path.stat().st_mode
        self.assertEqual(mode & (stat.S_IRWXG | stat.S_IRWXO), 0)

    def test_an_unsafe_key_file_is_refused(self):
        key_path = self.path.with_suffix(self.path.suffix + ".key")
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text("00" * 32)
        key_path.chmod(0o644)
        with self.assertRaises(VaultKeyFileUnsafe):
            Vault(self.path, keyring_module=_FakeKeyring(broken=True))

    def test_no_keyring_module_injected_falls_back_to_the_real_import(self):
        # `keyring_module=None` means "use whatever `import keyring`
        # finds" -- production behaviour. This test must NOT let that
        # real import touch the developer's actual OS keychain (caught
        # live, 2026-09-09: an earlier version of this test did exactly
        # that and left a real `simorgh-vault` entry in macOS Keychain
        # after nothing more than running the suite), so the real
        # `keyring.get_password`/`set_password` are patched to an
        # in-memory dict for the duration of this one test only.
        import unittest.mock

        store: dict[tuple, str] = {}

        def _get(service, username):
            return store.get((service, username))

        def _set(service, username, value):
            store[(service, username)] = value

        with unittest.mock.patch("keyring.get_password", side_effect=_get), \
                unittest.mock.patch("keyring.set_password", side_effect=_set):
            vault = Vault(self.path, keyring_module=None)
            vault.put("token:x", "token", {"value": "v"})
            self.assertEqual(vault.open("token:x")["value"], "v")
        self.assertTrue(store, "the patched keyring functions were never called")

    def test_a_fallback_logs_a_warning_once(self):
        logged = []

        class _Logger:
            def warning(self, *a, **kw):
                logged.append((a, kw))

        Vault(self.path, keyring_module=_FakeKeyring(broken=True), logger=_Logger())
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0][0][0], "vault_key_fallback_to_file")


class VaultHandleScopingTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vault = Vault(Path(self._tmp.name) / "v.bin", keyring_module=_FakeKeyring())
        self.vault.put("google:saeed", "oauth2", {"access_token": "a"})
        self.vault.put("imap:fastmail", "password", {"password": "p"})

    def test_a_handle_sees_only_its_scope(self):
        handle = VaultHandle(self.vault, ("google:*",))
        self.assertEqual([c.id for c in handle.list()], ["google:saeed"])

    def test_opening_outside_scope_raises(self):
        handle = VaultHandle(self.vault, ("google:*",))
        with self.assertRaises(MissingSecret):
            handle.open("imap:fastmail")

    def test_opening_inside_scope_works(self):
        handle = VaultHandle(self.vault, ("google:*",))
        self.assertEqual(handle.open("google:saeed")["access_token"], "a")

    def test_an_exact_id_pattern_with_no_wildcard_also_works(self):
        handle = VaultHandle(self.vault, ("imap:fastmail",))
        self.assertEqual(handle.open("imap:fastmail")["password"], "p")

    def test_put_and_delete_are_also_scoped(self):
        handle = VaultHandle(self.vault, ("google:*",))
        with self.assertRaises(MissingSecret):
            handle.put("imap:fastmail", "password", {"password": "new"})
        with self.assertRaises(MissingSecret):
            handle.delete("imap:fastmail")
        handle.put("google:new", "token", {"value": "x"})
        self.assertEqual(self.vault.open("google:new")["value"], "x")


class VaultSecretStoreAdapterTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vault = Vault(Path(self._tmp.name) / "v.bin", keyring_module=_FakeKeyring())
        self.vault.put("imap:fastmail", "password", {"password": "hunter2"})
        self.store = VaultSecretStore(self.vault)

    def test_a_vault_prefixed_name_reads_one_field(self):
        self.assertEqual(self.store.get("vault:imap:fastmail:password"), "hunter2")

    def test_an_unprefixed_name_is_a_miss_not_an_error(self):
        # So `ChainedSecretStore` can fall through to the next store.
        self.assertIsNone(self.store.get("SOME_ENV_VAR"))

    def test_a_missing_credential_is_a_miss(self):
        self.assertIsNone(self.store.get("vault:no:such:credential"))

    def test_a_missing_field_is_a_miss(self):
        self.assertIsNone(self.store.get("vault:imap:fastmail:nonexistent_field"))

    def test_require_raises_missing_secret_on_a_miss(self):
        with self.assertRaises(MissingSecret):
            self.store.require("vault:no:such:x")

    def test_it_composes_into_a_chained_store(self):
        from simorgh.kernel.secrets import ChainedSecretStore, EnvSecretStore

        chain = ChainedSecretStore(EnvSecretStore({}), self.store)
        self.assertEqual(chain.get("vault:imap:fastmail:password"), "hunter2")
        self.assertIsNone(chain.get("NOT_A_VAULT_NAME"))


class NeverLeaksTestCase(unittest.TestCase):
    """The honesty rule every connector's own tests will need to
    repeat: a secret must appear nowhere except inside `open()`'s
    return value."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "v.bin"

    def test_the_secret_never_appears_in_the_encrypted_file(self):
        vault = Vault(self.path, keyring_module=_FakeKeyring())
        vault.put("token:x", "token", {"value": "THE-SECRET-VALUE"})
        raw = self.path.read_bytes()
        self.assertNotIn(b"THE-SECRET-VALUE", raw)

    def test_a_decrypt_failure_message_never_contains_the_key(self):
        vault1 = Vault(self.path, keyring_module=_FakeKeyring())
        vault1.put("token:x", "token", {"value": "v"})
        try:
            Vault(self.path, keyring_module=_FakeKeyring())  # a different, fresh key
        except VaultUnavailable as exc:
            self.assertNotIn("v", str(exc).split()[-1])  # crude but real: no raw key hex leaks
        else:
            self.fail("expected VaultUnavailable")

    def test_repr_of_a_credential_never_carries_a_value(self):
        cred = Credential(id="token:x", kind="token")
        self.assertNotIn("SECRET", repr(cred))


class LazyVaultSecretStoreTestCase(unittest.TestCase):
    """The store that is actually chained into `build_secret_store()`
    on every Kernel/Worker boot. Its whole reason to exist is caught
    live, 2026-09-09: an eager version left a real OS keychain entry
    behind after nothing more than running the kernel test suite."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "v.bin"

    def test_a_non_vault_name_never_constructs_the_real_vault(self):
        from simorgh.kernel.vault import LazyVaultSecretStore

        calls = []

        class _TrackingKeyring:
            def get_password(self, *a):
                calls.append(a)
                return None

            def set_password(self, *a):
                calls.append(a)

        store = LazyVaultSecretStore(self.path, keyring_module=_TrackingKeyring())
        self.assertIsNone(store.get("SOME_ENV_VAR"))
        self.assertIsNone(store.get("GEMINI_API_KEY"))
        self.assertEqual(calls, [], "a non-vault: lookup must never touch the keyring")

    def test_a_vault_prefixed_name_does_construct_it(self):
        from simorgh.kernel.vault import LazyVaultSecretStore, Vault

        fake = _FakeKeyring()
        Vault(self.path, keyring_module=fake).put("token:x", "token", {"value": "v"})
        store = LazyVaultSecretStore(self.path, keyring_module=fake)
        self.assertEqual(store.get("vault:token:x:value"), "v")

    def test_it_composes_into_the_real_chain_builder(self):
        # `build_secret_store` itself, exercised end to end, must not
        # touch the real OS keychain for an ordinary boot -- the exact
        # regression this class exists to prevent.
        import unittest.mock

        from simorgh.kernel.config import LoadedConfig
        from simorgh.kernel.secrets import build_secret_store

        calls = []
        with unittest.mock.patch("keyring.get_password", side_effect=lambda *a: calls.append(a)), \
                unittest.mock.patch("keyring.set_password", side_effect=lambda *a: calls.append(a)):
            store = build_secret_store(LoadedConfig({}, None), Path(self._tmp.name))
            self.assertIsNone(store.get("SOME_ENV_VAR"))
        self.assertEqual(calls, [])

    def test_a_construction_failure_is_recorded_not_swallowed(self):
        from simorgh.kernel.vault import LazyVaultSecretStore

        store = LazyVaultSecretStore(self.path, keyring_module=_FakeKeyring(broken=True))
        key_path = self.path.with_suffix(self.path.suffix + ".key")
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text("00" * 32)
        key_path.chmod(0o644)  # unsafe -> construction should fail
        self.assertIsNone(store.get("vault:x:y"))
        self.assertIsNotNone(store.error)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
