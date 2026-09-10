"""The Home Assistant client, its dataclasses, its call-safety policy,
and its fake -- shared between Execution's `home_*` tools and (when it
is built) the `home` subsystem's percept bridge.

`home-automation-design.md` section 3 settled the placement and the
reason: a subsystem may not import another's internals, so a client
living in either one would be unreachable from the other. Contracts
already holds the shapes both sides agree on; a client for an external
system both sides talk to is the same kind of thing.

Contracts may import only the standard library
(`tests/simorgh/test_module_boundaries.py` rule 2), so the REST client
is `urllib` rather than `httpx`. That is no hardship -- it is a JSON
API with a bearer token -- and it keeps the dependency count of the
whole house integration at zero.

**Sim does not speak to devices. Sim speaks to Home Assistant**
(section 0). Every device class in this house is already integrated
there, and writing drivers into Sim would be slower, worse, and
abandoned the day a vendor changes an API.
"""

from .api import Entity, ServiceResult
from .client import HomeAssistantClient, HomeUnavailable
from .policy import classify_call

__all__ = ["Entity", "HomeAssistantClient", "HomeUnavailable", "ServiceResult", "classify_call"]
