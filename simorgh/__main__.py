"""`python -m simorgh …` -- the process entry point. All real logic lives
in `simorgh.kernel.cli` (docs/blueprint/subsystems/03-kernel.md section
5); this file exists only so the package is directly runnable.
"""

from __future__ import annotations

import sys

from simorgh.kernel.cli import main

if __name__ == "__main__":
    sys.exit(main())
