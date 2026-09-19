"""`[telemetry]` configuration. Read by the Kernel, which owns the store
(like the ledger); the section is in `kernel/configcheck.py`'s
`KERNEL_SECTIONS` and its class in `_config_classes`, so a typo in the
section is reported at boot."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

DAY = 86_400.0


@dataclass(frozen=True)
class Config:
    # False hands every Context the no-op `NullTelemetry` and opens no file.
    enabled: bool = True
    # A batch is written this long after its first row arrives ...
    flush_interval_s: float = 0.25
    # ... or as soon as this many rows are waiting, whichever is first.
    batch_rows: int = 500
    # Rows held while the disk is failing or slow; beyond this the oldest
    # are dropped (and counted) so a stuck disk cannot grow memory.
    max_buffer_rows: int = 50_000
    span_retention_days: float = 14.0
    sample_retention_days: float = 7.0
    # Samples older than this are thinned to one per bucket per series.
    downsample_after_days: float = 1.0
    downsample_bucket_s: float = 60.0
    # One retention pass this long after start (0 disables), because the
    # sleep tick first fires `sleep_every_s` (6 h) after boot and most
    # sessions are shorter than that -- the ledger learnt this the hard
    # way (`[ledger] compact_after_start_s`).
    maintain_after_start_s: float = 60.0
    # The sleep-tick pass is skipped if one ran less than this many
    # wall-clock seconds ago; a fake clock in tests fires the tick in a
    # tight loop.
    maintain_min_interval_s: float = 600.0

    @property
    def span_retention_s(self) -> float:
        return self.span_retention_days * DAY

    @property
    def sample_retention_s(self) -> float:
        return self.sample_retention_days * DAY

    @property
    def downsample_after_s(self) -> float:
        return self.downsample_after_days * DAY

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object] | None = None) -> "Config":
        m = dict(mapping or {})

        def num(key: str, kind=float):
            value = kind(m.get(key, getattr(cls, key)))  # type: ignore[arg-type]
            if value < 0:
                raise ValueError(f"[telemetry] {key} must be >= 0, not {value!r}")
            return value

        return cls(
            enabled=bool(m.get("enabled", cls.enabled)),
            flush_interval_s=num("flush_interval_s"),
            batch_rows=max(1, num("batch_rows", int)),
            max_buffer_rows=max(1, num("max_buffer_rows", int)),
            span_retention_days=num("span_retention_days"),
            sample_retention_days=num("sample_retention_days"),
            downsample_after_days=num("downsample_after_days"),
            downsample_bucket_s=max(1.0, num("downsample_bucket_s")),
            maintain_after_start_s=num("maintain_after_start_s"),
            maintain_min_interval_s=num("maintain_min_interval_s"),
        )


__all__ = ["Config"]
