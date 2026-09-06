"""`simorgh.contracts` -- THE single shared dependency of every Simorgh v2
subsystem (docs/blueprint/03-contracts-and-messaging.md is the prose
form; the checked-in JSON Schemas under `schema/` are the source of
truth when the two disagree).

What lives here and nowhere else: the message envelope, the topic
catalog and reserved-topology rules, one dataclass per message type with
its generated schema, the Bus/Ledger/Subsystem/Provider/Tool protocols,
the approval-token and subsystem-token helpers, and the version
translator registry. No logic that belongs to a subsystem, no imports
beyond the standard library (docs/blueprint/02-system-architecture.md
section 4, rule 2 -- enforced by tests/simorgh/test_module_boundaries.py).

Importing this package registers every message type (see `messages/`),
so `envelope.validate()` always has the full catalog available.
"""

from __future__ import annotations

from . import messages as _messages  # noqa: F401 -- side effect: populate the registry
from .envelope import CATALOG_VERSION, ContractError, Event, Message, validate
from .registry import MessageSpec, all_specs, get_spec
from .topics import CATALOG, DOMAINS, matches

__all__ = [
    "CATALOG",
    "CATALOG_VERSION",
    "ContractError",
    "DOMAINS",
    "Event",
    "Message",
    "MessageSpec",
    "all_specs",
    "get_spec",
    "matches",
    "validate",
]
