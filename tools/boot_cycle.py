#!/usr/bin/env python3
"""Boot Sim, let it settle, stop it properly, and check what it left.

    python tools/boot_cycle.py                 # one cycle here
    python tools/boot_cycle.py --cycles 5
    python tools/boot_cycle.py --signal TERM --settle 20

Shutdown is where this system's live bugs have lived: Ctrl-C ignored
while a tool thread was busy (fixed with a Stopper and `os._exit`),
whisper servers outliving the process that started them (fixed by
reaping orphans at start), a ledger left locked. None of those were
found by a test -- they were found by somebody closing the terminal and
looking.

So this closes the terminal, repeatedly, and looks:

  it stops      the signal is obeyed within `--grace` seconds, rather
                than the process sitting there with a thread mid-tool
  it is quiet   nothing a person would call a crash on the way out --
                a traceback, an unraisable exception, a `Task was
                destroyed but it is pending`
  it lets go    no child outlives it (a whisper server, an ffmpeg
                relay), because each holds a model or a camera open
  it can be re-read   the ledger it wrote opens again afterwards, which
                is the claim the whole architecture rests on

Free: the floor provider answers, so a cycle costs nothing and can run
in a loop for hours. What it exercises is boot, subscribe, tick and
teardown across every subsystem, which is most of the code that runs
before anybody says anything.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: What "it crashed on the way out" looks like in the output.
_UGLY = (
    ("Traceback (most recent call last)", "a stack trace on shutdown"),
    ("Task was destroyed but it is pending", "a task dropped mid-flight"),
    ("Exception ignored in", "an exception nobody could raise"),
    ("coroutine .* was never awaited", "a coroutine dropped"),
    ("Fatal Python error", "the interpreter itself"),
)
#: Processes Sim starts that must not outlive it.
_CHILDREN = ("whisper-server", "whisper-cli", "ffmpeg", "styletts2_server", "miso_server", "pocket_server")


def _orphans() -> list[str]:
    """Children of pid 1 that look like ours."""
    try:
        out = subprocess.run(["ps", "-ax", "-o", "ppid=,command="], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in (out or "").splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2 or parts[0] != "1":
            continue
        name = Path(parts[1].split()[0]).name
        if any(child in parts[1] for child in _CHILDREN) and name != "python":
            found.append(parts[1][:80])
    return found


def cycle(data: Path, *, settle: float, grace: float, sig: int) -> dict:
    """One boot, one stop, one look at what is left."""
    before = set(_orphans())
    env = dict(os.environ, HOME=str(data), SIMORGH_DATA_DIR=str(data / ".simorgh"),
               SIMORGH_NO_LOADER="1", SIMORGH_COGNITION_PROVIDER_ORDER="floor",
               PYTHONUNBUFFERED="1")
    for key in ("TOGETHER_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(key, None)
    started = time.monotonic()
    proc = subprocess.Popen([sys.executable, "-m", "simorgh", "run"], cwd=str(REPO), env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    time.sleep(settle)
    booted = proc.poll() is None
    proc.send_signal(sig)
    try:
        out = proc.communicate(timeout=grace)[0] or ""
        stopped_in = time.monotonic() - started - settle
        timed_out = False
    except subprocess.TimeoutExpired:
        proc.kill()
        out = proc.communicate()[0] or ""
        stopped_in, timed_out = grace, True

    ugly = [why for mark, why in _UGLY if mark in out]
    leaked = sorted(set(_orphans()) - before)
    return {
        "booted": booted,
        "stopped_in_s": round(stopped_in, 1),
        "ignored_the_signal": timed_out,
        "ugly": ugly,
        "leaked_children": leaked,
        "ledger_readable": _ledger_readable(data),
        "exit_code": proc.returncode,
        "tail": out[-1200:] if (ugly or timed_out) else "",
    }


def _ledger_readable(data: Path) -> bool:
    """The ledger it just wrote opens again -- the claim everything else
    rests on (ARCHITECTURE section 3.2, invariant 3)."""
    streams = data / ".simorgh" / "ledger" / "streams"
    if not streams.is_dir():
        return True                      # nothing written is not unreadable
    try:
        for path in list(streams.glob("*.jsonl"))[:40]:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
    except (OSError, ValueError):
        return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--settle", type=float, default=25.0, help="seconds to let it finish booting")
    ap.add_argument("--grace", type=float, default=20.0, help="seconds it may take to stop")
    ap.add_argument("--signal", default="INT", choices=["INT", "TERM"])
    ap.add_argument("--data", default="", help="data directory (a temp one per cycle by default)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    sig = signal.SIGINT if args.signal == "INT" else signal.SIGTERM
    results = []
    for n in range(args.cycles):
        import tempfile

        if args.data:
            data = Path(args.data)
            data.mkdir(parents=True, exist_ok=True)
        else:
            data = Path(tempfile.mkdtemp(prefix="simorgh-boot-"))
        try:
            result = cycle(data, settle=args.settle, grace=args.grace, sig=sig)
        finally:
            if not args.data:
                import shutil

                shutil.rmtree(data, ignore_errors=True)
        result["cycle"] = n + 1
        results.append(result)
        if not args.json:
            bad = (result["ignored_the_signal"] or result["ugly"] or result["leaked_children"]
                   or not result["ledger_readable"] or not result["booted"])
            print(f"cycle {n + 1}: {'FAIL' if bad else 'ok  '} "
                  f"booted={result['booted']} stopped in {result['stopped_in_s']}s "
                  f"exit={result['exit_code']}"
                  + (f" IGNORED THE {args.signal}" if result["ignored_the_signal"] else "")
                  + (f" ugly={result['ugly']}" if result["ugly"] else "")
                  + (f" leaked={result['leaked_children']}" if result["leaked_children"] else "")
                  + ("" if result["ledger_readable"] else " LEDGER UNREADABLE"), flush=True)
            if result["tail"]:
                print(result["tail"])
    if args.json:
        print(json.dumps(results, indent=1))
    bad = [r for r in results if r["ignored_the_signal"] or r["ugly"] or r["leaked_children"]
           or not r["ledger_readable"] or not r["booted"]]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
