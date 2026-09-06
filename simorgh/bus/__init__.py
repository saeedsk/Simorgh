"""`simorgh.bus` -- the nervous system (docs/blueprint/subsystems/01-bus.md).

Other packages import only `simorgh.bus.client` (boundary rule); the
Kernel additionally uses `factory`, `enforcement`, and `service`.
"""

from .service import Service

__all__ = ["Service"]
