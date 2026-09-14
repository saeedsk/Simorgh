"""`python -m simorgh …` -- the process entry point. All real logic lives
in `simorgh.kernel.cli` (docs/blueprint/subsystems/03-kernel.md section
5); this file exists only so the package is directly runnable.
"""

from __future__ import annotations

import os
import sys

# Before anything imports google.protobuf: its C++ implementation (the
# anaconda default) has no `FieldDescriptor.is_repeated`, and the Android
# TV remote library (execution/media/androidtv.py) fails on that mid-
# pairing. upb is what the PyPI wheels use everywhere else.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "upb")

from simorgh.kernel.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
