"""Secret storage and scoping (docs/blueprint/subsystems/03-kernel.md
section 5, `[secrets]`). Two sources, environment always wins over the
file (never the reverse -- an operator's shell should be able to
override a checked-in-adjacent secrets file without editing it):
`EnvSecretStore` (plain `os.environ`) and `FileSecretStore` (a TOML file
that must not be group/world-readable, mirroring the `ssh` private-key
convention -- section 8: "Secrets file world-readable -> refuse to load
it; exit 2"). `ScopedSecretStore` is what a `Service` actually receives:
`require()` raises `MissingSecret` for a name the subsystem never
declared, so a subsystem cannot accidentally (or curiously) read a
neighbor's key -- most concretely, the per-run HMAC secret, handed only
to `guardian` and `execution` (`02` section 3).
"""

from __future__ import annotations

import os
import stat as stat_module
import tomllib
from pathlib import Path
from typing import Mapping

from .api import MissingSecret, SecretStore

_UNSAFE_MODE_BITS = stat_module.S_IRWXG | stat_module.S_IRWXO


class SecretsFileUnsafe(RuntimeError):
    """The secrets file is readable/writable by group or other -- refused
    outright, the same posture `ssh` takes toward a world-readable
    private key (section 8)."""


class EnvSecretStore:
    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env = env if env is not None else os.environ

    def get(self, name: str) -> str | None:
        return self._env.get(name)

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise MissingSecret(name)
        return value


class FileSecretStore:
    def __init__(self, path: Path, *, require_safe_perms: bool = True) -> None:
        self._path = path
        self._values: dict[str, str] = {}
        if path.is_file():
            if require_safe_perms and os.name == "posix":
                mode = path.stat().st_mode
                if mode & _UNSAFE_MODE_BITS:
                    raise SecretsFileUnsafe(
                        f"{path} is readable/writable by group or other (mode "
                        f"{stat_module.filemode(mode)}) -- refusing to load secrets from it; "
                        f"run `chmod 600 {path}`"
                    )
            with path.open("rb") as fh:
                data = tomllib.load(fh)
            self._values = {str(k): str(v) for k, v in data.items() if isinstance(v, (str, int, float))}

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise MissingSecret(name)
        return value


class ChainedSecretStore:
    """Environment first, then the file -- an env var always overrides
    the file's own value for the same name."""

    def __init__(self, *stores: SecretStore) -> None:
        self._stores = stores

    def get(self, name: str) -> str | None:
        for store in self._stores:
            value = store.get(name)
            if value is not None:
                return value
        return None

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            raise MissingSecret(name)
        return value


class ScopedSecretStore:
    """What a `Service.start()` actually receives: only `allowed` names
    are ever visible, so a subsystem that never declared a need for a
    secret cannot read it even if it tried (`require`/`get` both scoped,
    not just `require`)."""

    def __init__(self, backing: SecretStore, allowed: frozenset[str]) -> None:
        self._backing = backing
        self._allowed = allowed

    def get(self, name: str) -> str | None:
        if name not in self._allowed:
            return None
        return self._backing.get(name)

    def require(self, name: str) -> str:
        if name not in self._allowed:
            raise MissingSecret(f"{name} (not scoped to this subsystem)")
        return self._backing.require(name)


def build_secret_store(config, data_dir: Path) -> SecretStore:  # noqa: ANN001 -- kernel.config.LoadedConfig
    """`config.section('secrets')['file']`, `${data_dir}` expanded;
    missing file is fine (env-only deployments), unsafe permissions are
    not."""
    section = config.section("secrets")
    file_value = str(section.get("file", "${data_dir}/secrets.toml")).replace("${data_dir}", str(data_dir))
    file_store = FileSecretStore(Path(file_value))
    return ChainedSecretStore(EnvSecretStore(), file_store)


__all__ = [
    "ChainedSecretStore",
    "EnvSecretStore",
    "FileSecretStore",
    "ScopedSecretStore",
    "SecretsFileUnsafe",
    "build_secret_store",
]
