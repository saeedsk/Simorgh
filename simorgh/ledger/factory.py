"""`make_ledger(config)` -- the Kernel's one call to get a started-able
`LedgerClient` for the configured backend. A missing optional dependency
raises `BackendUnavailable` unless `allow_fallback` is set, in which case
`jsonl` is used and the fallback is reported on the client
(`client.fallback_reason`) so the Kernel can log it loudly -- a silent
change of where data lives is worse than a clear failure (02-ledger
section 8)."""

from __future__ import annotations

from collections.abc import Mapping

from simorgh.contracts.protocols import Clock

from .api import BackendUnavailable, LedgerBackend
from .client import LedgerClient
from .config import Config


def make_backend(config: Config) -> LedgerBackend:
    if config.backend == "memory":
        from .backends.memory import InMemoryBackend

        return InMemoryBackend()
    if config.backend == "jsonl":
        from .backends.jsonl import JsonlBackend

        return JsonlBackend(config.data_path, fsync=config.fsync)
    if config.backend == "sqlite":
        from .backends.sqlite import SqliteBackend

        return SqliteBackend(config.data_path / "ledger.sqlite3")
    if config.backend == "dynamodb":
        from .backends.dynamodb import DynamoBackend, _boto3_adapters

        if not config.dynamodb_table or not config.dynamodb_bucket:
            raise BackendUnavailable("[ledger.dynamodb] table and bucket are required")
        table, bucket = _boto3_adapters(config.dynamodb_table, config.dynamodb_bucket)
        return DynamoBackend(config.dynamodb_table, config.dynamodb_bucket, table=table, bucket=bucket)
    raise BackendUnavailable(f"unknown ledger backend {config.backend!r}")


def make_ledger(config: Config | Mapping[str, object] | None = None, *, clock: Clock | None = None) -> LedgerClient:
    cfg = config if isinstance(config, Config) else Config.from_mapping(config)
    fallback_reason: str | None = None
    try:
        backend = make_backend(cfg)
    except BackendUnavailable as exc:
        if not cfg.allow_fallback or cfg.backend == "jsonl":
            raise
        fallback_reason = str(exc)
        from .backends.jsonl import JsonlBackend

        backend = JsonlBackend(cfg.data_path, fsync=cfg.fsync)
    client = LedgerClient(backend, clock=clock, inline_threshold=cfg.blob_inline_threshold,
                          tail_poll_ms=cfg.tail_poll_ms)
    client.fallback_reason = fallback_reason  # type: ignore[attr-defined]
    return client


__all__ = ["make_backend", "make_ledger"]
