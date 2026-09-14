"""Run benchmark rounds against one isolated copy of Sim until a deadline.

The creator, 2026-09-14: "10 instances, across all benchmark models" for
six hours. One process is one instance: a copy-on-write clone of this
repo with its own data directory -- its own ledger, its own Together
budget -- booted headless with autonomy off, asked for benchmark runs
over the bus exactly as `benchmark run` asks, one suite after another,
until `--until`. Every finished (or cut-short) run is appended as one
JSON line to `--out`, a file shared by all instances, outside every copy.

Cognition is limited to Together and the offline floor
(SIMORGH_COGNITION_PROVIDER_ORDER): a copy that spends its day's
Together budget answers from the floor rather than failing over to the
Claude CLI, which costs far more. SWE-bench pulls a ~3 GB image per
case, so no new run starts while free disk is under `--min-free-gb`.

Usage:

    python tools/bench_instance.py --id 3 --suites gaia-l1,bfcl-parallel --limit 10 \\
        --until 1789434440 --out /tmp/bench-wave/results.jsonl
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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # `tools/` is not a package

from observer_kit import DEFAULT_WORKSPACE_ROOT  # noqa: E402
from simorgh.contracts import topics  # noqa: E402
from simorgh.kernel.config import LoadedConfig  # noqa: E402
from simorgh.kernel.secrets import EnvSecretStore  # noqa: E402
from simorgh.kernel.service import Kernel  # noqa: E402


def say(instance: int, line: str) -> None:
    print(f"[bench {instance} {time.strftime('%H:%M:%S')}] {line}", flush=True)


#: Not copied into a benchmark copy. `workspace/` alone was 6 GB (voice
#: recordings, old SWE-bench checkouts, TV media): the first wave's clones
#: timed out under load, `observer_kit.fast_copy_repo` fell back to a real
#: byte copy without saying so, and ten copies took the disk from 53 GB
#: free to under 4 GB in minutes (2026-09-14).
_NOT_COPIED = {".git", ".claude", "workspace", "papers", "images", "results", ".simorgh_loader",
               "__pycache__", ".pytest_cache", "node_modules"}
#: A copy that costs more than this is not copy-on-write any more; stop.
_MAX_STAGE_GB = 1.0


def stage(root: Path) -> Path:
    """A throwaway copy of this repo's code with a fresh history. Each
    top-level entry is cloned copy-on-write (`cp -c`, no timeout to fall
    back on), big untracked folders are left out, and the copy is refused
    if it cost real disk."""
    repo = root / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    before = free_gb(root)
    for entry in sorted(REPO_ROOT.iterdir()):
        if entry.name in _NOT_COPIED:
            continue
        done = subprocess.run(["cp", "-Rc", str(entry), str(repo / entry.name)], capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"copy-on-write clone of {entry.name} failed: {done.stderr.strip()[:200]}")
    (repo / "workspace").mkdir(exist_ok=True)
    spent = before - free_gb(root)
    if spent > _MAX_STAGE_GB:
        shutil.rmtree(repo, ignore_errors=True)
        raise RuntimeError(f"staging used {spent:.1f} GB of real disk -- not a copy-on-write clone; refusing")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=bench@local", "-c", "user.name=Bench",
                    "commit", "-qm", "benchmark baseline"], capture_output=True)
    return repo


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1024 ** 3


def append(out: Path, row: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


async def run(args) -> int:
    if args.start_delay:
        await asyncio.sleep(args.start_delay)
    root = Path(args.root or DEFAULT_WORKSPACE_ROOT / f"bench-{args.wave}" / f"i{args.id}")
    root.mkdir(parents=True, exist_ok=True)
    if free_gb(root) < args.min_free_gb:
        say(args.id, f"not starting: {free_gb(root):.0f} GB free, under {args.min_free_gb}")
        return 2
    repo = stage(root)
    os.chdir(repo)
    data = root / "data"
    os.environ["SIMORGH_RUNTIME_DATA_DIR"] = str(data)
    os.environ["SIMORGH_COGNITION_PROVIDER_ORDER"] = "together,floor"
    kernel = Kernel(LoadedConfig({
        "runtime": {"data_dir": str(data)},
        "execution": {"repo_root": str(repo)},
        "curiosity": {"autonomy_on_boot": False},
    }, None), secrets=EnvSecretStore(dict(os.environ)))
    await kernel.boot()
    say(args.id, f"booted in {repo}")

    completed: asyncio.Queue = asyncio.Queue()

    async def _on_completed(message) -> None:
        await completed.put(message.payload)

    async def _on_progress(message) -> None:
        p = message.payload
        verdict = "skipped" if p.get("case_skipped") else ("correct" if p.get("case_correct") else "wrong")
        err = f" error={str(p.get('case_error'))[:80]}" if p.get("case_error") else ""
        say(args.id, f"{p.get('suite')} case {p.get('index')}/{p.get('total')} {verdict} "
                     f"({p.get('correct')}/{p.get('attempted')} so far){err}")

    await kernel.bus.subscribe(topics.BENCHMARK_RUN_COMPLETED, _on_completed)
    await kernel.bus.subscribe(topics.BENCHMARK_PROGRESS, _on_progress)

    suites = [s.strip() for s in args.suites.split(",") if s.strip()]
    offsets = {suite: max(0, args.offset) for suite in suites}
    turn = 0
    try:
        while time.time() < args.until:
            suite = suites[turn % len(suites)]
            turn += 1
            if free_gb(root) < args.min_free_gb:
                say(args.id, f"stopping: {free_gb(root):.0f} GB free, under {args.min_free_gb} -- no new runs")
                break
            payload = {"suite": suite, "limit": args.limit, "offset": offsets[suite],
                       "note": f"bench wave {args.wave} instance {args.id} offset {offsets[suite]}"}
            if args.level:
                payload["level"] = args.level
            reply = await kernel.bus.request(kernel.bus.new(topics.BENCHMARK_RUN_REQUEST, payload), timeout=120)
            if not reply.payload.get("ok", True) or not reply.payload.get("run_id"):
                error = reply.payload.get("error") or {}
                if error.get("code") == "no_cases" and offsets[suite] > 0:
                    say(args.id, f"{suite}: past the last case at offset {offsets[suite]}, back to the start")
                    offsets[suite] = 0
                    continue
                say(args.id, f"{suite} refused: {error.get('code')} -- {str(error.get('detail'))[:160]}")
                append(Path(args.out), {"wave": args.wave, "instance": args.id, "suite": suite, "refused": error,
                                        "at": time.time()})
                await asyncio.sleep(30)
                continue
            run_id = reply.payload["run_id"]
            say(args.id, f"started {suite} run {run_id}: {reply.payload.get('cases')} cases, "
                         f"model {reply.payload.get('model')}")
            summary = None
            while summary is None:
                remaining = args.until - time.time()
                if remaining <= 0:
                    say(args.id, "deadline: stopping the run in flight")
                    await kernel.bus.request(kernel.bus.new(topics.BENCHMARK_STOP_REQUEST, {}), timeout=60)
                    try:
                        summary = await asyncio.wait_for(completed.get(), timeout=300)
                    except asyncio.TimeoutError:
                        summary = None
                    break
                try:
                    candidate = await asyncio.wait_for(completed.get(), timeout=min(remaining, 300))
                except asyncio.TimeoutError:
                    continue
                if candidate.get("run_id") == run_id:
                    summary = candidate
            if summary is None:
                say(args.id, f"{suite} run {run_id}: no completion after the stop; nothing recorded")
                break
            row = {k: summary.get(k) for k in ("run_id", "suite", "suite_version", "model", "attempted", "correct",
                                                "skipped", "accuracy", "seconds", "partial", "by_level", "note")}
            row.update({"wave": args.wave, "instance": args.id, "offset": offsets[suite], "at": time.time()})
            offsets[suite] += max(1, int(summary.get("attempted") or 0) + int(summary.get("skipped") or 0)) \
                if not summary.get("partial") else 0
            append(Path(args.out), row)
            say(args.id, f"finished {suite}: {row.get('correct')}/{row.get('attempted')} correct, "
                         f"{row.get('skipped')} skipped, partial={row.get('partial')}")
    finally:
        await kernel.shutdown()
        say(args.id, "shut down")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark rounds against one isolated copy of Sim until a deadline.")
    parser.add_argument("--id", type=int, required=True)
    parser.add_argument("--suites", required=True, help="comma-separated, run in rotation")
    parser.add_argument("--limit", type=int, default=10, help="cases per run")
    parser.add_argument("--level", default="")
    parser.add_argument("--offset", type=int, default=0, help="where each suite's first slice starts")
    parser.add_argument("--until", type=float, required=True, help="epoch seconds to stop by")
    parser.add_argument("--out", required=True, help="shared JSONL of run summaries")
    parser.add_argument("--wave", default="w1")
    parser.add_argument("--root", default="")
    parser.add_argument("--min-free-gb", type=float, default=20.0)
    parser.add_argument("--start-delay", type=float, default=0.0, help="seconds to wait before staging")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
