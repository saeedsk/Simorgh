"""Simorgh v2 Ledger -- the append-only memory of everything that ever
happened. Spec: docs/blueprint/subsystems/02-ledger.md.

Public surface and who should import what:

- Other packages import ONLY from this package root
  (`from simorgh.ledger import ...`), never from private submodules:
    * `simorgh.kernel.service` -- `Event`, `Service`, `make_ledger`
      (boot: builds the backend via `make_ledger`, runs the ledger as a
      `Subsystem` via `Service`, and hands out `LedgerClient` views
      bound to each subsystem's stream prefix at runtime).
    * `simorgh.bus`, `simorgh.cognition`, `simorgh.world`, and tests --
      `Event`, `LedgerClient`, `Projection`, `Config` for day-to-day
      append/read; error types `LedgerError`, `LedgerUnavailable`,
      `ConflictError`, `ValidationError`, `BackendUnavailable`,
      `BlobNotFound` for failure handling.
- In-package modules may reach each other directly:
    * `client.py` -> `api.py` (Event, Projection, error types)
    * `service.py` -> `api.py`, `client.py`, `config.py`
    * `factory.py` -> `backends/`, `config.py`
    * `projection.py`, `blobs.py`, `compaction.py`, `idempotency.py`,
      `streams.py`, `migrate_v1.py` -- internal; not re-exported here.

`__all__` is the contract: it lists exactly the names re-exported at
this package root (verified against the imports above; the consistency
check lives in tests/simorgh/ledger). Adding a name to the package
surface means adding it to `__all__` and to the blueprint spec in
docs/blueprint/subsystems/02-ledger.md in the same change.
"""

from .api import (
    BackendUnavailable,
    BlobNotFound,
    ConflictError,
    Event,
    LedgerBackend,
    LedgerError,
    LedgerUnavailable,
    Projection,
    ValidationError,
)
from .client import LedgerClient
from .config import Config
from .factory import make_backend, make_ledger
from .service import Service

__all__ = [
    "BackendUnavailable", "BlobNotFound", "Config", "ConflictError", "Event", "LedgerBackend",
    "LedgerClient", "LedgerError", "LedgerUnavailable", "Projection", "Service", "ValidationError",
    "make_backend", "make_ledger",
]
