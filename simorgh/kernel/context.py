"""Builds the `Context` handed to one subsystem's `Service.start()`
(docs/blueprint/subsystems/03-kernel.md section 5). Each subsystem gets
its own `BusClient` (bound to its own `source` name, so policy/metrics/
trace all see who actually published) sharing the one backend, its own
config section (empty dict if unconfigured -- an absent section is never
a config error), a `ScopedSecretStore` limited to what it declared, and a
data directory under the runtime's own (`${data_dir}/<name>/`).
"""

from __future__ import annotations

import logging as _logging
import uuid
from pathlib import Path
from typing import Any, Mapping

from simorgh.bus.api import BusPolicy
from simorgh.bus.client import BusClient
from simorgh.contracts.protocols import Clock, Context, Ledger, Logger
from simorgh.contracts import security

from .api import RuntimeConfig, SecretStore
from .secrets import ScopedSecretStore


class _StdlibLogger:
    """The default `Logger`: routes to Python's own `logging`, with
    every call's keyword fields folded into the message (structured
    logging without a third-party dependency -- section 4's
    `log_to_ledger` is a *separate*, additive path the Kernel service
    wires on top, not a replacement for this)."""

    def __init__(self, name: str) -> None:
        self._logger = _logging.getLogger(f"simorgh.{name}")

    def _fmt(self, event: str, fields: dict) -> str:
        extra = " ".join(f"{k}={v!r}" for k, v in fields.items())
        return f"{event} {extra}".rstrip()

    def debug(self, event: str, **fields: Any) -> None:
        self._logger.debug(self._fmt(event, fields))

    def info(self, event: str, **fields: Any) -> None:
        self._logger.info(self._fmt(event, fields))

    def warning(self, event: str, **fields: Any) -> None:
        self._logger.warning(self._fmt(event, fields))

    def error(self, event: str, **fields: Any) -> None:
        self._logger.error(self._fmt(event, fields))


def make_logger(name: str) -> Logger:
    return _StdlibLogger(name)


class ContextFactory:
    def __init__(
        self,
        *,
        bus_backend: Any,
        ledger: Ledger,
        config: Any,  # kernel.config.LoadedConfig
        secrets: SecretStore,
        clock: Clock,
        runtime: RuntimeConfig,
        run_id: str,
        hmac_secret: bytes,
        needs_hmac_secret: frozenset[str],
        bus_policy: BusPolicy | None = None,
        identity_registry: Any | None = None,  # simorgh.bus.enforcement.IdentityRegistry, single mode: None
    ) -> None:
        from simorgh.bus.factory import make_client

        self._make_client = make_client
        self._bus_backend = bus_backend
        self._ledger = ledger
        self._config = config
        self._secrets = secrets
        self._clock = clock
        self._runtime = runtime
        self._run_id = run_id
        self._hmac_secret = hmac_secret
        self._needs_hmac_secret = needs_hmac_secret
        self._bus_policy = bus_policy
        self._identity_registry = identity_registry

    def build(self, name: str, *, instance_id: str = "") -> Context:
        source = f"{name}@{instance_id}" if instance_id else name
        bus = self._make_client(self._bus_backend, source=source, ledger=self._ledger,
                                clock=self._clock.now, policy=self._bus_policy)
        allowed = set(self._config.section(name).get("secrets", []))
        backing: SecretStore = self._secrets
        if name in self._needs_hmac_secret:
            allowed.add("__hmac__")
            backing = HmacSecretStore(self._secrets, self._hmac_secret)
        secrets = ScopedSecretStore(backing, frozenset(allowed))
        token = ""
        if self._identity_registry is not None:
            token = self._identity_registry.issue(name, instance_id)
        data_dir = self._runtime.data_dir / name
        data_dir.mkdir(parents=True, exist_ok=True)
        return Context(
            name=name, instance_id=instance_id, run_id=self._run_id, mode=self._runtime.mode,
            bus=bus, ledger=self._ledger, config=self._config.section(name), secrets=secrets,
            clock=self._clock, logger=make_logger(name), data_dir=data_dir, subsystem_token=token,
        )


class HmacSecretStore:
    """Wraps a backing `SecretStore`, additionally serving exactly one
    in-memory name (`__hmac__`) -- the per-run token secret -- without
    ever touching disk or `os.environ`."""

    def __init__(self, backing: SecretStore, hmac_secret: bytes | None) -> None:
        self._backing = backing
        self._hmac_hex = hmac_secret.hex() if hmac_secret is not None else None

    def get(self, name: str) -> str | None:
        if name == "__hmac__":
            return self._hmac_hex
        return self._backing.get(name)

    def require(self, name: str) -> str:
        value = self.get(name)
        if value is None:
            from .api import MissingSecret

            raise MissingSecret(name)
        return value


__all__ = ["ContextFactory", "HmacSecretStore", "make_logger"]
