"""Concrete `Connector` implementations for the pim domain.

Each one obeys the three rules from `contracts/connector.py`:
construction never raises, `probe()` is the health check and names what
is missing, and credentials come from the vault and never appear in a
return value, a log or an error string.
"""

from .caldav import CalDavConnector
from .fakes import FakeCalDav, FakeImap
from .imap import ImapConnector

__all__ = ["CalDavConnector", "FakeCalDav", "FakeImap", "ImapConnector"]
