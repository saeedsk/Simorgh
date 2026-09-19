"""`simorgh.telemetry` -- spans and samples, out of the decision log
(stage 1 item 1). One SQLite file, `<data_dir>/telemetry.sqlite`, owned
by the Kernel and handed to every subsystem as `ctx.telemetry`. Imports
only `simorgh.contracts` and the standard library.
"""

from __future__ import annotations

from .config import Config
from .service import FILENAME, RecordingSpan, TelemetryService
from .store import TelemetryStore

__all__ = ["Config", "FILENAME", "RecordingSpan", "TelemetryService", "TelemetryStore"]
