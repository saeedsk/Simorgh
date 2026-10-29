"""`simorgh.telemetry` -- spans and samples, out of the decision log
(stage 1 item 1). One SQLite file, `<data_dir>/telemetry.sqlite`, owned
by the Kernel and handed to every subsystem as `ctx.telemetry`. Imports
only `simorgh.contracts` and the standard library.

The intended access path is `ctx.telemetry` -- subsystems should use the
instance handed to them via the context, not import or construct their
own `TelemetryService`. This module's exports exist for the Kernel (which
builds the service) and for tests.

Doctest-style usage of `RecordingSpan` as a context manager:

    >>> from simorgh.telemetry import RecordingSpan
    >>> with RecordingSpan(...) as span:   # doctest: +SKIP
    ...     span.record("decision", {"action": "open"})
    ...     span.record("latency_ms", {"ms": 12})
    ... # span is committed on clean exit, abandoned on exception

Unknown names fail with the valid `__all__` listed:

    >>> from simorgh.telemetry import Nope
    Traceback (most recent call last):
        ...
    AttributeError: module 'simorgh.telemetry' has no attribute 'Nope'; valid names: Config, FILENAME, RecordingSpan, TelemetryService, TelemetryStore
"""

from __future__ import annotations

from .config import Config
from .service import FILENAME, RecordingSpan, TelemetryService
from .store import TelemetryStore

__all__ = ["Config", "FILENAME", "RecordingSpan", "TelemetryService", "TelemetryStore"]


def __getattr__(name: str) -> object:
    """Raise a helpful AttributeError naming the valid exports on a miss.

    Keeps `ctx.telemetry` as the documented access path while making any
    stray `from simorgh.telemetry import <typo>` self-explanatory.
    """
    raise AttributeError(
        f"module {__name__!r} has no attribute {name!r}; "
        f"valid names: {', '.join(__all__)}"
    )
