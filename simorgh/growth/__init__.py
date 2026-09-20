"""Growth: what Sim learns about itself, and what it does about it.

Stage 8 builds this as the merge of learning, reflection and curiosity.
What is here so far are the two halves that stand on their own and that
the merge will keep: `diagnose.py` finds what keeps going wrong by
counting rather than by asking a model, and `policies.py` is the durable
record of what Sim decided to do differently -- with the evidence, the
measurement and a way back.
"""

from .diagnose import Cluster, Failure, cluster
from .policies import Policy, PolicyStore

__all__ = ["Cluster", "Failure", "Policy", "PolicyStore", "cluster"]
