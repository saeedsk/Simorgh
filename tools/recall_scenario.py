#!/usr/bin/env python3
"""Moved: the recall scenario is `simorgh/evals/scenario.py` (stage 4
item 9), so the household eval suite and this tool are one piece of
code. This shim keeps the old command working."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from simorgh.evals.scenario import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
