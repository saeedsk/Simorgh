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
import pathlib
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
    runp.add_argument("--cases", type=int, default=0,
                      help="how many benchmark cases to score (default 5); more is a narrower interval")
    runp.add_argument("--dialect", default="", choices=["", "markers", "native"],
                      help="force the tool dialect for a benchmark suite (stage 2's native-vs-markers question)")
    runp.add_argument("--record", default="", metavar="DATA_DIR", help="append the report to DATA_DIR/evals.jsonl")
    runp.add_argument("--verbose", action="store_true", help="let the suite narrate to stdout")
    sub.add_parser("list", help="the suites, and which cost money")
    house = sub.add_parser("house", help="the household simulator's scenarios (stage 11)")
    house.add_argument("--one", default="", help="one scenario by id, in this process")
    house.add_argument("--only", default="", help="every scenario whose id starts with this")
    house.add_argument("--fast", action="store_true", help="the bless subset: one per stage, free, a few minutes")
    house.add_argument("--timing", action="store_true", help="with --one: where the turn's seconds went")
    house.add_argument("--profile", metavar="PATH", nargs="?", const="-",
                       help="with --one: sample every thread's stack; PATH gets collapsed stacks "
                            "for flamegraph.pl or speedscope", default="")
    house.add_argument("--findings", default="", metavar="PATH", help="write clustered findings there (default docs/findings/<date>-house.md)")
    house.add_argument("--paid", action="store_true",
                       help="let the scenarios reach a real model (costs money; runs the needs_model ones)")
    house.add_argument("--json", action="store_true")
    arcs = sub.add_parser("arcs", help="the companion arcs: weeks of a household (stage 11 item 6)")
    arcs.add_argument("--only", default="", help="one person's arc by name")
    arcs.add_argument("--json", action="store_true")
    scen = sub.add_parser("scenario", help="the household script, probe by probe")
    scen.add_argument("--json", action="store_true")
    scen.add_argument("--verbose", action="store_true")
    args, rest = ap.parse_known_args(argv)

    if args.command == "list":
        for name in sorted(SUITES):
            print(f"{name:<12} {'costs money' if name in PAID else 'free'}")
        return 0
    if args.command == "house":
        if args.paid:
            import os

            # Read by `house/run.py::_a_real_provider`, and by the
            # child process each scenario runs in.
            os.environ["SIMORGH_HOUSE_PAID"] = "1"
        from .house.run import as_json, run_one, run_pack
        from .house.scenarios import all_scenarios, by_id

        if args.one:
            scenario = by_id(args.one)
            if scenario is None:
                print(f"no scenario {args.one!r}", file=sys.stderr)
                return 2
            # In THIS process, so the parent can capture it: the parent
            # is what gives each scenario its own interpreter.
            timings = None
            # The timing table says which SEGMENT is slow; the sampler
            # says which STACK. You want the second one when a segment
            # is slow for no reason the table can see, or when a thread
            # spins with no I/O at all (stage 9 item 5, still open).
            sampler = None
            if args.profile:
                from .house.profile import Sampler

                sampler = Sampler()
            with contextlib.redirect_stdout(io.StringIO()):
                with sampler if sampler is not None else contextlib.nullcontext():
                    if args.timing:
                        from .house.run import run_with_timing

                        outcomes, timings = asyncio.run(run_with_timing(scenario))
                    else:
                        outcomes = asyncio.run(run_one(scenario))
            if timings is not None and not args.json:
                print(timings.render())
                print()
            if sampler is not None and not args.json:
                print(sampler.profile.render())
                if args.profile != "-":
                    pathlib.Path(args.profile).write_text(sampler.profile.collapsed())
                    print(f"\ncollapsed stacks: {args.profile}"
                          f"\n  flamegraph.pl {args.profile} > flame.svg, or open it in speedscope")
                print()
        else:
            from .house.scenarios import fast

            chosen = fast() if args.fast else [s for s in all_scenarios() if s.id.startswith(args.only)]
            outcomes = asyncio.run(run_pack(chosen))
        if args.json:
            print(as_json(outcomes))
        else:
            print(_house_table(outcomes))
        if args.findings or (not args.one and not args.json):
            from datetime import date

            from .house.observer import Findings, cluster, write

            findings = Findings(outcomes=outcomes, clusters=cluster(outcomes))
            where = args.findings or f"docs/findings/{date.today().isoformat()}-house.md"
            print(f"\nfindings: {write(findings, where)}")
        return 0 if all(o.status != "failed" for o in outcomes) else 1

    if args.command == "arcs":
        import json as _json

        from .house.arcs import play
        from .house.arcs import table as arc_table
        from .house.scenarios.companion import ARCS, WANT_RECALL

        chosen = [a for a in ARCS if not args.only or a.person.lower() == args.only.lower()]
        if not chosen:
            print(f"no arc for {args.only!r}; try {', '.join(a.person for a in ARCS)}", file=sys.stderr)
            return 2

        async def _all():
            out = []
            for arc in chosen:
                # One sandbox per arc, and one arc at a time: each is a
                # whole Sim, and two of them in one interpreter is the
                # segfault the runner already forks around.
                with contextlib.redirect_stdout(io.StringIO()):
                    out.append(await play(arc))
            return out

        played = asyncio.run(_all())
        if args.json:
            print(_json.dumps([{"person": p.arc.person, "role": p.arc.role,
                                "consented": p.arc.consented, "offered": p.offered,
                                "recall": p.recall, "precision": p.precision,
                                "nagging": p.nagging, "forbidden": p.forbidden}
                               for p in played], indent=1))
        else:
            print(arc_table(played))
        # The two rules that are not rates: nobody who did not say yes,
        # and nobody asked twice in one stretch.
        strict = sum(p.forbidden + p.nagging for p in played)
        consented = [p.recall for p in played if p.arc.may_be_checked_in_on and p.recall is not None]
        recall = sum(consented) / len(consented) if consented else 1.0
        return 0 if not strict and recall >= WANT_RECALL else 1

    if args.command == "scenario":
        from .scenario import main as scenario_main

        return scenario_main([*(["--json"] if args.json else []), *(["--verbose"] if args.verbose else []), *rest])

    if args.paid:
        # The suites that reach a model read this: a `Runner` takes no
        # arguments, and threading a flag through the registry for one
        # caller would be worse than one variable set right here.
        import os

        os.environ["SIMORGH_EVALS_PAID"] = "1"
    if getattr(args, "dialect", ""):
        os.environ["SIMORGH_EVALS_DIALECT"] = args.dialect
    if getattr(args, "cases", 0):
        os.environ["SIMORGH_EVALS_CASES"] = str(args.cases)
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


def _house_table(outcomes) -> str:
    """The pack as a person reads it: the failures, with the beat."""
    passed = sum(1 for o in outcomes if o.status == "passed")
    lines = [f"house: {passed}/{sum(1 for o in outcomes if o.status != 'skipped')} expectations"]
    for outcome in outcomes:
        if outcome.status != "passed":
            lines.append(f"  {outcome.status:7} {outcome.case.name:30} {outcome.why[:70]}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
