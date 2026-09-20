"""`python -m simorgh.evals` (stage 4 item 9).

    python -m simorgh.evals run household --repeats 3
    python -m simorgh.evals run household --json
    python -m simorgh.evals list
    python -m simorgh.evals scenario --verbose     # the household script, per probe

A suite that costs money needs `--paid`. That is not paternalism: the
loader runs `run household` on every bless, and a suite that quietly
spent forty dollars there would be found on a bill rather than in a log.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import sys

from .runner import record, run, table
from .suites import PAID, SUITES


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m simorgh.evals", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    runp = sub.add_parser("run", help="run a suite")
    runp.add_argument("suite", choices=sorted(SUITES))
    runp.add_argument("--repeats", type=int, default=1)
    runp.add_argument("--json", action="store_true")
    runp.add_argument("--paid", action="store_true", help="allow a suite that calls a real model")
    runp.add_argument("--record", default="", metavar="DATA_DIR", help="append the report to DATA_DIR/evals.jsonl")
    runp.add_argument("--verbose", action="store_true", help="let the suite narrate to stdout")
    sub.add_parser("list", help="the suites, and which cost money")
    scen = sub.add_parser("scenario", help="the household script, probe by probe")
    scen.add_argument("--json", action="store_true")
    scen.add_argument("--verbose", action="store_true")
    args, rest = ap.parse_known_args(argv)

    if args.command == "list":
        for name in sorted(SUITES):
            print(f"{name:<12} {'costs money' if name in PAID else 'free'}")
        return 0
    if args.command == "scenario":
        from .scenario import main as scenario_main

        return scenario_main([*(["--json"] if args.json else []), *(["--verbose"] if args.verbose else []), *rest])

    if args.suite in PAID and not args.paid:
        print(f"{args.suite} calls a real model and costs money; pass --paid to run it", file=sys.stderr)
        return 2
    # Suites narrate (the Interface prints every turn); keep that out of
    # the report unless it was asked for.
    sink = io.StringIO()
    with contextlib.redirect_stdout(sys.stdout if args.verbose else sink):
        report = asyncio.run(run(args.suite, repeats=args.repeats))
    if args.record:
        record(report, data_dir=args.record)
    print(json.dumps(report.as_dict(), indent=1) if args.json else table(report))
    return 0 if report.total and report.passed == report.total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
