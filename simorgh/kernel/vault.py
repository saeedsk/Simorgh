"""A credential vault for multi-value, rotating secrets -- the gap
`secrets.py` leaves open (its own module docstring only ever promised a
single string per name, read once at boot). An OAuth account needs
`access_token`/`refresh_token`/`expires_at` together, and a refresh has
to overwrite all three atomically; a mailbox needs a host+user+password
triple; none of that fits `EnvSecretStore.get(name) -> str | None`.

`platform-connectors-design.md` section 1 specifies `age` (`pyrage`) as
the encryption and `keyring` for the key. Neither `pyrage` nor an `age`
binary is present on this machine (checked, 2026-09-09) while
`cryptography` already is (it is already a transitive dependency via
other packages, and `requirements.txt`'s "everything else is
stdlib-only" floor is about *core* Simorgh, not every optional feature
-- see `execution/external.py`'s own precedent for optional-but-real
deps). AES-256-GCM via `cryptography.hazmat` is the substitution: same
property (authenticated symmetric encryption of a small blob), no new
package to install, one file. If `pyrage`/`age` become available later,
`_encrypt`/`_decrypt` are the only two functions that would change --
the on-disk format already carries an algorithm tag for exactly that
migration.

The vault key itself lives in the OS keychain via `keyring` (macOS
Keychain, Linux Secret Service, Windows Credential Locker) -- so no
master password prompt at boot; the OS session is what gates it. When
`keyring` cannot find a working backend (headless Linux with no
Secret Service, some CI containers), the vault falls back to a key
file at `<path>.key` with the same 0600-or-refuse posture
`FileSecretStore` already enforces, and says so once at open time
rather than failing silently.

Values here NEVER cross into the bus, the ledger, a `ToolResult`, tool
metadata, or a log line -- the same rule `notify.py` and every
connector's tests enforce for their own secrets. `Vault.open()` is the
only method that returns real values, and it is synchronous and
in-memory only.
"""

from __future__ import annotations

import json
import os
import stat as stat_module
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .api import MissingSecret, SecretStore

_UNSAFE_MODE_BITS = stat_module.S_IRWXG | stat_module.S_IRWXO
_ALGO = "aes256gcm-v1"
_KEYRING_SERVICE = "simorgh-vault"
_KEYRING_USERNAME = "vault-key"


def default_vault_path() -> Path:
    """`~/.simorgh/vault.bin`, overridable by `SIMORGH_VAULT_PATH` for
    tests and containers. A fixed per-machine path rather than one
    under a Kernel run's `data_dir`: the vault is meant to survive
    across `sim.sh` restarts and to be the same file whether it is the
    daemon or the `vault` CLI command touching it."""
    override = os.environ.get("SIMORGH_VAULT_PATH")
    if override:
        return Path(override)
    return Path.home() / ".simorgh" / "vault.bin"


class VaultUnavailable(RuntimeError):
    """The vault could not be opened, decrypted, or written -- never
    silently treated as empty; a caller must be told which."""


class VaultKeyFileUnsafe(RuntimeError):
    """The fallback key file is readable/writable by group or other."""


@dataclass(frozen=True)
class Credential:
    """What `Vault.list()` returns: everything about a credential
    EXCEPT its values. `Vault.open(id)` is the only way to see those."""

    id: str
    kind: str                      # "oauth2" | "token" | "password" | "keyfile" | "cookie_jar"
    scopes: tuple[str, ...] = ()
    expires_at: float | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    last_used_at: float | None = None


