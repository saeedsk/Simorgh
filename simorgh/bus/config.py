"""Bus configuration (docs/blueprint/subsystems/01-bus.md section 3.5).
Loaded from the `[bus]` section of `simorgh.toml` by the Kernel; every
field has a working default so the `memory` backend needs no config at
all (the guaranteed floor, section 8)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class SqliteConfig:
    path: str = "${data_dir}/bus.sqlite"
    poll_interval_ms: int = 50
    busy_timeout_ms: int = 5000


@dataclass(frozen=True)
class AwsConfig:
    region: str = "us-east-1"
    topic_prefix: str = "simorgh-dev"
    queue_prefix: str = "simorgh-dev"
    wait_time_seconds: int = 1


@dataclass(frozen=True)
class Config:
    backend: str = "memory"  # memory | sqlite | aws
    max_queue_depth: int = 10_000  # per consumer group; publish awaits above this (backpressure)
    max_deliveries: int = 5  # then -> dead:<type>
    default_lease_seconds: float = 30.0  # visibility timeout for commands
    request_default_timeout: float = 30.0
    priority_preempt_threshold: int = 9  # at/above: bypass backpressure, jump queues
    handler_timeout_seconds: float = 300.0  # memory backend per-handler default
    drain_seconds: float = 10.0
    trace_enabled: bool = True
    # per-pattern sample rate; default 1.0 for anything not listed (03 section 5 "Tracing")
    trace_sample: Mapping[str, float] = field(default_factory=lambda: {
        "system.tick.second": 0.0, "system.metrics": 0.0, "_inbox.#": 0.0,
    })
    trace_blob_threshold_bytes: int = 4096
    dedupe_window: int = 5000
    metrics_interval_seconds: float = 15.0
    sqlite: SqliteConfig = field(default_factory=SqliteConfig)
    aws: AwsConfig = field(default_factory=AwsConfig)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None, *, data_dir: str = ".") -> "Config":
        """`[bus]` table -> Config, with `SIMORGH_BUS_BACKEND` /
        `SIMORGH_BUS_SQLITE_PATH` environment overrides and `${data_dir}`
        expanded in the sqlite path."""
        data = dict(data or {})
        sqlite_raw = dict(data.pop("sqlite", {}) or {})
        aws_raw = dict(data.pop("aws", {}) or {})
        env_backend = os.environ.get("SIMORGH_BUS_BACKEND")
        if env_backend:
            data["backend"] = env_backend
        env_path = os.environ.get("SIMORGH_BUS_SQLITE_PATH")
        if env_path:
            sqlite_raw["path"] = env_path
        sqlite_cfg = SqliteConfig(**{k: v for k, v in sqlite_raw.items() if k in SqliteConfig.__dataclass_fields__})
        sqlite_cfg = SqliteConfig(
            path=sqlite_cfg.path.replace("${data_dir}", str(data_dir)),
            poll_interval_ms=sqlite_cfg.poll_interval_ms,
            busy_timeout_ms=sqlite_cfg.busy_timeout_ms,
        )
        aws_cfg = AwsConfig(**{k: v for k, v in aws_raw.items() if k in AwsConfig.__dataclass_fields__})
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(sqlite=sqlite_cfg, aws=aws_cfg, **known)


__all__ = ["AwsConfig", "Config", "SqliteConfig"]
