"""The memory eval suite (stage 15 items 4, 5 and 5b).

Native Memory, native Memory with the entity layer, and two sidecars --
Graphiti and Cognee -- fed the same synthetic household month and asked
the same questions; see `suite.py`. Nothing in `simorgh/` imports this
package except `evals/suites.py` and `evals/__main__.py`.
"""

from .corpus import CATEGORIES, QUESTIONS, episodes
from .suite import FREE, SYSTEMS, main, run

__all__ = ["CATEGORIES", "FREE", "QUESTIONS", "SYSTEMS", "episodes", "main", "run"]
