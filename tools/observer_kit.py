"""Shared infrastructure for the observer testing method (see `docs/
observer-testing.md`), built 2026-09-08 after eleven waves of it were
run by hand.

Three real costs were eating the time between "start a wave" and "read
its findings," and none of them needed a faster model to fix:

1. **Sandbox setup dominated wall-clock time.** Every observer did its
   own `shutil.copytree` of the repo -- 234 MB including `.git` and
   `papers/` -- which is a real byte-for-byte copy and took seconds to
   tens of seconds per agent, paid ten times over in a wave. On this
   machine's filesystem (APFS), `cp -c` clones the same tree with
   copy-on-write in about a second: no bytes move until something
   writes, so ten sandboxes cost what one used to. `fast_copy_repo`
   does this with a `shutil.copytree` fallback for a filesystem that
   does not support it, so the function is safe everywhere and fast
   where it matters.

2. **Observers shared one scratchpad directory** and collided in it
   twice in one afternoon -- one agent's files overwritten mid-run by
   another's, forcing a redo. `agent_workspace` gives each observer an
   unambiguous, collision-proof directory keyed by its own name, so
   "use your own scratchpad" is enforced by the tool rather than
   requested in a prompt.

3. **Findings came back as prose**, which is fine for a human reading
   one report and expensive for a coordinator reading ten -- four
   different observers can find the identical marker-truncation bug and
   nothing notices until someone reads all four essays end to end.
   `record_finding` writes one JSON line per finding to a run-scoped
   file; `tools/aggregate_findings.py` reads a whole wave's worth and
   clusters duplicates automatically. Prose is still the right format
   for the reasoning *behind* a finding -- this captures the fact of it
   for machines, alongside the prose for humans.

None of this changes what an observer does. It changes how long getting
ready to do it takes, and how long reading the result takes afterward.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
# Where sandboxes and findings live by default: OUTSIDE the repo, always.
# `fast_copy_repo`'s own first real run put a sandbox at
# `<repo>/scratchpad/observers/...` and cloned the repo into a directory
# nested inside itself -- the copy grew by copying its own growing
# output, and ran for minutes before it was killed (2026-09-08). A
# system temp directory can never be a subdirectory of `REPO_ROOT`, so
# this class of mistake is unreachable through the default path; the
# explicit check in `fast_copy_repo` covers a caller who overrides it.
DEFAULT_WORKSPACE_ROOT = Path(tempfile.gettempdir()) / "simorgh-observers"
# Findings live under a SEPARATE root from sandboxes, deliberately.
# Sandboxes are disposable and meant to be deleted once a wave finishes
# -- large, and a real 20-agent wave used 10 GB of them. Findings are
# the opposite: small, durable, and the entire point of running the
# wave. Putting both under one parent was a real mistake, made and
# caught the same day it landed: a wave finished, its sandboxes were
# deleted to reclaim disk (an entirely reasonable cleanup), and that
# `rm -rf` on the shared parent took the wave's whole findings file
# with it. A system temp directory is legitimately swept by disk
# pressure and by exactly this kind of cleanup; a cache directory under
# the user's home is not, and is where this now lives instead.
FINDINGS_ROOT = Path.home() / ".cache" / "simorgh-observer-findings"

# Directories an observer's sandbox never needs and that make a real
# copy needlessly slow when the fast path isn't available: build
# artifacts, and -- once the Kernel has run there -- its own ledger,
# which regenerates on boot and is *supposed* to start empty.
_SLOW_COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", ".claude", "ledger", ".simorgh",
)


def fast_copy_repo(dest: Path, *, source: Path | None = None) -> Path:
    """Clone the repo into `dest` (created fresh; must not already
    exist) as fast as the filesystem allows.

    Tries `cp -c` first -- APFS's `clonefile()`, a copy-on-write clone
    that takes about as long as reading the directory tree, independent
    of its size, and costs no extra disk until something is written.
    Falls back to `shutil.copytree` (skipping `.git` and other dead
    weight, see `_SLOW_COPY_IGNORE`) on a filesystem where that isn't
    available, so this is safe to call anywhere.

    Unlike the slow-path fallback, the fast path clones `.git` too --
    which is what lets a sandbox `git init` cheaply into a REAL history
    if a caller wants one (most observer work does not; `git init` in
    the sandbox as before is still fine and matches what most tasks
    already do).

    `dest` must not sit inside `source`. `cp -Rc source dest` with `dest`
    nested under `source` copies the destination into itself as it
    grows -- caught live on 2026-09-08 when this function's own default
    workspace location put a sandbox at `<repo>/scratchpad/observers/...`
    and the clone ran for minutes, writing a self-referential tree,
    before it was killed. `agent_workspace`'s default is now outside the
    repo for exactly this reason; this check is the second line of
    defence for any other caller.
    """
    source = (source or REPO_ROOT).resolve()
    dest = Path(dest).resolve()
    if dest.exists():
        raise FileExistsError(f"{dest} already exists -- fast_copy_repo never overwrites a sandbox")
    if dest == source or source in dest.parents:
        raise ValueError(
            f"refusing to clone {source} into {dest}, which is inside it -- "
            "the copy would recurse into its own output"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    try:
        subprocess.run(
            ["cp", "-Rc", str(source), str(dest)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        return dest
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        # Not APFS, not macOS, or `cp` doesn't support -c here. Clean up
        # any partial clone before the real copy, which must start from
        # nothing.
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(source, dest, ignore=_SLOW_COPY_IGNORE)
        return dest
    finally:
        # Not asserted on -- environments vary -- but worth knowing if
        # the fast path silently stopped working on some future machine.
        os.environ["_OBSERVER_KIT_LAST_COPY_S"] = f"{time.monotonic() - started:.2f}"


def prune_stale_workspaces(
    *, root: Path | None = None, min_age_seconds: float = 1800.0, keep_prefix: str | None = None,
) -> list[Path]:
    """Delete old sandbox directories directly under `root` (default
    `DEFAULT_WORKSPACE_ROOT`) to reclaim disk automatically, instead of
    relying on someone noticing and doing it by hand.

    A finished wave's sandboxes are pure disk waste -- a real 14-agent
    wave used ~3.7 GB, and they accumulated across waves 6/7/8 to 13 GB
    before anyone thought to clean them up (2026-09-08: the coordinator
    did it manually, on a direct nudge, when it should have happened on
    its own the moment the next wave started). This is safe to call
    freely because `FINDINGS_ROOT` lives under a wholly separate parent
    (`~/.cache`, not this function's `root`) precisely so a sweep here
    can never take a wave's findings with it -- see `FINDINGS_ROOT`'s
    own docstring for the incident that made that separation mandatory.

    Only directories with no activity in the last `min_age_seconds` are
    removed, and `keep_prefix` (typically the wave about to be staged)
    is always spared -- both guard against pruning a sandbox some other
    concurrently-running wave is still actively using. Returns the
    paths actually removed, for the caller to log.

    "No activity" is the newest mtime of ANY file anywhere under the
    workspace directory, not the workspace directory's own mtime. A
    real incident (2026-09-08) found the difference matters: a
    workspace dir's own mtime is set once at `mkdir` time
    (`agent_workspace()`) and never updated again -- creating its
    `repo/` subdirectory doesn't touch it, and neither does any file
    changed deep inside `repo/` afterward, including every commit an
    agent makes there. That made a workspace look "stale" the moment
    it crossed `min_age_seconds` in wall-clock age, regardless of
    whether an agent was still actively working in it -- an agent
    running a real trial suite (tens of minutes) had its own sandbox,
    with a fix not yet committed, deleted out from under it mid-run.
    """
    root = Path(root) if root is not None else DEFAULT_WORKSPACE_ROOT
    if not root.is_dir():
        return []
    cutoff = time.time() - min_age_seconds
    removed = []
    for entry in root.iterdir():
        if not entry.is_dir() or entry.name == "findings":
            continue
        if keep_prefix and entry.name.startswith(keep_prefix):
            continue
        try:
            if _newest_mtime_under(entry) >= cutoff:
                continue
        except OSError:
            continue
        shutil.rmtree(entry, ignore_errors=True)
        removed.append(entry)
    return removed


def _newest_mtime_under(path: Path) -> float:
    """The most recent mtime of `path` itself or anything under it --
    real activity, not just "when was this directory created." See
    `prune_stale_workspaces`'s docstring for why the directory's own
    mtime alone is not enough."""
    newest = path.stat().st_mtime
    for dirpath, _dirnames, filenames in os.walk(path):
        try:
            newest = max(newest, os.stat(dirpath).st_mtime)
        except OSError:
            continue
        for name in filenames:
            try:
                newest = max(newest, os.stat(os.path.join(dirpath, name)).st_mtime)
            except OSError:
                continue
    return newest


def agent_workspace(name: str, *, parent: Path | None = None) -> Path:
    """A fresh, collision-proof directory for one observer.

    `name` should be short and identify the observer ("gaia-reader",
    "cancel-timing") -- it becomes part of the path so a human skimming
    the wave's scratchpad can tell whose files are whose. A short random
    suffix is still added: two observers given the same loose name (or
    the same observer re-run) must never collide the way the shared
    scratchpad did on 2026-09-08.
    """
    parent = parent or DEFAULT_WORKSPACE_ROOT
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in name) or "observer"
    workspace = Path(parent) / f"{safe}-{uuid.uuid4().hex[:8]}"
    workspace.mkdir(parents=True, exist_ok=False)
    return workspace


Severity = Literal["blocker", "degraded", "cosmetic"]


@dataclasses.dataclass(frozen=True)
class Finding:
    """One observed defect, in the shape `aggregate_findings.py` clusters
    on. Keep `file`/`line` populated whenever the finding names one --
    that pair is most of the clustering signal, along with `category`.
    """

    observer: str
    severity: Severity
    summary: str
    category: str = ""          # short slug: "marker-truncation", "boot-order", ...
    file: str = ""               # repo-relative path, if the finding names one
    line: int = 0
    evidence: str = ""            # a quoted log line, ledger entry, or command output
    fix_suggested: str = ""
    run_id: str = ""              # set by record_finding from SIMORGH_OBSERVER_RUN_ID if present


def _findings_path(run_id: str) -> Path:
    out = FINDINGS_ROOT / f"{run_id}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def record_finding(
    observer: str, severity: Severity, summary: str, *,
    category: str = "", file: str = "", line: int = 0,
    evidence: str = "", fix_suggested: str = "", run_id: str | None = None,
) -> Finding:
    """Append one finding as a JSON line to this wave's shared file.

    `run_id` groups a wave together for `aggregate_findings.py`; pass it
    explicitly, or set `SIMORGH_OBSERVER_RUN_ID` once per wave and every
    call in every observer's process picks it up automatically. Appends
    are line-buffered text writes, which are atomic for a line this
    short on every platform this runs on -- ten observers writing
    concurrently is the expected case, not an edge one.
    """
    run_id = run_id or os.environ.get("SIMORGH_OBSERVER_RUN_ID", "unscoped")
    finding = Finding(
        observer=observer, severity=severity, summary=summary, category=category,
        file=file, line=line, evidence=evidence, fix_suggested=fix_suggested, run_id=run_id,
    )
    with _findings_path(run_id).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dataclasses.asdict(finding)) + "\n")
    return finding


def load_findings(run_id: str) -> list[Finding]:
    path = _findings_path(run_id)
    if not path.exists():
        return []
    findings = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                findings.append(Finding(**json.loads(line)))
    return findings


def new_run_id(label: str = "wave") -> str:
    """A run id for a fresh wave, shareable as `SIMORGH_OBSERVER_RUN_ID`
    across every observer's environment."""
    return f"{label}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


__all__ = [
    "REPO_ROOT",
    "Finding",
    "Severity",
    "agent_workspace",
    "fast_copy_repo",
    "load_findings",
    "new_run_id",
    "record_finding",
]