def _aesgcm():
    """`AESGCM`, or a `VaultUnavailable` naming the package. `cryptography`
    is treated as an optional dependency (the `requirements.txt`
    stdlib-only floor is about *core* Simorgh; the vault is an added
    feature) and so the import is guarded, both to refuse cleanly on a
    minimal install and to satisfy the module-boundary rule that every
    third-party import sit behind `try/except ImportError`."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover -- optional dependency
        raise VaultUnavailable(
            "the vault needs the `cryptography` package (pip install cryptography)"
        ) from exc
    return AESGCM


def _encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + _aesgcm()(key).encrypt(nonce, plaintext, None)


def _decrypt(key: bytes, blob: bytes) -> bytes:
    nonce, ciphertext = blob[:12], blob[12:]
    return _aesgcm()(key).decrypt(nonce, ciphertext, None)


def _keyring_disabled() -> bool:
    """`SIMORGH_VAULT_NO_KEYRING=1` keeps the key in a 0600 file beside
    the vault instead of the OS keychain.

    For containers and CI, where there is either no keychain or one
    nobody wants written to. It also stops this project's own test
    suite leaving a real entry on a developer's machine -- which has
    happened once already, from nothing more than running the tests.
    """
    return (os.environ.get("SIMORGH_VAULT_NO_KEYRING") or "").strip() not in ("", "0", "false", "no")


def _load_or_create_key(path: Path, *, keyring_module=None) -> tuple[bytes, str]:
    """The 32-byte vault key, and where it came from ("keyring" or
    "file") for the one-time startup notice. Tries keyring first;
    never raises for keyring being unusable, only for a genuinely
    unsafe key FILE."""
    if keyring_module is not None and not _keyring_disabled():
        try:
            stored = keyring_module.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
        except Exception:  # noqa: BLE001 -- any backend failure means "try the file"
            stored = None
        if stored:
            return bytes.fromhex(stored), "keyring"
        try:
            new_key = os.urandom(32)
            keyring_module.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, new_key.hex())
            return new_key, "keyring"
        except Exception:  # noqa: BLE001 -- fall through to the file
            pass

    key_path = path.with_suffix(path.suffix + ".key")
    if key_path.is_file():
        if os.name == "posix":
            mode = key_path.stat().st_mode
            if mode & _UNSAFE_MODE_BITS:
                raise VaultKeyFileUnsafe(
                    f"{key_path} is readable/writable by group or other (mode "
                    f"{stat_module.filemode(mode)}) -- refusing to use it as a vault key; "
                    f"run `chmod 600 {key_path}`"
                )
        return bytes.fromhex(key_path.read_text().strip()), "file"

    new_key = os.urandom(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(new_key.hex())
    key_path.chmod(0o600)
    return new_key, "file"


class Vault:
    """The multi-value store. `path` holds the encrypted blob; nothing
    is decrypted until `open()` is called for one credential id."""

    def __init__(self, path: Path, *, keyring_module=None, clock=time.time, logger=None) -> None:
        self._path = path
        self._clock = clock
        self._logger = logger
        if keyring_module is None:
            try:
                import keyring as keyring_module  # noqa: PLC0414
            except ImportError:
                keyring_module = None
        self._key, self._key_source = _load_or_create_key(path, keyring_module=keyring_module)
        self._records: dict[str, dict] = self._read()
        if logger is not None and self._key_source == "file":
            logger.warning(
                "vault_key_fallback_to_file",
                detail="no working keyring backend; vault key stored in a 0600 file instead",
            )

    @property
    def path(self) -> Path:
        """Where the encrypted blob lives. `vault list` prints it, so a
        person can tell which file they are looking at when
        `SIMORGH_VAULT_PATH` is set."""
        return self._path

    @property
    def key_source(self) -> str:
        return self._key_source

    def _read(self) -> dict[str, dict]:
        if not self._path.is_file():
            return {}
        raw = self._path.read_bytes()
        if not raw:
            return {}
        try:
            header, blob = raw.split(b"\n", 1)
        except ValueError as exc:
            raise VaultUnavailable(f"{self._path} is not a valid vault file") from exc
        if header.decode("ascii", "replace") != _ALGO:
            raise VaultUnavailable(f"{self._path} uses an unsupported vault format {header!r}")
        try:
            plaintext = _decrypt(self._key, blob)
        except Exception as exc:  # noqa: BLE001 -- wrong key / corrupt file, either way: unavailable
            raise VaultUnavailable(
                f"could not decrypt {self._path} -- wrong vault key or a corrupted file"
            ) from exc
        return json.loads(plaintext.decode("utf-8"))

    def _write(self) -> None:
        plaintext = json.dumps(self._records).encode("utf-8")
        blob = _encrypt(self._key, plaintext)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_bytes(_ALGO.encode("ascii") + b"\n" + blob)
        tmp.chmod(0o600)
        tmp.replace(self._path)

    def list(self) -> list[Credential]:
        out = []
        for cred_id, record in self._records.items():
            meta = record.get("_meta", {})
            out.append(Credential(
                id=cred_id, kind=record.get("_kind", "token"),
                scopes=tuple(meta.get("scopes", ())), expires_at=meta.get("expires_at"),
                created_at=meta.get("created_at", 0.0), updated_at=meta.get("updated_at", 0.0),
                last_used_at=meta.get("last_used_at"),
            ))
        return sorted(out, key=lambda c: c.id)

    def open(self, cred_id: str) -> Mapping[str, str]:
        """Decrypted values for one credential -- in-memory only, never
        cached beyond the call, never logged. Records `last_used_at`."""
        record = self._records.get(cred_id)
        if record is None:
            raise MissingSecret(cred_id)
        record.setdefault("_meta", {})["last_used_at"] = self._clock()
        self._write()
        return {k: v for k, v in record.items() if not k.startswith("_")}

    def put(self, cred_id: str, kind: str, values: Mapping[str, str], *,
            scopes: tuple[str, ...] = (), expires_at: float | None = None) -> None:
        now = self._clock()
        existing = self._records.get(cred_id, {})
        created_at = existing.get("_meta", {}).get("created_at", now)
        self._records[cred_id] = {
            **{str(k): str(v) for k, v in values.items()},
            "_kind": kind,
            "_meta": {"scopes": list(scopes), "expires_at": expires_at,
                      "created_at": created_at, "updated_at": now,
                      "last_used_at": existing.get("_meta", {}).get("last_used_at")},
        }
        self._write()

    def delete(self, cred_id: str) -> None:
        if cred_id in self._records:
            del self._records[cred_id]
            self._write()

    def stale(self, *, days: float = 90.0) -> list[Credential]:
        """Credentials no subsystem has opened in `days` -- the audit
        `platform-connectors-design.md` §1 asks for."""
        cutoff = self._clock() - days * 86400.0
        return [c for c in self.list()
                if (c.last_used_at or c.created_at) < cutoff]


def _glob_match(pattern: str, name: str) -> bool:
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return pattern == name


@dataclass(frozen=True)
class VaultHandle:
    """What a subsystem actually receives: a `Vault` scoped to the
    credential-id patterns it declared it needs. `open` outside that
    scope raises -- the same boundary `ScopedSecretStore` gives plain
    secrets, extended to multi-value credentials."""

    _vault: Vault
    _allowed: tuple[str, ...]

    def _in_scope(self, cred_id: str) -> bool:
        return any(_glob_match(pattern, cred_id) for pattern in self._allowed)

    def list(self) -> list[Credential]:
        return [c for c in self._vault.list() if self._in_scope(c.id)]

    def open(self, cred_id: str) -> Mapping[str, str]:
        if not self._in_scope(cred_id):
            raise MissingSecret(f"{cred_id} (not scoped to this subsystem's vault handle)")
        return self._vault.open(cred_id)

    def put(self, cred_id: str, kind: str, values: Mapping[str, str], **kw) -> None:
        if not self._in_scope(cred_id):
            raise MissingSecret(f"{cred_id} (not scoped to this subsystem's vault handle)")
        self._vault.put(cred_id, kind, values, **kw)

    def delete(self, cred_id: str) -> None:
        if not self._in_scope(cred_id):
            raise MissingSecret(f"{cred_id} (not scoped to this subsystem's vault handle)")
        self._vault.delete(cred_id)


class VaultSecretStore:
    """Adapts a `Vault` to the plain `SecretStore` protocol
    (`get`/`require` -> one string), so `ChainedSecretStore` can include
    it beside `EnvSecretStore`/`FileSecretStore` with no other code
    changing. A lookup name `"vault:<cred_id>:<field>"` reads that one
    field from that one credential; anything else is a miss (falls
    through to the next store in the chain), never an error -- a chain
    link must stay silent about names it does not own."""

    _PREFIX = "vault:"

    def __init__(self, vault: Vault) -> None:
        self._vault = vault

    def get(self, name: str) -> str | None:
        if not name.startswith(self._PREFIX):
            return None
        rest = name[len(self._PREFIX):]
        cred_id, _, field_name = rest.rpartition(":")
        if not cred_id or not field_name:
            return None
        try:
            values = self._vault.open(cred_id)
        except MissingSecret:
            return None
        return values.get(field_name)

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise MissingSecret(name)
        return value


class ImportSourceError(RuntimeError):
    """`vault import` could not reach the named source -- missing CLI,
    missing package, or the source itself does not have the value.
    Always names exactly what to install/configure."""


def resolve_import_source(source: str, *, env: Mapping[str, str] | None = None,
                          runner=None) -> str:
    """One value from a `vault import <id> <source>` source string.
    Never reads or writes the vault itself -- `import` is "copy in
    once", so the caller (`vault.py`'s CLI wiring) still calls
    `vault.put` with whatever field name it decides on.

    Supported today, all zero-new-dependency:
      env:NAME        -- os.environ[NAME] (or the injected `env`)
      file:PATH       -- the file's stripped text content
    Left for a follow-up (each optional, each refuses by naming the
    CLI it needs rather than silently doing nothing):
      op://vault/item/field   -- the `op` CLI (1Password)
      bw:<item>               -- the `bw` CLI (Bitwarden/Vaultwarden)
      aws-sm:<name>           -- boto3 Secrets Manager
      ssm:<path>              -- boto3 SSM Parameter Store
    """
    import subprocess

    env = env if env is not None else os.environ
    runner = runner or subprocess.run

    if source.startswith("env:"):
        name = source[len("env:"):]
        value = env.get(name)
        if value is None:
            raise ImportSourceError(f"{name} is not set in the environment")
        return value

    if source.startswith("file:"):
        path = Path(source[len("file:"):]).expanduser()
        if not path.is_file():
            raise ImportSourceError(f"no such file: {path}")
        return path.read_text().strip()

    if source.startswith("op://"):
        raise ImportSourceError(
            "1Password import needs the `op` CLI signed in -- "
            "run `op read '" + source + "'` yourself and use `vault add`, "
            "or ask for op:// support to be finished"
        )
    if source.startswith("bw:"):
        raise ImportSourceError(
            "Bitwarden import needs the `bw` CLI unlocked -- "
            "run `bw get password " + source[3:] + "` yourself and use `vault add`, "
            "or ask for bw: support to be finished"
        )
    if source.startswith("aws-sm:") or source.startswith("ssm:"):
        raise ImportSourceError(
            f"{source.split(':', 1)[0]} import needs `boto3` and AWS credentials -- "
            "not yet wired; use the AWS CLI to fetch it and `vault add` for now"
        )
    raise ImportSourceError(
        f"unknown import source {source!r} -- known prefixes: env:, file: "
        "(op://, bw:, aws-sm:, ssm: are named but not yet wired)"
    )


class LazyVaultSecretStore:
    """`VaultSecretStore`, but the real `Vault` (and therefore the OS
    keychain, or a fallback key file) is touched only on the FIRST
    lookup of a `vault:`-prefixed name -- never at construction.

    This is what actually gets chained into `build_secret_store()`,
    which runs on every Kernel/Worker boot, including every test that
    boots one without passing its own `secrets=`. Constructing a real
    `Vault` there eagerly means opening (and on a fresh machine,
    CREATING) an entry in the developer's actual OS keychain on every
    single test run -- caught live, 2026-09-09: the kernel test suite
    left a real `simorgh-vault` keychain item behind on this machine
    the first time this store was wired in eagerly. A name that never
    starts with `vault:` (the overwhelming majority of lookups, since
    almost nothing uses the vault yet) must cost nothing and touch
    nothing.

    A construction failure (no usable keyring AND an unsafe fallback
    key file, or a corrupted vault) is cached so it is reported once
    via `get`/`require` returning None/raising, not retried on every
    lookup -- but it is never swallowed silently past that: the first
    failure is available via `.error`.
    """

    def __init__(self, path=None, *, keyring_module=None) -> None:
        self._path = path
        self._keyring_module = keyring_module
        self._real: VaultSecretStore | None = None
        self._tried = False
        self.error: Exception | None = None

    def _ensure(self) -> VaultSecretStore | None:
        if not self._tried:
            self._tried = True
            try:
                path = self._path if self._path is not None else default_vault_path()
                self._real = VaultSecretStore(Vault(path, keyring_module=self._keyring_module))
            except Exception as exc:  # noqa: BLE001 -- additive only; see class docstring
                self.error = exc
                self._real = None
        return self._real

    def get(self, name: str) -> str | None:
        if not name.startswith(VaultSecretStore._PREFIX):
            return None
        real = self._ensure()
        return real.get(name) if real is not None else None

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise MissingSecret(name)
        return value


__all__ = [
    "Credential", "ImportSourceError", "LazyVaultSecretStore", "Vault", "VaultHandle",
    "VaultKeyFileUnsafe", "VaultSecretStore", "VaultUnavailable", "default_vault_path",
    "resolve_import_source",
]
