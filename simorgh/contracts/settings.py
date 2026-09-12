"""Where Sim's settings live, and the one-time hand-off of a secret from
the terminal to a tool.

A password typed on a command line becomes a tool proposal, and every
proposal is ledgered -- so `cameras setup <host> <user> <password>` had
been writing the NVR's password into the ledger (the creator,
2026-09-12: "the password may leak to sim logs"). The terminal now asks
for the password hidden (`getpass`), writes it to a hand-off file only
the owner can read, and the tool reads and deletes that file; the
proposal carries no password at all.

`settings_home()` mirrors the Kernel's search order for `simorgh.toml`
(`$SIMORGH_CONFIG`, `./simorgh.toml`, `~/.simorgh/`) without importing
the Kernel, so both the interface and execution agree on the directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def settings_home(home: Path | None = None) -> Path:
    if home is not None:
        return Path(home)
    env = os.environ.get("SIMORGH_CONFIG")
    if env:
        return Path(env).expanduser().parent
    if Path("simorgh.toml").is_file():
        return Path.cwd()
    return Path("~/.simorgh").expanduser()


def handoff_path(name: str, home: Path | None = None) -> Path:
    safe = "".join(ch for ch in name.lower() if ch.isalnum() or ch in "-_") or "secret"
    return settings_home(home) / f"handoff-{safe}.json"


def write_handoff(name: str, values: dict[str, str], home: Path | None = None) -> Path:
    """Write `values` for one tool to read once; owner-only, atomic."""
    path = handoff_path(name, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(values), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    path.chmod(0o600)
    return path


def read_handoff(name: str, home: Path | None = None) -> dict[str, str]:
    """The values handed off, deleting the file; {} when there is none."""
    path = handoff_path(name, home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


__all__ = ["handoff_path", "read_handoff", "settings_home", "write_handoff"]
