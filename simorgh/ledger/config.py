"""`[ledger]` configuration (02-ledger section 3.5). Loaded by the
Kernel from `simorgh.toml`; `SIMORGH_LEDGER_BACKEND` and
`SIMORGH_LEDGER_DIR` override the file (05 section 2: config, not
code, chooses a backend)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

BACKENDS = ("memory", "jsonl", "sqlite", "dynamodb")


@dataclass(frozen=True)
class Config:
    backend: str = "jsonl"
    data_dir: str = "~/.simorgh/ledger"
    fsync: bool = True
    snapshot_every: int = 200
    blob_inline_threshold: int = 4096
    tail_poll_ms: int = 100
    keep_tail: int = 50
    retention: dict = field(default_factory=dict)  # prefix -> "7d" | "forever" (defaults merged in compaction)
    allow_fallback: bool = False  # fall back to jsonl if the configured backend is unavailable
    dynamodb_table: str = ""
    dynamodb_bucket: str = ""

    @property
    def data_path(self) -> Path:
        return Path(os.path.expanduser(self.data_dir))

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object] | None = None,
                     *, env: Mapping[str, str] | None = None) -> "Config":
        m = dict(mapping or {})
        env = os.environ if env is None else env
        dynamo = m.get("dynamodb") if isinstance(m.get("dynamodb"), Mapping) else {}
        backend = str(env.get("SIMORGH_LEDGER_BACKEND") or m.get("backend") or cls.backend)
        if backend not in BACKENDS:
            raise ValueError(f"[ledger] backend must be one of {BACKENDS}, not {backend!r}")
        retention = m.get("retention") if isinstance(m.get("retention"), Mapping) else {}
        keep_tail = int(retention.get("keep_tail", m.get("keep_tail", cls.keep_tail)))  # type: ignore[union-attr]
        return cls(
            backend=backend,
            data_dir=str(env.get("SIMORGH_LEDGER_DIR") or m.get("data_dir") or cls.data_dir),
            fsync=bool(m.get("fsync", cls.fsync)),
            snapshot_every=int(m.get("snapshot_every", cls.snapshot_every)),  # type: ignore[arg-type]
            blob_inline_threshold=int(m.get("blob_inline_threshold", cls.blob_inline_threshold)),  # type: ignore[arg-type]
            tail_poll_ms=int(m.get("tail_poll_ms", cls.tail_poll_ms)),  # type: ignore[arg-type]
            keep_tail=keep_tail,
            retention={k: v for k, v in retention.items() if k != "keep_tail"},  # type: ignore[union-attr]
            allow_fallback=bool(m.get("allow_fallback", cls.allow_fallback)),
            dynamodb_table=str(dynamo.get("table", "")),  # type: ignore[union-attr]
            dynamodb_bucket=str(dynamo.get("bucket", "")),  # type: ignore[union-attr]
        )


__all__ = ["BACKENDS", "Config"]
