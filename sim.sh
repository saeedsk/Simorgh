#!/usr/bin/env bash
# Launches Simorgh from anywhere -- resolves its own location so it works
# regardless of the caller's current directory.
#
# Since 2026-09-07 this goes through the Sim loader (simloader.py): a
# stdlib-only bootloader that gates the checkout with the unit suite,
# tags a green commit as known-good, and steps back one tag when the gate
# fails, up to a cap. `SIMORGH_NO_LOADER=1` runs the package directly,
# for when you are the one debugging the gate.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

PYTHON_BIN="${SIMORGH_PYTHON:-python3}"

if [[ "${SIMORGH_NO_LOADER:-0}" == "1" ]]; then
  exec "$PYTHON_BIN" -m simorgh run "$@"
fi
exec "$PYTHON_BIN" simloader.py run "$@"
