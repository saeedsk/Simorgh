#!/usr/bin/env python3
"""Send one command to the Sim running in this house.

    python tools/sim_say.py restart
    python tools/sim_say.py "benchmark run swebench-verified 30"
    python tools/sim_say.py --host 192.168.50.10 status

It posts the line to `POST /api/command`, which runs it through the same
path as typing it at Sim's keyboard -- so Guardian gates whatever it
does, and the line is echoed on Sim's own screen. Only COMMANDS: to talk
to Sim, use the dashboard or `/api/chat`.

The token is `SIM_API_TOKEN` from the environment or `~/.simorgh/secrets.toml`.

Why it exists: on 2026-09-22 the creator was away from the house, asked
for Sim to be restarted so it would pick up a fix, and there was no
channel that could carry a command -- only conversation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path


def token() -> str:
    from_env = os.environ.get("SIM_API_TOKEN", "").strip()
    if from_env:
        return from_env
    path = Path(os.environ.get("SIMORGH_SECRETS") or Path.home() / ".simorgh" / "secrets.toml")
    try:
        return str(tomllib.loads(path.read_text()).get("SIM_API_TOKEN") or "").strip()
    except (OSError, tomllib.TOMLDecodeError):
        return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("line", nargs="+", help="the command, as you would type it")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()
    line = " ".join(args.line)
    body = json.dumps({"line": line}).encode()
    headers = {"Content-Type": "application/json"}
    key = token()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        f"http://{args.host}:{args.port}/api/command", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:  # noqa: S310 -- operator-supplied host
            print(f"{response.status} {response.read().decode()}")
            return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        print(f"{exc.code}: {detail}", file=sys.stderr)
        # The two that have a specific thing to do about them.
        if exc.code == 401:
            print("SIM_API_TOKEN did not match the running instance.", file=sys.stderr)
        if exc.code == 400 and "not_a_command" in detail:
            print(f"{line!r} is conversation, not a command -- say it on the dashboard.", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"no Sim answering on {args.host}:{args.port} ({exc})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
