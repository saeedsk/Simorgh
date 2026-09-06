"""Simorgh v2 Ledger -- the append-only memory of everything that ever
happened. Spec: docs/blueprint/subsystems/02-ledger.md. Other packages
import only `simorgh.ledger.client` (the type-level client); the Kernel
uses `make_ledger` and `Service`.
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
