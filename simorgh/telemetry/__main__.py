"""`python -m simorgh.telemetry tokens [--since 7d] [--file PATH | --data-dir DIR] [--json]`
and `python -m simorgh.telemetry routing [--since 7d] [--mode shadow|on] [same file options]`.

Reads the telemetry file read-only. The file is `<data_dir>/telemetry.sqlite`;
without `--file` or `--data-dir`, `data_dir` is `SIMORGH_RUNTIME_DATA_DIR`
or `~/.simorgh`, the Kernel's own default (telemetry may not import the
Kernel's config loader, so a `data_dir` set only in simorgh.toml needs
`--data-dir`)."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from . import routing
from .service import FILENAME
from .tokens import format_report, parse_since, report


def _path(args, parser: argparse.ArgumentParser) -> Path:
    if args.file and args.data_dir:
        parser.error("--file and --data-dir are mutually exclusive")
    if args.file:
        return Path(args.file).expanduser()
    data_dir = args.data_dir or os.environ.get("SIMORGH_RUNTIME_DATA_DIR") or "~/.simorgh"
    return Path(data_dir).expanduser() / FILENAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simorgh.telemetry")
    sub = parser.add_subparsers(dest="command", required=True)
    tokens = sub.add_parser("tokens", help="where a turn's input tokens go, and the cache hit rate")
    route = sub.add_parser("routing", help="the tool router's shadow record: miss rate and per-group counts")
    route.add_argument("--mode", choices=sorted(routing.SPANS), default="shadow",
                       help="which record to read: shadow (default) or on")
    for command in (tokens, route):
        command.add_argument("--since", default="7d", help="period to read: 7d, 12h, 30m (default 7d)")
        command.add_argument("--file", help="a telemetry.sqlite file")
        command.add_argument("--data-dir", help="the data directory holding telemetry.sqlite")
        command.add_argument("--json", action="store_true", help="print the summary as JSON")
    args = parser.parse_args(argv)
    try:
        since_s = parse_since(args.since)
    except ValueError as exc:
        parser.error(str(exc))
    path = _path(args, parser)
    if not path.exists():
        print(f"{args.command}: no telemetry file at {path}", file=sys.stderr)
        return 1
    try:
        if args.command == "routing":
            result = routing.report(path, since_s=since_s, mode=args.mode)
            text = routing.format_report
        else:
            result = report(path, since_s=since_s)
            text = format_report
    except sqlite3.Error as exc:
        print(f"{args.command}: cannot read {path}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(text(result), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
