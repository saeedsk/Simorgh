"""Evals: one way to ask whether a change made Sim better (stage 4 item 9).

`simorgh/benchmark` (datasets against a model), `tools/trial_suite.py`
(real tasks against the whole system) and the household scenario used to
answer that question in three formats that could not be compared. This
package is the single entry point over all three: one `Case`, one
`Outcome`, one `Report` with a bootstrap interval over repeats, and a
`simloader.py bless` that runs the free suite and records what it got.

    python -m simorgh.evals run household --repeats 3
"""

from .api import Case, Outcome, Report, bootstrap_ci
from .runner import last, record, run, table
from .suites import PAID, SUITES, find

__all__ = ["Case", "Outcome", "PAID", "Report", "Report", "SUITES", "bootstrap_ci", "find",
           "last", "record", "run", "table"]
