#!/usr/bin/env python3
"""Run many Sims at once, for hours, and write down what breaks.

    python tools/soak.py --instances 8 --hours 8
    python tools/soak.py --instances 2 --hours 0.5 --jobs house-fast,suite
    python tools/soak.py --report                      # what the run has found

The creator, going out for the evening of 2026-09-22: "start running sim
in simulation mode in 8 instances and start testing it and observe, find
bugs and fix them ... continue this test for next 8 hours and
automatically fix and commit".

Each instance gets its OWN COPY of the repository (`fast_copy_repo`:
copy-on-write on APFS, so eight copies cost about what one read costs)
and its own data directory. Nothing here touches the live Sim, the live
ledger, or the checkout the creator is using -- the lesson of
2026-09-06, when a sandboxed run with only its HOME moved committed into
the real project.

What it runs, cycling so a failure is retried on fresh ground rather
than repeated in a poisoned sandbox:

  house        the household simulator, all scenarios (`simorgh.evals
               house`) -- a whole simulated family talking to Sim
  house-fast   the bless subset, quick, for a fast loop
  arcs         weeks of household life compressed (`simorgh.evals arcs`)
  suite        that instance's module tier of the unit tests
  trial        one real watched task in the sandbox (`tools/trial.py`)

Every failure becomes a JSON line under `workspace/soak/<run>/`: what
ran, what it said, and the last of its output. `--report` clusters them
by the first line of the failure, so eight instances finding the same
bug read as one bug with eight witnesses.

FREE by default. `--paid` lets the jobs that need a real model run one;
without it those scenarios skip themselves, and everything else still
exercises the whole system against the floor provider.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

#: Where a run's sandboxes and findings live: OUTSIDE the repository,
#: on the same filesystem so the clone is still copy-on-write. Inside
#: it, `fast_copy_repo` refuses -- the copy would recurse into its own
#: output -- and that refusal is right.
SOAK_DIR = Path(os.environ.get("SIMORGH_SOAK_DIR") or (Path.home() / "simorgh-soak"))

#: One job = a name and the argv to run inside a sandbox.
JOBS: dict[str, list[str]] = {
    "house": [sys.executable, "-m", "simorgh.evals", "house", "--json"],
    "house-fast": [sys.executable, "-m", "simorgh.evals", "house", "--fast", "--json"],
    "arcs": [sys.executable, "-m", "simorgh.evals", "arcs", "--json"],
    "suite": [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", "-m", "not live and not slow"],
    "trial": [sys.executable, "tools/trial.py", "--task", "read simorgh/kernel/service.py and say what boots first"],
}
#: The order instances take jobs in, so eight instances are not all
#: doing the same thing at the same moment.
DEFAULT_ROTATION = ("house-fast", "house", "suite", "house-fast", "arcs", "house", "house-fast", "suite")
#: A job that has not printed anything for this long is wedged, and a
#: wedged job is a finding of its own.
JOB_TIMEOUT_S = 2400.0


@dataclass
class Instance:
    """One sandboxed Sim. Odd-numbered ones run the creator's own
    `simorgh.toml`; even ones run the defaults."""

    number: int
    root: Path
    data: Path
    jobs: list[str]
    runs: int = 0
    failures: int = 0
    current: str = ""
    history: list[str] = field(default_factory=list)


def _log(run_dir: Path, kind: str, **fields) -> None:
    line = json.dumps({"at": round(time.time(), 1), "kind": kind, **fields}, ensure_ascii=False)
    with (run_dir / "soak.jsonl").open("a", encoding="utf-8") as out:
        out.write(line + "\n")


def make_instance(run_dir: Path, number: int, rotation: tuple[str, ...]) -> Instance:
    from tools.observer_kit import fast_copy_repo

    root = run_dir / f"sim{number}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    fast_copy_repo(root, source=REPO)
    # ...without the household's `workspace/`: several gigabytes of
    # models, venvs, camera stills and TTS samples that no scenario
    # needs. The clone is copy-on-write, so it costs nothing until
    # something WRITES -- and eight sandboxes running for an hour wrote
    # enough of it to take 8 GB of free space (2026-09-23). The
    # directory itself stays, because tools expect it to exist.
    workspace = root / "workspace"
    if workspace.is_dir():
        shutil.rmtree(workspace, ignore_errors=True)
    (workspace / "scratch").mkdir(parents=True, exist_ok=True)
    (workspace / "README.md").write_text("A sandbox's workspace: shared models, nothing else (tools/soak.py).\n")
    # ...except the models, which the scenarios DO need: stripping the
    # whole directory broke every voice beat with `kokoro model files
    # not found` -- the soak catching its own regression within the
    # hour (2026-09-23). Symlinked, not copied: they are read-only and
    # several gigabytes, and a link cannot diverge.
    for shared in ("voice/models", "voice/venvs", "voice/references", "voice/prompts", "voice/engines"):
        source = REPO / "workspace" / shared
        if not source.exists():
            continue
        link = workspace / shared
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            link.symlink_to(source, target_is_directory=True)
        except OSError:
            pass
    data = root / "sandbox-home"
    (data / ".simorgh").mkdir(parents=True, exist_ok=True)
    # Half the instances run the CREATOR'S OWN settings, not the
    # defaults. His house is `barge_in = false`, `vad_sensitivity =
    # high`, `speaker_threshold = 0.2`, kokoro, a 0.0.0.0 bind -- and a
    # scenario that passes on defaults can fail on the configuration
    # somebody actually lives with. Copied WITHOUT secrets: the file
    # holds none (they live in secrets.toml, which is not copied), and
    # a soak that could spend money is not a soak (2026-09-23).
    if number % 2 == 1:
        live = Path.home() / ".simorgh" / "simorgh.toml"
        if live.is_file():
            shutil.copy2(live, data / ".simorgh" / "simorgh.toml")
    jobs = list(rotation[number % len(rotation):]) + list(rotation[:number % len(rotation)])
    return Instance(number=number, root=root, data=data, jobs=jobs)


def env_for(inst: Instance, *, paid: bool) -> dict:
    """A sandbox's environment: its own home, its own ledger, no keys
    unless the run is paid for.

    `SIMORGH_DATA_DIR` and `HOME` both move, because a subsystem that
    reads `~/.simorgh` directly -- and several do -- would otherwise
    write into the creator's own house while he is out.
    """
    env = dict(os.environ)
    env.update({
        "HOME": str(inst.data),
        "SIMORGH_DATA_DIR": str(inst.data / ".simorgh"),
        "SIMORGH_LEDGER_DIR": str(inst.data / ".simorgh" / "ledger"),
        "SIMORGH_NO_LOADER": "1",
        "SIMORGH_COGNITION_PROVIDER_ORDER": "floor" if not paid else env.get("SIMORGH_COGNITION_PROVIDER_ORDER", "together,floor"),
        "SIMORGH_SOAK": f"sim{inst.number}",
        "PYTHONUNBUFFERED": "1",
    })
    if not paid:
        # Not "please do not spend money": no key to spend it with.
        for key in ("TOGETHER_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            env.pop(key, None)
    return env


async def run_job(inst: Instance, job: str, run_dir: Path, *, paid: bool) -> bool:
    argv = JOBS[job]
    if job == "suite":
        # A different slice per instance, so eight of them cover the
        # suite rather than running the same third of it eight times.
        # Directories that actually hold tests: `__pycache__` is a
        # directory too, and pytest's "no tests ran" exit 5 was the
        # soak's first finding -- about the soak (2026-09-23).
        modules = sorted(p.name for p in (inst.root / "tests" / "simorgh").iterdir()
                         if p.is_dir() and not p.name.startswith("_") and any(p.glob("test_*.py")))
        argv = [*argv, f"tests/simorgh/{modules[inst.number % len(modules)]}"]
    inst.current = job
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(inst.root), env=env_for(inst, paid=paid),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except OSError as exc:
        _log(run_dir, "finding", instance=inst.number, job=job, why=f"could not start: {exc}")
        return False
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=JOB_TIMEOUT_S)
        code = proc.returncode
    except asyncio.TimeoutError:
        proc.kill()
        out, code = b"", -9
        _log(run_dir, "finding", instance=inst.number, job=job, seconds=round(time.monotonic() - started, 1),
             why=f"wedged: no result in {JOB_TIMEOUT_S:.0f}s", tail="")
        inst.failures += 1
        return False
    text = out.decode(errors="replace")
    inst.runs += 1
    ok = code == 0 and not _failed_expectations(job, text)
    if not ok:
        inst.failures += 1
        # The WHOLE output in a file of its own, and the failing
        # expectations -- not the last 4,000 characters, which for a
        # house run is the tail of a long JSON array of passes with the
        # failure cut off the front. The soak's first real finding was
        # unreadable for exactly that reason (2026-09-23).
        where = run_dir / f"fail-{inst.number}-{job}-{int(time.time())}.log"
        try:
            where.write_text(text, encoding="utf-8")
        except OSError:
            where = Path("")
        _log(run_dir, "finding", instance=inst.number, job=job, code=code,
             seconds=round(time.monotonic() - started, 1),
             why=_why(job, text, code), failed=_failed_rows(job, text), log=str(where),
             tail=text[-1500:])
    else:
        _log(run_dir, "ok", instance=inst.number, job=job, seconds=round(time.monotonic() - started, 1))
    inst.history.append(f"{job}:{'ok' if ok else 'FAIL'}")
    # The data a run left behind, gone before the next one. Eight
    # sandboxes writing ledgers, logs and telemetry for eight hours ate
    # 8 GB of free space in fifty minutes (2026-09-23) -- and a fresh
    # data directory is better science anyway: a scenario that only
    # passes because a previous run's memory is still there is not
    # passing.
    for leftover in ("ledger", "logs", "telemetry.sqlite", "telemetry.sqlite-wal", "telemetry.sqlite-shm"):
        target = inst.data / ".simorgh" / leftover
        try:
            shutil.rmtree(target) if target.is_dir() else target.unlink(missing_ok=True)
        except OSError:
            pass
    return ok


def _failed_rows(job: str, text: str) -> list[dict]:
    """The expectations that failed, with the beat that broke them."""
    if not job.startswith(("house", "arcs")):
        return []
    try:
        rows = json.loads(text[text.index("["):text.rindex("]") + 1])
    except (ValueError, IndexError):
        return []
    return [{"name": r.get("name"), "why": str(r.get("why") or "")[:300],
             "scenario": (r.get("detail") or {}).get("scenario", ""),
             "beat": str((r.get("detail") or {}).get("beat", ""))[:200]}
            for r in rows if str(r.get("status")) == "failed"][:20]


def _failed_expectations(job: str, text: str) -> bool:
    """A house run exits 0 and reports its failures in JSON."""
    if not job.startswith(("house", "arcs")):
        return False
    try:
        rows = json.loads(text[text.index("["):text.rindex("]") + 1])
    except (ValueError, IndexError):
        return False
    return any(str(r.get("status")) == "failed" for r in rows)


def _why(job: str, text: str, code: int) -> str:
    """One line: what a person would say broke."""
    if job.startswith(("house", "arcs")):
        try:
            rows = json.loads(text[text.index("["):text.rindex("]") + 1])
            bad = [r for r in rows if str(r.get("status")) == "failed"]
            if bad:
                first = bad[0]
                where = (first.get("detail") or {}).get("scenario", "")
                return f"{where}: {first.get('name')} -- {str(first.get('why') or '')[:160]}"
        except (ValueError, IndexError):
            pass
    for line in reversed(text.strip().splitlines()):
        if any(mark in line for mark in ("Error", "error:", "FAILED", "assert", "Traceback", "refused")):
            return line.strip()[:200]
    return f"exit {code}"


async def drive(inst: Instance, run_dir: Path, *, until: float, paid: bool,
                refresh_s: float = 0.0, rotation: tuple[str, ...] = ()) -> None:
    next_refresh = time.monotonic() + refresh_s if refresh_s else 0.0
    while time.monotonic() < until:
        job = inst.jobs[inst.runs % len(inst.jobs)]
        await run_job(inst, job, run_dir, paid=paid)
        if next_refresh and time.monotonic() >= next_refresh:
            # A sandbox is a copy of the repository as it was when the
            # soak started. Over eight hours the repository moves --
            # that is the point of running one while fixing things -- and
            # without this the soak spends the night testing the code of
            # the hour it began, and none of the fixes it prompted
            # (2026-09-23).
            runs, failures = inst.runs, inst.failures
            fresh = make_instance(run_dir, inst.number, rotation or tuple(inst.jobs))
            inst.root, inst.data = fresh.root, fresh.data
            inst.runs, inst.failures = runs, failures
            _log(run_dir, "refreshed", instance=inst.number, head=_head())
            next_refresh = time.monotonic() + refresh_s
        await asyncio.sleep(1.0)


def _head() -> str:
    """Which commit the sandboxes are now testing."""
    try:
        out = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def report(run_dir: Path) -> str:
    """Findings, clustered by what broke -- eight instances finding one
    bug is one bug with eight witnesses."""
    path = run_dir / "soak.jsonl"
    if not path.is_file():
        return f"no soak at {run_dir}"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    findings = [r for r in rows if r.get("kind") == "finding"]
    oks = [r for r in rows if r.get("kind") == "ok"]
    clusters: dict[str, list[dict]] = {}
    for row in findings:
        clusters.setdefault(f"{row.get('job')}: {row.get('why')}", []).append(row)
    out = [f"soak {run_dir.name}: {len(oks)} clean run(s), {len(findings)} failure(s), "
           f"{len(clusters)} distinct"]
    for why, rows_ in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        seen = sorted({r.get("instance") for r in rows_})
        out.append(f"  x{len(rows_):<3} instances {seen}  {why}")
    return "\n".join(out)


async def main_async(args) -> int:
    run_dir = SOAK_DIR / (args.run or time.strftime("%Y%m%d-%H%M"))
    if args.report:
        print(report(run_dir if args.run else max(SOAK_DIR.iterdir(), key=lambda p: p.stat().st_mtime)))
        return 0
    run_dir.mkdir(parents=True, exist_ok=True)
    rotation = tuple(args.jobs.split(",")) if args.jobs else DEFAULT_ROTATION
    for job in rotation:
        if job not in JOBS:
            raise SystemExit(f"no job called {job!r}; have {', '.join(JOBS)}")
    print(f"soak {run_dir.name}: {args.instances} instance(s), {args.hours:g}h, "
          f"{'paid' if args.paid else 'free'}, jobs {', '.join(rotation)}")
    # The start line BEFORE the copies, and one line per sandbox as it
    # lands. Eight copy-on-write clones still take minutes, and with the
    # log written afterwards a watcher saw an empty directory and no way
    # to tell "still starting" from "died" -- the same silence this
    # evening's fixes were mostly about (2026-09-23).
    _log(run_dir, "start", instances=args.instances, hours=args.hours, paid=args.paid, jobs=list(rotation))
    instances = []
    for n in range(args.instances):
        instances.append(make_instance(run_dir, n, rotation))
        _log(run_dir, "sandbox", instance=n, of=args.instances)
    until = time.monotonic() + args.hours * 3600.0
    await asyncio.gather(*(drive(i, run_dir, until=until, paid=args.paid,
                                 refresh_s=args.refresh_hours * 3600.0, rotation=rotation)
                           for i in instances))
    _log(run_dir, "end", runs=sum(i.runs for i in instances), failures=sum(i.failures for i in instances))
    print(report(run_dir))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--instances", type=int, default=8)
    ap.add_argument("--hours", type=float, default=8.0)
    ap.add_argument("--jobs", default="", help=f"comma-separated, from: {', '.join(JOBS)}")
    ap.add_argument("--run", default="", help="a run id (default: now)")
    ap.add_argument("--refresh-hours", type=float, default=1.0,
                    help="rebuild each sandbox from the repo this often, so the soak tests what is committed NOW")
    ap.add_argument("--paid", action="store_true", help="let jobs reach a real model (costs money)")
    ap.add_argument("--report", action="store_true", help="read the findings of a run and stop")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
