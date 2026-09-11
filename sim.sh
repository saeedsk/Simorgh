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

# Name the repository Sim works on. Execution only ever makes a task's
# worktree of a repository somebody NAMED (`[execution] repo_root` or
# this variable); a root merely inferred from the working directory
# means in-place edits, as before 2026-09-11. Every path through this
# script -- loader or not -- runs Sim from this checkout, so name it.
export SIMORGH_EXECUTION_REPO_ROOT="${SIMORGH_EXECUTION_REPO_ROOT:-$REPO_ROOT}"

if [[ "${SIMORGH_NO_LOADER:-0}" == "1" ]]; then
  exec "$PYTHON_BIN" -m simorgh run "$@"
fi

# The loader gates every file except itself, and it lives in the same
# commit as the code it judges -- so Sim could, in one commit, destroy
# the only mechanism that would undo that commit. An observer proved it:
# a syntax error in simloader.py bricked the system completely, with no
# gate, no rollback, no note and no message on screen (2026-09-08).
#
# This script is the one file Sim has no reason to rewrite, so the check
# belongs here. If the loader will not compile, put back the copy from
# the newest known-good tag and say so.
if ! "$PYTHON_BIN" -c "import sys; compile(open('simloader.py').read(), 'simloader.py', 'exec')" 2>/dev/null; then
  LAST_GOOD="$(git tag --list 'sim-good-*' --sort=-v:refname 2>/dev/null | head -1)"
  if [[ -n "$LAST_GOOD" ]]; then
    echo "[sim.sh] simloader.py does not compile -- restoring it from $LAST_GOOD" >&2
    git checkout "$LAST_GOOD" -- simloader.py
    if ! "$PYTHON_BIN" -c "compile(open('simloader.py').read(), 'simloader.py', 'exec')" 2>/dev/null; then
      echo "[sim.sh] the restored loader does not compile either; running without it" >&2
      exec "$PYTHON_BIN" -m simorgh run "$@"
    fi
  else
    echo "[sim.sh] simloader.py does not compile and there is no known-good tag to restore from." >&2
    echo "[sim.sh] running Sim directly; fix simloader.py, then run \`python simloader.py bless\`." >&2
    exec "$PYTHON_BIN" -m simorgh run "$@"
  fi
fi

exec "$PYTHON_BIN" simloader.py run "$@"
