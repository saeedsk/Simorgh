#!/usr/bin/env python3
"""kill_resume_trial: SIGKILL Sim mid-task, boot it again, and check the task
finishes without redoing work or repeating an irreversible action.

Stage 0 item 30 (docs/plan/stage-0-safety-gaps-wires-gate.md). The existing
crash-resume test covers the `local-multi` worker mode nobody runs; this is
the drill for the mode Sim actually uses: ONE process, the in-memory bus, the
jsonl ledger on disk. The only thing that survives the kill is the ledger,
which is the claim the architecture makes (docs/ARCHITECTURE.md section 3.2,
invariant 3).

    python tools/kill_resume_trial.py                 # default task, kill after 2 completed steps
    python tools/kill_resume_trial.py --kill-after 3 --max-usd 1.0
    python tools/kill_resume_trial.py --keep          # leave the lab for inspection

How it works:
  1. A lab: a copy of this repo with its own git history, and a data dir.
  2. Child A boots Sim on the lab, creates the task, and runs until the
     task's ledger stream shows `--kill-after` completed steps. The parent
     then SIGKILLs it -- no shutdown, no flush beyond what fsync already did.
  3. Child B boots Sim on the SAME data dir and lab. Nothing re-creates
     the task: the lease left behind by A expires, Planning re-offers it,
     a worker claims it and `orchestration/resume.py` resumes it.
  4. The parent judges from the ledger and git:
     - the task ended `completed`;
     - no successful write after the kill repeats one that had succeeded
       before it (redone work);
     - git has at most one commit per `git_commit` step the task recorded as
       ok, and no commit was made twice (an irreversible action repeated).

Real model calls: Cognition is pinned to Together + the floor with a spend
cap per child (`--max-usd`), for the same reason as tools/trial_suite.py.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOLS = Path(__file__).resolve().parent

DEFAULT_TASK = (
    "Create a new file workspace/kill_resume/notes.py containing a function add(a, b) that returns a + b, "
    "with a one-line docstring. Then add a second function mul(a, b) that returns a * b in the same file. "
    "Run the tests for that file if there are any, then commit the file with a short message."
)

_CHILD = r'''
import asyncio, json, os, sys, time
sys.path.insert(0, {repo_root!r})
os.chdir({lab!r})
os.environ["SIMORGH_RUNTIME_DATA_DIR"] = {data!r}
from simorgh.contracts import topics
from simorgh.kernel.config import LoadedConfig
from simorgh.kernel.secrets import EnvSecretStore
from simorgh.kernel.service import Kernel

async def main():
    kernel = Kernel(LoadedConfig({{
        "runtime": {{"data_dir": {data!r}}},
        "execution": {{"repo_root": {lab!r}}},
        "curiosity": {{"autonomy_on_boot": False}},
        "cognition": {{"provider_order": ["together", "floor"],
                       "providers": {{"together": {{"max_spend_usd": {max_usd}, "window_seconds": 86400.0}}}}}},
    }}, None), secrets=EnvSecretStore())
    await kernel.boot()
    if {create!r}:
        payload = {{"kind": "patch", "description": {task!r}, "origin": "human", "mode": "execute"}}
        reply = await kernel.bus.request(kernel.bus.new(topics.TASK_CREATE, payload), timeout=10)
        print("TASK_ID " + reply.payload["task_id"], flush=True)
    planning = kernel._supervisor.services["planning"].service
    deadline = time.monotonic() + {timeout}
    while time.monotonic() < deadline:
        await asyncio.sleep(1)
        tasks = [t for t in planning._store.all() if t.kind == "patch"] if hasattr(planning._store, "all") else []
        done = [t for t in tasks if t.status in ("completed", "failed")]
        if done:
            print("FINAL " + done[0].status, flush=True)
            break
    await kernel.shutdown()

asyncio.run(main())
'''


_MUTATING = frozenset({"write_file", "create_file", "apply_source_patch", "replace_in_file", "git_commit",
                       "worktree_land", "apply_skill"})


def _git(repo: str, *args: str) -> str:
    done = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return done.stdout.strip()


def _task_events(data: Path, task_id: str) -> list[dict]:
    path = data / "ledger" / "streams" / f"task%3A{task_id}.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(errors="replace").splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def _steps(events: list[dict]) -> list[dict]:
    out = []
    for event in events:
        body = event.get("payload") or event.get("event", {}).get("payload") or {}
        etype = event.get("type") or event.get("event", {}).get("type")
        if etype in ("task.step", "step") and body.get("step_no") is not None:
            out.append(body)
    return out


def _spawn(lab: str, data: str, *, create: bool, task: str, max_usd: float, timeout: float) -> subprocess.Popen:
    code = _CHILD.format(repo_root=str(REPO_ROOT), lab=lab, data=data, create=create, task=task,
                         max_usd=max_usd, timeout=timeout)
    return subprocess.Popen([sys.executable, "-u", "-c", code], cwd=lab, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)


def run(task: str, *, kill_after: int, max_usd: float, timeout: float, keep: bool) -> dict:
    sys.path.insert(0, str(TOOLS))
    from observer_kit import fast_copy_repo

    root = tempfile.mkdtemp(prefix="simorgh-killresume-")
    lab, data = os.path.join(root, "repo"), os.path.join(root, "data")
    fast_copy_repo(Path(lab), source=REPO_ROOT)
    shutil.rmtree(os.path.join(lab, ".git"), ignore_errors=True)
    shutil.rmtree(os.path.join(lab, ".claude"), ignore_errors=True)
    _git(lab, "init", "-q")
    subprocess.run(["git", "-C", lab, "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", lab, "-c", "user.email=lab@local", "-c", "user.name=Lab", "commit", "-qm", "trial baseline"],
                   capture_output=True)
    base_commits = int(_git(lab, "rev-list", "--count", "HEAD") or 0)
    report: dict = {"lab": root if keep else "", "kill_after": kill_after}

    # 1. child A: create the task and work until `kill_after` steps are on disk
    a = _spawn(lab, data, create=True, task=task, max_usd=max_usd, timeout=timeout)
    task_id = ""
    started = time.monotonic()
    os.set_blocking(a.stdout.fileno(), False)
    buffer = ""
    while time.monotonic() - started < timeout:
        time.sleep(0.5)
        try:
            buffer += a.stdout.read() or ""
        except (TypeError, OSError):
            pass
        if not task_id and "TASK_ID " in buffer:
            task_id = buffer.split("TASK_ID ", 1)[1].split()[0]
        if task_id and len(_steps(_task_events(Path(data), task_id))) >= kill_after:
            break
        if a.poll() is not None:
            break
    report["task_id"] = task_id
    report["steps_before_kill"] = len(_steps(_task_events(Path(data), task_id))) if task_id else 0
    report["a_finished_on_its_own"] = a.poll() is not None
    if a.poll() is None:
        a.send_signal(signal.SIGKILL)
        a.wait()
    report["commits_before_kill"] = int(_git(lab, "rev-list", "--count", "HEAD") or 0) - base_commits

    # 2. child B: same data dir, no task creation; it must pick the task up
    b = _spawn(lab, data, create=False, task=task, max_usd=max_usd, timeout=timeout)
    try:
        out, _ = b.communicate(timeout=timeout + 60)
    except subprocess.TimeoutExpired:
        b.kill()
        out = ""
    final = out.split("FINAL ", 1)[1].split()[0] if "FINAL " in out else "unfinished"
    report["final"] = final

    # 3. judge
    steps = _steps(_task_events(Path(data), task_id)) if task_id else []
    # Redone work: after the kill, a successful write that repeats one that
    # had already succeeded before it (same tool, same summary head). Reads
    # may repeat harmlessly; writes and commits may not. Step numbers keep
    # counting up across a resume, so a reused number is not the signal.
    cut = report["steps_before_kill"]
    before = {(s.get("tool"), str(s.get("summary", ""))[:80]) for s in steps[:cut] if s.get("ok")}
    report["steps_total"] = len(steps)
    report["redone_steps"] = [int(s["step_no"]) for s in steps[cut:]
                              if s.get("ok") and s.get("tool") in _MUTATING
                              and (s.get("tool"), str(s.get("summary", ""))[:80]) in before]
    commits_ok = sum(1 for s in steps if s.get("tool") == "git_commit" and s.get("ok"))
    commits = int(_git(lab, "rev-list", "--count", "HEAD") or 0) - base_commits
    subjects = _git(lab, "log", "--format=%s", f"-{max(commits, 1)}").splitlines() if commits else []
    report["commits"] = commits
    report["git_commit_steps_ok"] = commits_ok
    report["duplicate_commit_subjects"] = len(subjects) - len(set(subjects))
    report["ok"] = (final == "completed" and not report["redone_steps"]
                    and report["duplicate_commit_subjects"] == 0 and commits <= max(commits_ok, 1))
    if not keep:
        shutil.rmtree(root, ignore_errors=True)
    return report


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--task", default=DEFAULT_TASK)
    ap.add_argument("--kill-after", type=int, default=2, help="completed steps on disk before the SIGKILL")
    ap.add_argument("--max-usd", type=float, default=1.0, help="Together spend cap per child process")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)
    report = run(args.task, kill_after=args.kill_after, max_usd=args.max_usd, timeout=args.timeout, keep=args.keep)
    print(json.dumps(report, indent=1))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
