"""Cluster a wave's findings so a human reads one triage list, not ten
essays.

Four observers finding the identical marker-truncation bug independently
is real confirmation and should read as ONE line with four names behind
it, not four paragraphs a coordinator has to notice are the same thing.
This groups by `(file, category)` when both are given, falling back to
`(category, a normalized prefix of summary)` when a finding has no file
-- most CLI/behavioural findings don't -- and ranks the result by
severity, then by how many independent observers hit it.

Usage:

    python tools/aggregate_findings.py <run_id>
    python tools/aggregate_findings.py <run_id> --json

`run_id` is whatever was set as `SIMORGH_OBSERVER_RUN_ID` for the wave
(or passed explicitly to `record_finding`). With no `run_id`, lists the
run ids that have findings recorded.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `tools/` is not a package
from observer_kit import FINDINGS_ROOT, Finding, load_findings  # noqa: E402

_SEVERITY_ORDER = {"blocker": 0, "degraded": 1, "cosmetic": 2}
_WORD = re.compile(r"[a-z0-9]+")


def _fallback_key(finding: Finding) -> str:
    """A signature for findings with no file. A `category` slug is the
    real signal here -- ask observers to set one -- so trust it outright
    when given. Only a genuinely uncategorized finding falls back to the
    first few significant words of its summary, which is a much weaker
    signal and will under-merge more often than it over-merges; that is
    the safer failure for a triage aid, so it stays a last resort rather
    than the default."""
    if finding.category:
        return finding.category
    words = _WORD.findall(finding.summary.lower())
    return "|".join(words[:4])


def cluster(findings: list[Finding]) -> list[dict]:
    groups: dict[tuple, list[Finding]] = defaultdict(list)
    for finding in findings:
        key = (finding.file, finding.category) if finding.file else ("", _fallback_key(finding))
        groups[key].append(finding)

    clusters = []
    for members in groups.values():
        severity = min((m.severity for m in members), key=lambda s: _SEVERITY_ORDER.get(s, 9))
        clusters.append({
            "severity": severity,
            "observers": sorted({m.observer for m in members}),
            "count": len(members),
            "file": members[0].file,
            "line": members[0].line,
            "category": members[0].category,
            "summaries": [m.summary for m in members],
            "evidence": [m.evidence for m in members if m.evidence],
            "fix_suggested": next((m.fix_suggested for m in members if m.fix_suggested), ""),
        })
    clusters.sort(key=lambda c: (_SEVERITY_ORDER.get(c["severity"], 9), -c["count"]))
    return clusters


def render(clusters: list[dict]) -> str:
    lines = []
    for c in clusters:
        where = f"{c['file']}:{c['line']}" if c["file"] else (c["category"] or "(uncategorized)")
        confirmed = f" -- confirmed by {c['count']} observer(s): {', '.join(c['observers'])}" if c["count"] > 1 else \
                    f" ({c['observers'][0]})"
        lines.append(f"[{c['severity'].upper():8s}] {where}{confirmed}")
        lines.append(f"  {c['summaries'][0]}")
        if c["fix_suggested"]:
            lines.append(f"  fix: {c['fix_suggested']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if lines else "(no findings recorded for this run)\n"


def _list_runs() -> list[str]:
    if not FINDINGS_ROOT.exists():
        return []
    return sorted(p.stem for p in FINDINGS_ROOT.glob("*.jsonl"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_id", nargs="?", help="the wave's SIMORGH_OBSERVER_RUN_ID")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if not args.run_id:
        runs = _list_runs()
        if not runs:
            print("no observer runs recorded yet (scratchpad/observers/findings/ is empty)")
            return 0
        print("recorded runs:\n  " + "\n  ".join(runs))
        return 0

    findings = load_findings(args.run_id)
    clusters = cluster(findings)
    if args.json:
        print(json.dumps(clusters, indent=2))
    else:
        print(f"{len(findings)} finding(s) from {len(clusters)} distinct issue(s), run {args.run_id!r}\n")
        print(render(clusters))
    return 0


if __name__ == "__main__":
    sys.exit(main())
