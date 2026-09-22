"""The night's measuring step: a proposed rule, run on its held-out suite
with and without it (stage 8 item 5, the live half).

`evaluate.measure_and_decide` knew how to judge a candidate since
2026-09-22 and nothing ever called it, so no policy could be adopted.
This is the caller. For each PROPOSED `rule` the night:

1. looks up the task type's held-out suite (`[growth] held_out`, task
   type -> an evals suite name). No suite, no measurement: the policy
   stays proposed and the night's record says why. Never adopted blind;
2. prices it -- `2 x repeats` runs of the suite, each charged the
   suite's own spend cap (`measure_usd_per_run`) -- so `run_night` can
   refuse it BEFORE any money is spent when the night cannot cover it;
3. runs each side in a fresh copy of the repo (`git archive HEAD`,
   never the live checkout): the baseline copy as committed, the
   candidate copy with the rule appended to `rules/<task_type>.md`,
   which `orchestration/profiles.py` puts into the agent body of the
   Sim booted from that copy. The suite runs as `python -m simorgh.evals
   run <suite> --json` in a child interpreter whose cwd and PYTHONPATH
   are the copy, so the copy's `rules/` is the one it reads;
4. hands the result to `measure_and_decide`, which refuses on any
   regressed case and otherwise lets `adopt` decide. An adopted rule
   is LANDED by publishing `action.proposed(policy_adopt)`; Guardian
   asks a person before `rules/` changes.

The whole thing is OFF unless `[growth] measure_policies = true`: the
suites that can measure a rule cost money, and the creator approves paid
runs explicitly.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from .evaluate import DEFAULT_REPEATS, measure_and_decide

#: The checkout the live Sim runs from; the copies are made from its HEAD.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: What one run of a held-out suite may cost, unless configured: the
#: benchmark sandbox's own cap (`evals/house/bench.py::SPEND_CAP_USD`).
#: The estimate is the cap, not a guess, so the night's check before the
#: step is a real bound.
DEFAULT_USD_PER_RUN = 0.50
#: Cases per run (`python -m simorgh.evals run --cases`).
DEFAULT_CASES = 5
#: One run of a suite, wall clock, before it is abandoned.
DEFAULT_TIMEOUT_S = 1800.0

#: `spawn(argv, cwd, env, timeout) -> (returncode, stdout, stderr)`.
Spawn = Callable[[list[str], str, dict, float], Awaitable[tuple[int, str, str]]]


@dataclass(frozen=True)
class MeasureConfig:
    """The `[growth]` keys this step reads (all in CONTRACT.md)."""

    enabled: bool = False
    held_out: dict[str, str] = field(default_factory=dict)
    repeats: int = DEFAULT_REPEATS
    usd_per_run: float = DEFAULT_USD_PER_RUN
    cases: int = DEFAULT_CASES
    timeout_s: float = DEFAULT_TIMEOUT_S

    def est_usd(self) -> float:
        """Both sides, every repeat, each at its cap."""
        return 2 * self.repeats * self.usd_per_run


def _num(value, default, cast, floor):
    try:
        return max(floor, cast(value))
    except (TypeError, ValueError):
        return default


def measure_config(config) -> MeasureConfig:
    """`[growth]` -> MeasureConfig. Anything unreadable falls back to
    the safe reading: off, no suites, the default price. A malformed
    price falls back to the default rather than to zero, because a zero
    price is a step the budget can never refuse."""
    section = config if isinstance(config, dict) else {}
    enabled = section.get("measure_policies", False) is True
    raw = section.get("held_out")
    held_out = ({str(k): str(v) for k, v in raw.items() if isinstance(v, str) and v.strip()}
                if isinstance(raw, dict) else {})
    return MeasureConfig(
        enabled=enabled, held_out=held_out,
        repeats=_num(section.get("measure_repeats", DEFAULT_REPEATS), DEFAULT_REPEATS, int, 1),
        usd_per_run=_num(section.get("measure_usd_per_run", DEFAULT_USD_PER_RUN),
                         DEFAULT_USD_PER_RUN, float, 0.0),
        cases=_num(section.get("measure_cases", DEFAULT_CASES), DEFAULT_CASES, int, 1),
        timeout_s=_num(section.get("measure_timeout_s", DEFAULT_TIMEOUT_S), DEFAULT_TIMEOUT_S, float, 1.0),
    )


async def _spawn(argv: list[str], cwd: str, env: dict, timeout: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*argv, cwd=cwd, env=env, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -9, "", f"timed out after {timeout:.0f}s"
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def copy_repo(repo: Path, into: Path) -> Path:
    """The committed tree of `repo` at HEAD, extracted into `into`.

    `git archive` rather than a worktree or a copytree: it touches
    nothing in the live repo (no worktree metadata, no index), and it
    leaves behind the untracked gigabytes under `workspace/`.
    """
    tar = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "HEAD"],
                         capture_output=True, check=True, timeout=300)
    into.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(tar.stdout)) as archive:
        archive.extractall(into, filter="data")
    return into


def place_rule(copy: Path, task_type: str, rule: str) -> Path:
    """Append the candidate to the copy's `rules/<task_type>.md`, after
    whatever was already adopted there -- the candidate is measured on
    top of what the live Sim already reads, not instead of it."""
    path = copy / "rules" / f"{task_type}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8").rstrip() if path.exists() else ""
    path.write_text((existing + "\n\n" if existing else "") + rule.strip() + "\n", encoding="utf-8")
    return path


class SuiteCases:
    """`run_cases(rules)` for one task type: one run of its held-out
    suite in a fresh repo copy, as `{case: passed}`.

    Skipped cases (a provider outage, a missing attachment) are left out
    rather than counted as failures, so they cannot fix or break
    anything. What each run reported spending is added to `spent_usd`;
    a run that reports nothing is charged `usd_per_run`, because
    guessing zero is how a budget stops being one.
    """

    def __init__(self, suite: str, task_type: str, cfg: MeasureConfig, *, repo: Path = REPO_ROOT,
                 spawn: Spawn = _spawn, copy=copy_repo, scratch: str | None = None) -> None:
        self.suite, self.task_type, self.cfg = suite, task_type, cfg
        self._repo, self._spawn, self._copy, self._scratch = Path(repo), spawn, copy, scratch
        self.spent_usd = 0.0
        self.runs = 0

    async def __call__(self, rules: str | None) -> dict[str, bool]:
        tmp = Path(tempfile.mkdtemp(prefix="simorgh-measure-", dir=self._scratch))
        try:
            copy = await asyncio.to_thread(self._copy, self._repo, tmp / "repo")
            if rules:
                place_rule(Path(copy), self.task_type, rules)
            env = {**os.environ, "SIMORGH_EVALS_ONE": "1",
                   "PYTHONPATH": os.pathsep.join(p for p in (str(copy), os.environ.get("PYTHONPATH", "")) if p)}
            argv = [sys.executable, "-m", "simorgh.evals", "run", self.suite, "--repeats", "1", "--json",
                    "--paid", "--cases", str(self.cfg.cases)]
            code, out, err = await self._spawn(argv, str(copy), env, self.cfg.timeout_s)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.runs += 1
        try:
            rows = list(json.loads(out).get("cases") or [])
        except (ValueError, AttributeError):
            self.spent_usd += self.cfg.usd_per_run
            raise RuntimeError(f"{self.suite} did not report (exit {code}): {(err or out).strip()[-200:]}")
        self.spent_usd += _cost(rows, self.cfg.usd_per_run)
        return {str(r.get("name") or ""): r.get("status") == "passed"
                for r in rows if r.get("status") in ("passed", "failed") and r.get("name")}


def _cost(rows: list[dict], fallback: float) -> float:
    reported = False
    total = 0.0
    for row in rows:
        for value in (row.get("cost_usd"), (row.get("detail") or {}).get("cost_usd")):
            if value is None:
                continue
            reported = True
            try:
                total += max(0.0, float(value))
            except (TypeError, ValueError):
                pass
            break
    return total if reported else fallback


async def measure_one(store, policy, cfg: MeasureConfig, *, land, samples_now: int = 0,
                      cases_for=None) -> dict:
    """Measure one proposed rule; the night step's result.

    `cases_for(suite, task_type, cfg) -> SuiteCases` is the seam a test
    replaces; everything else is the production path.
    """
    suite = cfg.held_out.get(policy.task_type, "")
    if not suite:
        return {"skipped": f"no held-out suite for {policy.task_type or 'untyped'} work "
                           f"([growth] held_out); left proposed", "spent_usd": 0.0}
    run = (cases_for or SuiteCases)(suite, policy.task_type, cfg)
    try:
        decided, ev = await measure_and_decide(store, policy.id, run, repeats=cfg.repeats,
                                               samples_now=samples_now, land=land)
    finally:
        spent = float(getattr(run, "spent_usd", 0.0))
    if ev is None:
        return {"detail": "no longer proposed", "spent_usd": spent}
    if decided is None or decided.status == "proposed":
        return {"detail": f"{suite}: no case counted on both sides; left proposed", "spent_usd": spent}
    return {"detail": (f"{suite}: {decided.status} ({ev.result:.2f} against {ev.baseline:.2f} over "
                       f"{ev.evaluated_on}; fixed {len(ev.fixed)}, regressed {len(ev.regressed)})"),
            "spent_usd": spent}


__all__ = ["DEFAULT_CASES", "DEFAULT_USD_PER_RUN", "MeasureConfig", "SuiteCases", "copy_repo",
           "measure_config", "measure_one", "place_rule"]
