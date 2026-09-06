#!/usr/bin/env bash
# Opens Simorgh v2's live dashboard (simorgh/interface/httpapi.py) in
# Chrome. That dashboard is served BY a running `python -m simorgh run`
# process -- this script does not start Sim, only points a browser at
# it, so `simorgh run` (or `./sim2.sh`, once that exists) must already
# be up. The port isn't wired to `simorgh.toml`/env overrides yet (see
# docs/EVOLUTION.md milestone 112's own note on this), so it's the
# `InterfaceConfig` default below unless you pass a different URL.
set -euo pipefail

URL="${1:-http://127.0.0.1:8765/}"

if ! curl -s -o /dev/null -m 2 "$URL"; then
  echo "no dashboard reachable at $URL -- is 'python -m simorgh run' running?" >&2
  exit 1
fi

case "$(uname -s)" in
  Darwin)
    open -a "Google Chrome" "$URL" 2>/dev/null || open "$URL"
    ;;
  Linux)
    (command -v google-chrome >/dev/null && google-chrome "$URL") \
      || (command -v google-chrome-stable >/dev/null && google-chrome-stable "$URL") \
      || xdg-open "$URL" &
    ;;
  *)
    echo "unsupported platform -- open manually: $URL" >&2
    exit 1
    ;;
esac
