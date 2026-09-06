#!/usr/bin/env bash
# Launches Simorgh from anywhere -- resolves its own location so it works
# regardless of the caller's current directory. Cutover (Phase 5, Stage B,
# docs/blueprint/06-migration-from-v1.md section 6): this now runs the v2
# Kernel (`python -m simorgh run`) as the default entry point. v1
# (`src.main`) is retired but not yet deleted -- `python -m src.main` still
# works and prints a notice pointing back here (see src/main.py).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${SIMORGH_PYTHON:-python3}"

exec "$PYTHON_BIN" -m simorgh run
