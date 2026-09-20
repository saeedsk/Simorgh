"""The `home_*` tools: Sim acting on the house through Home Assistant.

The client, the dataclasses, the safety policy and the fake house live
in `simorgh/contracts/home/`, shared with the `home` subsystem when
that is built (`home-automation-design.md` section 3 settled that, and
the module-boundary rules require it). What lives here is the part only
Execution needs: turning "kitchen lights" into an entity id, and
turning a service call into something a person can read.

**Built here: the acting half.** Finding entities, reading state,
calling services safely, and undoing the last call. **Not built here:
the percept bridge and the rules engine** -- the WebSocket subscription
that turns `state_changed` into `percept.home.*`, and the engine that
runs rules off it. Those are the `home` subsystem, they are a larger
piece, and a half-built subscription would be worse than none.
"""

from .registry import Registry
from .tools import home_tools

__all__ = ["Registry", "home_tools"]
