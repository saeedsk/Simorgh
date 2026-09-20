"""The product domains, outside the most trusted package (stage 9 item 1).

Six domains -- the creator's documents, calendar and mail, security
posture, the house, energy, media -- used to live inside
`simorgh/execution/`, next to the HMAC verifier and the sandboxes. That
put 10,000 lines of integrations in the one package Sim may never edit,
for no safety reason: a media tool is not part of the approval path, it
is something the approval path gates.

They register through Execution's `extra_tools` seam, exactly as an
external adapter would. Execution keeps the registry, the verifier, the
sandboxes, the worktrees and path/net safety, and only that is
Guardian-protected. Nothing here is special: a domain is a factory
returning tool objects, and the tools reach the world through the same
`action.proposed` path as everything else.
"""

from __future__ import annotations

from .energy.tools import energy_tools
from .home.cameras import cameras_tools
from .home.ring import ring_tools
from .home.tools import home_tools
from .knowledge.tools import knowledge_tools
from .media.tools import media_tools
from .pim.tools import pim_tools
from .security.tools import security_tools

#: Every domain, in the order Execution used to splice them in.
DOMAINS: tuple[str, ...] = ("knowledge", "pim", "security", "home", "energy", "media")


def domain_tools(config, *, secrets=None) -> list:
    """Every domain's tools, for Execution's `extra_tools`.

    `config` is Execution's own `Config` and `secrets` the scoped store
    it is handed at `start()`, which is why this is a factory rather
    than a list: the secrets do not exist when the Kernel builds the
    Service.
    """
    return [
        *knowledge_tools(config),
        *pim_tools(config, secrets=secrets),
        *security_tools(config, secrets=secrets),
        *home_tools(config, secrets=secrets),
        *energy_tools(config, secrets=secrets),
        *media_tools(config, secrets=secrets),
        *cameras_tools(config, secrets=secrets),
        *ring_tools(config, secrets=secrets),
    ]


__all__ = ["DOMAINS", "domain_tools"]
