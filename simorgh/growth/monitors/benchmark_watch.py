"""Benchmark-outcome watcher: failing benchmark cases become candidates.

An observer, like the rest of the monitors. It reads recent
`benchmark:runs` records and writes one `growth:candidates` row per
failing case, into the same stream the monitors already feed, so the
counting that `diagnose.cluster()` does sees recurring benchmark
failures alongside everything else. It emits and nothing more: it never
writes `self:model`, never acts, and adopting a lesson is the policy
store's job, with a measurement.
"""

from __future__ import annotations

from typing import Awaitable, Callable

CANDIDATES_STREAM = "growth:candidates"
SOURCE = "benchmark"


def _failed_check(case) -> str:
    if getattr(case, "error", ""):
        return "case_ran"
    if getattr(case, "blocked_by", ""):
        return f"not_blocked:{case.blocked_by}"
    return "answer_correct"


def _reason(case) -> str:
    if getattr(case, "error", ""):
        return str(case.error)
    if getattr(case, "blocked_by", ""):
        return f"stopped by {case.blocked_by}"
    expected = getattr(case, "expected", "")
    answer = getattr(case, "answer", "")
    return f"expected {expected!r}, got {answer!r}"


def failing_candidates(records) -> list[dict]:
    """One candidate payload per failing (scored, not skipped) case.

    `records` are `RunRecord`s (duck-typed: `suite`, `run_id`, `results`).
    A skipped case was never fairly asked, so it is not a failure.
    """
    found: list[dict] = []
    for record in records:
        suite = getattr(record, "suite", "") or "unknown"
        run_id = getattr(record, "run_id", "")
        for case in getattr(record, "results", None) or []:
            if getattr(case, "skipped", False) or getattr(case, "correct", True):
                continue
            failed_check = _failed_check(case)
            reason = _reason(case)
            found.append({
                "source": SOURCE,
                "subject": f"{suite}/{case.case_id}",
                "kind": "patch",
                "what": f"benchmark case {case.case_id} failed: {failed_check}",
                "count": 1,
                "evidence": [run_id] if run_id else [],
                "failed_check": failed_check,
                "reason": reason,
            })
    return found


async def watch(store, append: Callable[[str, str, dict], Awaitable[None]], *,
                suite: str = "", limit: int = 20) -> list[dict]:
    """Read the most recent `limit` runs and emit a candidate per failure.

    `store` is a `RunStore` (only `history` is used); `append` is the
    monitor's `_append(stream, event_type, payload)`. Only
    `growth:candidates` is written.
    """
    records = await store.history(suite=suite, limit=limit)
    found = failing_candidates(records)
    for payload in found:
        await append(CANDIDATES_STREAM, "candidate", payload)
    return found


__all__ = ["CANDIDATES_STREAM", "SOURCE", "failing_candidates", "watch"]
