#!/usr/bin/env python3
"""One household scenario, in the foreground, with the transcript as it goes.

Stage 11 item 11. `python -m simorgh.evals house --one <id>` runs a
scenario and prints the verdict; this prints the *conversation* -- who
said what, what Sim said back, what it did to the house, and which
expectation failed next to the beat it failed on.

The difference matters when you are debugging rather than gating. A
red expectation tells you a rule is wrong; the transcript tells you
what the room sounded like when it went wrong, which is the thing you
actually need and the thing a CI line cannot carry.

    tools/house.py stage9/a-lamp-is-not-a-decision
    tools/house.py stage3 --list
    tools/house.py stage6/a-quiet-week --timing

Free by default: the floor provider, a fake house, a fake microphone.
A scenario that needs a model to judge meaning says so and skips,
rather than passing on an answer nobody read.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _scenarios():
    from simorgh.evals.house.scenarios import all_scenarios

    return all_scenarios()


def _matching(query: str):
    scenarios = _scenarios()
    exact = [s for s in scenarios if s.id == query]
    return exact or [s for s in scenarios if s.id.startswith(query)]


GREEN, RED, GREY, YELLOW, OFF = "\033[32m", "\033[31m", "\033[90m", "\033[33m", "\033[0m"


def _plain(stream) -> bool:
    return not getattr(stream, "isatty", lambda: False)()


async def _run(scenario, *, timing: bool) -> int:
    from simorgh.evals.house.run import run_one, run_with_timing

    bare = _plain(sys.stdout)
    def colour(code: str, text: str) -> str:
        return text if bare else f"{code}{text}{OFF}"

    print(colour(GREY, f"── {scenario.id}  (stage {scenario.stage})"))
    if scenario.because:
        print(colour(GREY, f"   because {scenario.because}"))
    print()

    if timing:
        outcomes, table = await run_with_timing(scenario)
    else:
        outcomes, table = await run_one(scenario), None

    # The transcript is on the director's record, which `run_one` owns
    # and closes. What comes back is the verdicts; print those against
    # the beats so a failure is readable without reopening the file.
    failed = 0
    for outcome in outcomes:
        status = str(outcome.status)
        if status == "passed":
            print(f"  {colour(GREEN, '✓')} {outcome.case.name}")
            continue
        if status == "skipped":
            print(f"  {colour(YELLOW, '–')} {outcome.case.name}  {colour(GREY, outcome.why or '')}")
            continue
        failed += 1
        print(f"  {colour(RED, '✗')} {outcome.case.name}")
        if outcome.why:
            print(f"      {outcome.why}")
        detail = getattr(outcome.case, "detail", "")
        if detail:
            for line in str(detail).splitlines():
                print(colour(GREY, f"      {line}"))

    if table is not None:
        print()
        print(table.render() if hasattr(table, "render") else str(table))

    print()
    print(colour(GREY, f"── {len(outcomes) - failed}/{len(outcomes)} expectations"))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario", nargs="?", default="",
                        help="a scenario id, or a prefix (\"stage9\")")
    parser.add_argument("--list", action="store_true", help="what there is to run")
    parser.add_argument("--timing", action="store_true", help="also where the turn's seconds went")
    args = parser.parse_args(argv)

    if args.list or not args.scenario:
        for scenario in _scenarios():
            print(f"  {scenario.id:52} {scenario.because}")
        return 0

    found = _matching(args.scenario)
    if not found:
        print(f"no scenario matches {args.scenario!r}; `--list` shows them all", file=sys.stderr)
        return 2
    if len(found) > 1:
        # A prefix that matches several is almost always a typo away
        # from the one that was meant, and running six scenarios in the
        # foreground when one was asked for wastes the minutes this
        # tool exists to save.
        print(f"{args.scenario!r} matches {len(found)}:", file=sys.stderr)
        for scenario in found:
            print(f"  {scenario.id}", file=sys.stderr)
        print("run `python -m simorgh.evals house --only <prefix>` for the set", file=sys.stderr)
        return 2
    return asyncio.run(_run(found[0], timing=args.timing))


if __name__ == "__main__":
    raise SystemExit(main())
