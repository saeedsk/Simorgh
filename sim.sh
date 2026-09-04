#!/usr/bin/env bash
# Launches Simorgh's CLI from anywhere -- resolves its own location so it
# works regardless of the caller's current directory, and runs `src.main`
# as a module (not a bare script) so its `from src....` imports resolve
# the same way they do under `python3 -m unittest discover` and every
# doc/example in this repo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${SIMORGH_PYTHON:-python3}"

exec "$PYTHON_BIN" -m src.main
