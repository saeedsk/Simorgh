"""Put one task to Sim, under control, and watch every turn.

The creator, 2026-09-07, after this method found five separate blockers
that had kept Sim from ever editing its own source: "we repeat the
experience you just did, we ask sim for different type of tasks which
requires different way of thinking, using different tools and perform
different thing, then you closely watch and observe it and we will
discover bugs one by one and fix them."

Everything here exists to make one task legible:

- **Autonomy off.** Nothing self-directed runs, so the only thing moving
  is the task under test. Otherwise a hundred curiosity tasks compete for
  the same worker and the same provider and nothing is observable.
- **An isolated repo.** Sim's write tools are real. It runs against a
  copy, so a trial can apply and commit for real without touching
  anything that matters, and the copy is reset between trials.
- **The model's own words.** Replies come back on a private inbox rather
  than a topic, so they cannot be observed from the bus at all; this
  hooks the parser instead, which is the one place every reply passes
  through.

Usage:

    python tools/trial.py "the task text" --kind patch --subject simorgh/x.py

`--keep` leaves the lab repo in place afterwards, for looking at what it
actually wrote.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # `tools/` is not a package

from observer_kit import fast_copy_repo  # noqa: E402
from simorgh.contracts import topics  # noqa: E402
import simorgh.cognition.parser as parser_mod  # noqa: E402
from simorgh.kernel.config import LoadedConfig  # noqa: E402
from simorgh.kernel.secrets import EnvSecretStore  # noqa: E402
from simorgh.kernel.service import Kernel  # noqa: E402

SAID: list[tuple[str, str]] = []
_orig_parse = parser_mod.OutputParser.parse


def _probe(self, text, expected):
    out = _orig_parse(self, text, expected)
    if (expected or {}).get("kind") == "markers":
        SAID.append((out.kind, text))
    return out


parser_mod.OutputParser.parse = _probe


def git(repo: str, *args: str) -> str:
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return done.stdout.strip()


def make_lab(root: str) -> str:
    """A throwaway copy of this repo, with its own git history.

    Cloned with `observer_kit.fast_copy_repo` (APFS copy-on-write, a
    `shutil.copytree` fallback elsewhere): the copy is near-instant and
    costs no disk until something writes, where the old `copytree`
    duplicated the whole tree -- `papers/` alone is 109 MB -- per trial.
    The clone brings `.git` along; it is removed so the lab's history
    starts at "trial baseline" exactly as before, which `run_trial`'s
    "what it changed" report relies on.
    """
    repo = os.path.join(root, "repo")
    fast_copy_repo(Path(repo), source=REPO_ROOT)
    shutil.rmtree(os.path.join(repo, ".git"), ignore_errors=True)
    shutil.rmtree(os.path.join(repo, ".claude"), ignore_errors=True)
    git(repo, "init", "-q")
    subprocess.run(["git", "-C", repo, "add", "-A"], capture_output=True)
    subprocess.run(
        ["git", "-C", repo, "-c", "user.email=lab@local", "-c", "user.name=Lab",
         "commit", "-qm", "trial baseline"],
        capture_output=True,
    )
    return repo


async def run_trial(task: str, *, kind: str, subject: str | None, root: str, timeout_s: float,
                    max_steps: int = 0, attempts: int = 1) -> int:
    repo = make_lab(root)
    os.chdir(repo)
    kernel = Kernel(
        LoadedConfig({
            "runtime": {"data_dir": os.path.join(root, "data")},
            # Explicit, not inferred from the cwd `os.chdir(repo)` set
            # above: `find_repo_root` reads the cwd at boot, and a lab
            # that ran in a shared process would otherwise point Sim's
            # write tools at whichever repo was current that instant.
            "execution": {"repo_root": repo},
            # The point of a trial: nothing self-directed competes with it.
            "curiosity": {"autonomy_on_boot": False},
        }, None),
        secrets=EnvSecretStore({}),
    )
    await kernel.boot()
    steps: list[tuple] = []
    await kernel.bus.subscribe(topics.TASK_STEP, lambda m: steps.append(
        (m.payload.get("tool"), (m.payload.get("summary") or "")[:76], m.payload.get("ok")),
    ) or asyncio.sleep(0))

    print(f"\n=== TASK ({kind}) ===\n{task}\n")
    payload = {"kind": kind, "description": task, "origin": "human", "mode": "execute"}
    if subject:
        payload["subject"] = subject
    if max_steps:
        payload["max_steps"] = max_steps
    reply = await kernel.bus.request(kernel.bus.new(topics.TASK_CREATE, payload), timeout=10)
    task_id = reply.payload["task_id"]

    planning = kernel._supervisor.services["planning"].service  # noqa: SLF001
    started = time.monotonic()
    while time.monotonic() - started < timeout_s:
        await asyncio.sleep(1)
        record = await planning._store.get(task_id)  # noqa: SLF001
        if not record:
            continue
        if record.status in ("completed", "failed"):
            break
        # A task that only ran out of steps is a continuation, not an
        # ending: Planning re-offers it within seconds with a fresh
        # budget and a memory of the attempt. `--attempts` says how many
        # of those to sit through before calling it.
        if record.status == "blocked" and record.attempts >= attempts:
            break
    record = await planning._store.get(task_id)  # noqa: SLF001

    print(f"=== OUTCOME: {record.status if record else 'timed out'} "
          f"in {time.monotonic() - started:.0f}s ===\n")
    print("what it did:")
    for tool, summary, ok in steps:
        if tool is None and summary.startswith("asking"):
            continue
        print(f"   {str(tool or 'final answer'):20s} ok={ok}  {summary}")

    print("\nwhat it said:")
    for index, (out_kind, text) in enumerate(SAID, start=1):
        print(f"   {index}. [{out_kind}] {text.strip()[:220]}")

    print("\nwhat it changed:")
    dirty, log = git(repo, "status", "--short"), git(repo, "log", "--oneline", "-3")
    print(f"   working tree: {dirty or '(clean)'}")
    print(f"   commits:\n      " + (log.replace("\n", "\n      ") or "(none)"))
    diff = git(repo, "diff", "HEAD~1", "--stat") if "trial baseline" not in log.splitlines()[0] else ""
    if diff:
        print(f"   diff: {diff}")

    await kernel.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one watched task against an isolated copy of this repo.")
    parser.add_argument("task", help="what to ask Sim to do")
    parser.add_argument("--kind", default="patch", choices=("patch", "skill", "research", "project", "chat"))
    parser.add_argument("--subject", default=None, help="the file the task is about, when it has one")
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--keep", action="store_true", help="leave the lab repo behind for inspection")
    parser.add_argument("--max-steps", type=int, default=0,
                        help="per-attempt step cap for this task; a small one exercises the "
                             "continuation path, where the work spans attempts")
    parser.add_argument("--attempts", type=int, default=1,
                        help="how many attempts to watch before giving up on a task that keeps "
                             "running out of steps")
    args = parser.parse_args(argv)

    root = tempfile.mkdtemp(prefix="simorgh-trial-")
    try:
        return asyncio.run(run_trial(
            args.task, kind=args.kind, subject=args.subject, root=root, timeout_s=args.timeout,
            max_steps=args.max_steps, attempts=args.attempts,
        ))
    finally:
        if args.keep:
            print(f"\nlab kept at {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
