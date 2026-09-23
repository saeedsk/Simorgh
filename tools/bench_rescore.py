#!/usr/bin/env python3
"""Re-judge a finished SWE-bench run from the logs it already wrote.

    python tools/bench_rescore.py                 # the most recent run
    python tools/bench_rescore.py --run cd41919dda39
    python tools/bench_rescore.py --json out.json

Every case in a SWE-bench run leaves its container log under
`results/swebench/<case>.log`. That log, plus the dataset row, is
everything `swebench.judge` needs -- so a fix to the LOG READER can be
applied to runs that are already paid for, instead of spending another
two hours and another dollar to ask the same models the same questions.

Why it exists (2026-09-22): a 30-case run reported 12 correct and threw
nine cases away as "named test(s) never appeared in the log". Four
parser bugs were found and fixed that evening, and re-judging the same
logs turned five of those nine into real verdicts -- three of them
RESOLVED. That re-judging was done by hand, in a throwaway script, which
is no way to check whether a harness fix helped.

This never re-runs a model and never writes to the ledger: it reads
what is on disk and prints what the run WOULD have scored.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


async def _load_run(run_id: str):
    from simorgh.benchmark.store import RunStore
    from simorgh.ledger.factory import make_ledger

    # The live ledger, read-only: the same `~/.simorgh/ledger` the
    # running Sim writes its runs to.
    ledger = make_ledger({"backend": "jsonl", "data_dir": str(Path.home() / ".simorgh" / "ledger")})
    await ledger.start()
    try:
        runs = [r for r in await RunStore(ledger).history(limit=200) if r.suite.startswith("swebench")]
        if not runs:
            raise SystemExit("no SWE-bench run in the ledger")
        if run_id:
            runs = [r for r in runs if r.run_id == run_id]
            if not runs:
                raise SystemExit(f"no run {run_id!r}")
        # The summary carries only totals; the per-case detail (which
        # case, and what it scored) lives in a blob beside it. Without
        # it every case reads as unnamed and nothing can be re-judged.
        return await RunStore(ledger).detail(runs[-1].run_id) or runs[-1]
    finally:
        await ledger.stop()


def rescore(run, rows: dict, logs: Path) -> list[dict]:
    """One row per case: what it scored then, what it scores now."""
    from simorgh.benchmark import swebench

    out: list[dict] = []
    for result in run.results:
        case_id = result.case_id
        row, log = rows.get(case_id), logs / f"{case_id}.log"
        if not case_id or row is None or not log.is_file():
            out.append({"case": case_id or "(unnamed)", "was": _state(result), "now": "no log kept"})
            continue
        verdict = swebench.judge(log.read_text(errors="replace"), row)
        out.append({
            "case": case_id, "was": _state(result),
            "now": "resolved" if verdict.resolved else ("unmeasurable" if verdict.skipped else "miss"),
            "detail": verdict.detail[:100],
        })
    return out


def _state(result) -> str:
    return "resolved" if result.correct else ("unmeasurable" if result.skipped else "miss")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", default="", help="a run id; the most recent SWE-bench run by default")
    ap.add_argument("--logs", default="results/swebench")
    ap.add_argument("--json", default="", metavar="PATH")
    args = ap.parse_args()

    dataset = Path.home() / ".simorgh" / "benchmarks" / "swebench-verified.json"
    if not dataset.is_file():
        raise SystemExit(f"no dataset at {dataset} -- `benchmark load swebench-verified` first")
    rows = {r["instance_id"]: r for r in json.loads(dataset.read_text())["rows"]}

    run = asyncio.run(_load_run(args.run))
    scored = rescore(run, rows, REPO / args.logs)
    changed = [r for r in scored if r["was"] != r["now"]]
    for row in scored:
        mark = "  " if row["was"] == row["now"] else "->"
        print(f"{mark} {row['case']:28} {row['was']:13} {row['now']:13} {row.get('detail', '')[:60]}")

    now_resolved = sum(1 for r in scored if r["now"] == "resolved")
    now_unmeasurable = sum(1 for r in scored if r["now"] == "unmeasurable")
    print(f"\nrun {run.run_id} ({run.suite}, {run.model})")
    print(f"  then: {run.correct}/{len(run.results)} resolved, {run.skipped} unmeasurable")
    print(f"  now : {now_resolved}/{len(scored)} resolved, {now_unmeasurable} unmeasurable")
    print(f"  {len(changed)} case(s) changed verdict -- re-judged from logs, no model was asked")
    if args.json:
        Path(args.json).write_text(json.dumps(scored, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
