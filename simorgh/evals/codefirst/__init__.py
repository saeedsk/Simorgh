"""The code-first suite (stage 19 item 8): household jobs that are data.

Five questions across four domains -- mail, calendar, files, tool
telemetry -- each over more items than one tool page shows, each with an
exact answer computed from a seeded fake (`world.py`, `cases.py`). The
score is the answer's exactness; whether a `run_analysis` program ran is
recorded beside it (`method.py`). `run.py` runs it two ways: two scripted
models over Sim's real tools (free, offline: is each case fair?) and Sim
itself in a sandbox (paid).
"""

from .cases import CASES, CodeFirstCase, Score, by_id
from .method import PROGRAM_TOOLS, method_of, ran_program
from .world import DEFAULT_SEED, TEST_ANCHOR, World, build

__all__ = ["CASES", "CodeFirstCase", "DEFAULT_SEED", "PROGRAM_TOOLS", "Score", "TEST_ANCHOR", "World", "build",
           "by_id", "method_of", "ran_program"]
