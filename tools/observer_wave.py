"""Pre-stage a wave of observer sandboxes before any agent starts.

Every prior wave had each observer spend its own first minute doing a
`shutil.copytree` of the repo. That is `N` slow copies for one `N`-agent
wave, on the coordinator's own clock even though the copies could all
happen before a single agent is launched. This does them up front, with
`observer_kit.fast_copy_repo` (copy-on-write on APFS, instant
regardless of size), so an agent's sandbox is sitting there ready the
moment it starts.

Usage:

    python tools/observer_wave.py --count 10 --label gaia
    # prints, one per line:
    #   gaia-01  /path/to/scratchpad/observers/gaia-01-3f9a1c2b
    #   gaia-02  /path/to/scratchpad/observers/gaia-02-7b0e44d1
    #   ...
    #   RUN_ID=gaia-20260908-153000-a1b2c3

Paste the run id into every observer's brief as
`SIMORGH_OBSERVER_RUN_ID`, and each numbered path as that observer's own
sandbox root and scratchpad -- so nothing is shared and nothing is
copied twice.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `tools/` is not a package
from observer_kit import agent_workspace, fast_copy_repo, new_run_id, prune_stale_workspaces  # noqa: E402


def stage_wave(count: int, *, label: str = "observer") -> tuple[str, list[Path]]:
    """Returns `(run_id, [sandbox_path, ...])`, one sandbox per observer,
    each already a full repo clone ready to `git init` and use.

    Prunes sandboxes left over from earlier waves first (2026-09-08: a
    prior wave's sandboxes were only ever reclaimed by someone noticing
    and doing it by hand, and grew to 13 GB across three waves before
    that happened) -- see `prune_stale_workspaces` for why this is safe
    to do unconditionally on every new wave."""
    removed = prune_stale_workspaces(keep_prefix=label)
    if removed:
        print(f"# pruned {len(removed)} stale sandbox(es) from earlier waves", file=sys.stderr)
    run_id = new_run_id(label)
    sandboxes = []
    for i in range(1, count + 1):
        workspace = agent_workspace(f"{label}-{i:02d}")
        repo = fast_copy_repo(workspace / "repo")
        pin_data_dir(repo, workspace / "data")
        sandboxes.append(repo)
    return run_id, sandboxes


def pin_data_dir(repo: Path, data_dir: Path) -> Path:
    """Write a `simorgh.toml` into the sandbox so ANY Sim booted from it
    -- `sim.sh`, `python -m simorgh run`, an ad-hoc Kernel in a script --
    keeps its Ledger under the sandbox, not under `~/.simorgh`.

    `kernel/config.py::find_config_path` reads `./simorgh.toml` before it
    falls back to the default data dir, and the real repo ships no such
    file, so a Kernel booted inside a sandbox with no config of its own
    lands in the creator's LIVE ledger. On 2026-09-10 an observer's
    claim-race experiment did exactly that: 325 synthetic `race N` tasks
    (origin `human`, workers `wA`/`wC`/`w1`, no percept behind any of
    them) appeared in the live store, 312 of them `available`, and the
    creator's own Sim spent an evening offering them to its workers.
    Telling each observer to export `SIMORGH_RUNTIME_DATA_DIR` is one
    forgotten line from that; a file in the sandbox is not."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (repo / "simorgh.toml").write_text(
        "# Written by tools/observer_wave.py: this sandbox's Sim keeps its data here,\n"
        "# never in ~/.simorgh.\n"
        "[runtime]\n"
        f'data_dir = "{data_dir}"\n'
    )
    return repo / "simorgh.toml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--count", type=int, default=10, help="how many sandboxes to stage")
    parser.add_argument("--label", default="observer", help="short name for this wave, e.g. 'gaia'")
    args = parser.parse_args(argv)

    started = time.monotonic()
    run_id, sandboxes = stage_wave(args.count, label=args.label)
    elapsed = time.monotonic() - started

    for i, sandbox in enumerate(sandboxes, start=1):
        print(f"{args.label}-{i:02d}  {sandbox}")
    print(f"RUN_ID={run_id}")
    print(f"# staged {len(sandboxes)} sandbox(es) in {elapsed:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
