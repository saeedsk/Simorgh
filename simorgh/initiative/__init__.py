"""Initiative: when Sim speaks first, and through which channel.

`api.py` is the decision, pure and testable; `service.py` is the
subsystem that listens for things worth saying and proposes each delivery
as an ordinary action, so Guardian gates an unprompted word exactly as it
gates every other effect.
"""

from .api import Delivery, Notice, Situation, decide
from .service import Service, VERSION

__all__ = ["Delivery", "Notice", "Service", "Situation", "VERSION", "decide"]
