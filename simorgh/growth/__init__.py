"""Growth: what Sim learns about itself, and what it does about it.

The merge of learning, reflection and curiosity into one Subsystem
(stage 8 item 1). Three services used to answer the same question --
how should Sim be different tomorrow? -- separately, so a failure
cluster one of them found never reached the estimate another kept.

    estimate/    what Sim is good at, from outcomes    (was learning)
    monitors/    what is going wrong, watched          (was reflection)
    explore/     what is worth finding out             (was curiosity)
    diagnose.py  what keeps going wrong, by counting
    policies.py  what was decided, with the evidence and a way back

Every `learn.*`, `reflect.*` and `curiosity.*` topic is still published
and subscribed as before; the merge changes the owner, not the wire.
"""

from .diagnose import Cluster, Failure, cluster
from .policies import Policy, PolicyStore
from .service import NAME, PARTS, Service, VERSION

__all__ = ["Cluster", "Failure", "NAME", "PARTS", "Policy", "PolicyStore", "Service", "VERSION", "cluster"]
